"""Disposable native workers with cancellation, wall time and output limits.

No shell interpolation. This is failure isolation, not an OS security sandbox.
The parent never loads PDF engines. Temporary stdout/stderr are bounded while
workers run, not only after they exit.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT = 48 * 1024 * 1024
MAX_STDERR = 2 * 1024 * 1024


def _terminate(proc) -> None:
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


def run_worker(request: dict, *, timeout: float = 60, cancel_event=None) -> dict:
    if not 0 < timeout <= 600:
        raise ValueError('Worker timeout must be greater than zero and at most 600 seconds')
    data = json.dumps(request, allow_nan=False).encode('utf-8')
    if len(data) > 65536:
        raise ValueError('Worker request exceeds 64 KiB')
    if cancel_event is not None and cancel_event.is_set():
        return {'worker_status': 'CANCELLED', 'message': 'Cancelled before worker launch'}
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    started = time.monotonic()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([sys.executable, '-m', 'ezctd.worker'], stdin=subprocess.PIPE,
                                stdout=output, stderr=errors, start_new_session=os.name != 'nt',
                                creationflags=flags)
        pending = data
        try:
            while True:
                reason = None
                if cancel_event is not None and cancel_event.is_set():
                    reason = ('CANCELLED', 'Cancelled; unverified output is not published')
                elif time.monotonic() - started >= timeout:
                    reason = ('TIMEOUT', 'Native worker exceeded its time limit')
                elif os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > MAX_STDERR:
                    reason = ('OUTPUT_LIMIT', 'Worker output exceeded the configured limit')
                if reason:
                    _terminate(proc)
                    return {'worker_status': reason[0], 'message': reason[1]}
                try:
                    proc.communicate(pending, timeout=min(0.1, max(0.001, timeout - (time.monotonic() - started))))
                    # Cancellation can arrive while communicate is waiting for
                    # a fast successful worker. Do not publish that success as
                    # though the request had never been cancelled.
                    if cancel_event is not None and cancel_event.is_set():
                        return {'worker_status': 'CANCELLED',
                                'message': 'Cancelled; unverified output is not published'}
                    break
                except subprocess.TimeoutExpired:
                    pending = None
        except BaseException:
            _terminate(proc)
            raise
        if os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > MAX_STDERR:
            return {'worker_status': 'OUTPUT_LIMIT', 'message': 'Worker output exceeded the configured limit'}
        output.seek(0)
        try:
            payload = json.load(output)
        except (ValueError, UnicodeError):
            return {'worker_status': 'CRASH_OR_PROTOCOL_ERROR', 'exit_code': proc.returncode}
        if not isinstance(payload, dict) or payload.get('worker_status') not in ('OK', 'ERROR'):
            return {'worker_status': 'CRASH_OR_PROTOCOL_ERROR', 'exit_code': proc.returncode}
        if proc.returncode != 0 and payload['worker_status'] == 'OK':
            return {'worker_status': 'CRASH_OR_PROTOCOL_ERROR', 'exit_code': proc.returncode}
        # Decoding a bounded but large payload can outlast communicate itself.
        # A cancellation observed during JSON/protocol handling still wins over
        # returning a successful native result to the publisher.
        if cancel_event is not None and cancel_event.is_set():
            return {'worker_status': 'CANCELLED',
                    'message': 'Cancelled; unverified output is not published'}
        return payload
