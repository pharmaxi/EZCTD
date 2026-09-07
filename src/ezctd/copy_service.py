"""Parent-owned, no-clobber copy publication; original files are never written.

A saved PDF and its proof are a per-file transaction. If proof publication fails,
only the just-created, inode-verified destination is removed. Existing files are
never removed. This is a trusted-local-workspace boundary, not a hostile OS sandbox.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .process_runner import run_worker
from .read_scope import ReadScope, selected_path
from .safe_io import sha256_file, validate_new_output, write_new_text


def inspect_linearization(source: Path, *, roots: tuple[Path, ...], expected: str,
                          timeout: float = 60, cancel_event=None) -> dict:
    path = ReadScope(roots).authorize(source)
    result = run_worker({'operation': 'inspect-copy', 'path': str(path),
                         'expected_sha256': expected}, timeout=timeout, cancel_event=cancel_event)
    if result['worker_status'] != 'OK':
        raise RuntimeError(result.get('message', result['worker_status']))
    return result['result']


def linearize_copy(source: Path, output: Path, *, roots: tuple[Path, ...], expected: str,
                   timeout: float = 300, cancel_event=None) -> dict[str, Any]:
    path = ReadScope(roots).authorize(source)
    target = validate_new_output(output, inputs=(path,), input_roots=roots)
    if target.suffix.lower() != '.pdf':
        raise ValueError('PDF output requires .pdf extension')
    proof_path = target.with_name(target.name + '.ezctd.json')
    validate_new_output(proof_path, inputs=(path,), input_roots=roots)
    if sha256_file(path) != expected:
        raise ValueError('Source changed after plan; generate a new plan')
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_new_output(target, inputs=(path,), input_roots=roots)
    with tempfile.TemporaryDirectory(prefix='.ezctd-stage-', dir=target.parent) as td:
        stage = Path(td) / 'verified.pdf'
        result = run_worker({'operation': 'linearize-stage', 'path': str(path),
                             'expected_sha256': expected, 'stage_path': str(stage)},
                            timeout=timeout, cancel_event=cancel_event)
        if result['worker_status'] != 'OK':
            raise RuntimeError(result.get('message', result['worker_status']))
        proof = result['result']
        checked = selected_path(stage)
        if (proof.get('verification_status') != 'VERIFIED_LOCAL_INVARIANTS'
                or proof.get('source_sha256') != expected
                or sha256_file(checked) != proof.get('output_sha256')):
            raise RuntimeError('Worker verification envelope or staged hash invalid')
        ReadScope(roots).authorize(path)
        if sha256_file(path) != expected:
            raise RuntimeError('Source changed before publication; result discarded')
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError('Cancelled before publication')
        validate_new_output(target, inputs=(path,), input_roots=roots)
        validate_new_output(proof_path, inputs=(path,), input_roots=roots)
        stage_stat = checked.stat()
        published = False
        try:
            # Same-filesystem hardlink is atomic and does not replace any target.
            os.link(checked, target)
            published = True
            proof.update({'source_relative_path': path.relative_to(roots[0]).as_posix(),
                          'output_filename': target.name,
                          'source_last_verified_sha256': expected,
                          'publication': 'PUBLISHED_COPY_WITH_PROOF',
                          'regulatory_necessity': 'NOT_DECIDED_BY_GENERIC_LINEARIZATION'})
            write_new_text(proof_path, json.dumps(proof, ensure_ascii=False, indent=2) + '\n',
                           inputs=(path,), input_roots=roots)
        except BaseException:
            if published:
                try:
                    current = target.lstat()
                    if (current.st_dev, current.st_ino) == (stage_stat.st_dev, stage_stat.st_ino):
                        target.unlink()
                except FileNotFoundError:
                    pass
            raise
    return proof
