"""Bounded disposable processes; not a security sandbox.

Native crashes and wall-clock timeouts do not terminate the batch parent.
No shell interpolation and no arbitrary worker module selection are exposed.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile

MAX_OUTPUT = 48 * 1024 * 1024


def run_worker(request: dict, *, timeout: float = 60) -> dict:
    if not 0 < timeout <= 600:
        raise ValueError('Worker timeout must be greater than zero and at most 600 seconds')
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([sys.executable, '-m', 'ezctd.worker'], stdin=subprocess.PIPE,
                                stdout=output, stderr=errors, start_new_session=os.name != 'nt',
                                creationflags=flags)
        try:
            proc.communicate(json.dumps(request).encode('utf-8'), timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               capture_output=True, timeout=10, check=False)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.kill()
            proc.wait(timeout=10)
            return {'worker_status': 'TIMEOUT', 'message': 'Native worker exceeded its time limit'}
        except BaseException:
            if os.name != 'nt':
                os.killpg(proc.pid, signal.SIGKILL)
            proc.kill()
            proc.wait(timeout=10)
            raise
        if output.tell() > MAX_OUTPUT:
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
        return payload
