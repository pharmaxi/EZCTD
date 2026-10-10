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
from .safe_io import PublishedOutputCleanupError, sha256_file, validate_new_output, write_new_text


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
    return _publish_staged_copy(source, output, roots=roots, expected=expected,
                                operation='linearize-stage', parameters={}, timeout=timeout,
                                cancel_event=cancel_event,
                                necessity='NOT_DECIDED_BY_GENERIC_LINEARIZATION')


def organize_copy(source: Path, output: Path, *, roots: tuple[Path, ...], expected: str,
                  order: list[int], rotations: list[int], timeout: float = 300,
                  cancel_event=None) -> dict[str, Any]:
    """Publish a verified page-order/rotation snapshot using the same transaction."""
    return _publish_staged_copy(source, output, roots=roots, expected=expected,
                                operation='organize-stage',
                                parameters={'order': list(order), 'rotations': list(rotations)},
                                timeout=timeout, cancel_event=cancel_event,
                                necessity='USER_REQUESTED_PAGE_ORGANIZATION')


def _publish_staged_copy(source: Path, output: Path, *, roots: tuple[Path, ...], expected: str,
                         operation: str, parameters: dict, timeout: float,
                         cancel_event, necessity: str) -> dict[str, Any]:
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
        result = run_worker({'operation': operation, 'path': str(path),
                             'expected_sha256': expected, 'stage_path': str(stage), **parameters},
                            timeout=timeout, cancel_event=cancel_event)
        if result['worker_status'] != 'OK':
            raise RuntimeError(result.get('message', result['worker_status']))
        proof = result['result']
        checked = selected_path(stage)
        if (proof.get('verification_status') != 'VERIFIED_LOCAL_INVARIANTS'
                or proof.get('source_sha256') != expected
                or sha256_file(checked) != proof.get('output_sha256')):
            raise RuntimeError('Worker verification envelope or staged hash invalid')
        if operation == 'organize-stage':
            mapping = proof.get('page_mapping')
            if (proof.get('operation') != 'organize-pages'
                    or proof.get('page_count') != len(parameters['order'])
                    or proof.get('order') != parameters['order']
                    or proof.get('rotations') != parameters['rotations']
                    or not isinstance(mapping, list) or len(mapping) != len(parameters['order'])
                    or any(not isinstance(row, dict)
                           or row.get('output_position') != index
                           or row.get('source_page') != source_page
                           or row.get('rotation_delta') != parameters['rotations'][source_page - 1]
                           for index, (source_page, row) in
                           enumerate(zip(parameters['order'], mapping, strict=True), 1))):
                raise RuntimeError('Worker page mapping does not match the requested edit snapshot')
        ReadScope(roots).authorize(path)
        if sha256_file(path) != expected:
            raise RuntimeError('Source changed before publication; result discarded')
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError('Cancelled before publication')
        validate_new_output(target, inputs=(path,), input_roots=roots)
        validate_new_output(proof_path, inputs=(path,), input_roots=roots)
        stage_stat = checked.stat()
        published = False
        proof_identity = None

        def remember_proof_publication(published_path, identity):
            nonlocal proof_identity
            if published_path != proof_path:
                raise RuntimeError('Proof publication receipt named an unexpected destination')
            proof_identity = identity

        try:
            # Same-filesystem hardlink is atomic and does not replace any target.
            os.link(checked, target)
            published = True
            proof.update({'source_relative_path': path.relative_to(roots[0]).as_posix(),
                          'output_filename': target.name,
                          'source_last_verified_sha256': expected,
                          'publication': 'PUBLISHED_COPY_WITH_PROOF',
                          'regulatory_necessity': necessity})
            write_new_text(proof_path, json.dumps(proof, ensure_ascii=False, indent=2) + '\n',
                           inputs=(path,), input_roots=roots,
                           on_published=remember_proof_publication)
            proof_stat = proof_path.lstat()
            if proof_identity is None or (proof_stat.st_dev, proof_stat.st_ino) != proof_identity:
                raise RuntimeError('Proof changed during publication; result discarded')
            ReadScope(roots).authorize(path)
            if sha256_file(path) != expected:
                raise RuntimeError('Source changed during publication; new copy and proof removed')
            # A late cancellation/close while the proof was being saved must
            # not leave a result that this transaction reports as discarded.
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Cancelled during publication; new copy and proof removed')
        except BaseException as exc:
            cleanup_failure = (exc if isinstance(exc, PublishedOutputCleanupError)
                               and exc.output_path == proof_path else None)
            if cleanup_failure is not None:
                # write_new_text may have atomically linked the proof before
                # its temporary-name cleanup failed. Use the writer's recorded
                # inode, never infer ownership from the proof path alone.
                proof_identity = cleanup_failure.published_identity
            if proof_identity is not None:
                try:
                    current = proof_path.lstat()
                    if (current.st_dev, current.st_ino) == proof_identity:
                        proof_path.unlink()
                except FileNotFoundError:
                    pass
            if published:
                try:
                    current = target.lstat()
                    if (current.st_dev, current.st_ino) == (stage_stat.st_dev, stage_stat.st_ino):
                        target.unlink()
                except FileNotFoundError:
                    pass
            if cleanup_failure is not None:
                try:
                    current = cleanup_failure.temporary_path.lstat()
                    if (current.st_dev, current.st_ino) == cleanup_failure.published_identity:
                        cleanup_failure.temporary_path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as retry_error:
                    # Preserve the first cleanup failure and explicitly retain
                    # failure of this bounded ownership-checked cleanup retry.
                    exc.args = (f'{exc}; temporary cleanup retry failed: '
                                f'{type(retry_error).__name__}: {retry_error}',)
            raise
    return proof
