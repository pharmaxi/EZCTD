"""Workflow regressions with synthetic PDFs and explicit failure injection.

Native PDF assertions use the real engines. Events and injected exceptions only
make cancellation scheduling and failed I/O deterministic; they are not evidence
of an OS sandbox or a real clinical/official-validator run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

import pytest

from ezctd.cli import _default_rulepack
from ezctd.process_runner import run_worker
from ezctd.read_cache import ReadCache
from ezctd.safe_io import sha256_file
from ezctd.workspace import Workspace


def wait(workspace, ident):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        result = workspace.job(ident)
        if result['status'] not in ('QUEUED', 'RUNNING', 'FINALIZING'):
            return result
        time.sleep(.01)
    raise AssertionError('Synthetic job did not finish within 30 seconds')


@pytest.fixture
def workflow(tmp_path, pdf_factory):
    source = tmp_path / 'input'
    for name in ('a.pdf', 'b.pdf', 'c.pdf'):
        pdf_factory(source / name, pages=2, bookmark=True)
    workspace = Workspace(source, tmp_path / 'workspace', _default_rulepack())
    yield workspace
    workspace.close()


def test_mixed_native_plan_applies_only_verified_eligible_file(tmp_path, pdf_factory):
    source = tmp_path / 'input'
    pdf_factory(source / 'a-good.pdf', pages=2, bookmark=True)
    (source / 'b-corrupt.pdf').write_bytes(b'%PDF-1.7\nsynthetic corrupt input\n')
    workspace = Workspace(source, tmp_path / 'workspace', _default_rulepack())
    try:
        before = {doc.id: sha256_file(doc.path) for doc in workspace.docs.values()}
        plan = wait(workspace, workspace.start('plan', ['1', '2']))
        assert plan['status'] == 'COMPLETED_WITH_ERRORS'
        assert plan['counts'] == {'succeeded': 1, 'errors': 1, 'cancelled': 0,
                                  'pending': 0, 'blocked': 0, 'skipped': 0}
        assert plan['can_apply'] and plan['eligible_count'] == 1
        assert plan['can_retry'] and plan['retryable_count'] == 1
        assert (workspace.output / 'jobs' / (plan['id'] + '.json')).is_file()
        with pytest.raises(ValueError, match='explicit confirmation'):
            workspace.start('apply', plan_id=plan['id'], confirmed=False)
        assert workspace.job(plan['id'])['can_apply']
        applied = wait(workspace, workspace.start('apply', plan_id=plan['id'], confirmed=True))
        assert applied['status'] == 'COMPLETED'
        assert applied['requested_ids'] == ['1']
        assert applied['results'][0]['status'] == 'VERIFIED_COPY'
        proof = applied['results'][0]['proof']
        assert len(proof['pages']) == 2 and all(page['pixels_equal'] for page in proof['pages'])
        assert {doc.id: sha256_file(doc.path) for doc in workspace.docs.values()} == before
        assert not workspace.job(plan['id'])['can_apply']
    finally:
        workspace.close()


def test_plan_source_change_at_completion_excludes_preflight_entry(workflow, monkeypatch):
    import ezctd.workspace as module
    original = module.inspect_linearization

    def mutate_after_inspection(source, **kwargs):
        result = original(source, **kwargs)
        source.write_bytes(source.read_bytes() + b'\n% synthetic new source revision\n')
        return result

    monkeypatch.setattr(module, 'inspect_linearization', mutate_after_inspection)
    plan = wait(workflow, workflow.start('plan', ['1']))
    assert plan['status'] == 'COMPLETED_WITH_ERRORS'
    assert not plan['can_apply'] and plan['eligible_count'] == 0
    assert plan['results'][0]['preflight_eligibility'] == 'ELIGIBLE'
    assert plan['results'][0]['eligibility'] == 'BLOCKED'
    assert plan['results'][0]['status'] == 'ERROR'
    assert plan['input_integrity'][0]['unchanged'] is False
    assert plan['id'] not in workflow.plans


def test_failed_job_record_publication_never_exposes_actionable_plan(workflow, monkeypatch):
    import ezctd.workspace as module

    def disk_failure(*args, **kwargs):
        raise OSError('synthetic job evidence write failure')

    monkeypatch.setattr(module, 'write_new_text', disk_failure)
    plan = wait(workflow, workflow.start('plan', ['1']))
    assert plan['status'] == 'ERROR'
    assert 'synthetic job evidence write failure' in plan['message']
    assert not plan['can_apply'] and plan['id'] not in workflow.plans
    assert not (workflow.output / 'jobs' / (plan['id'] + '.json')).exists()
    with pytest.raises(ValueError, match='unused completed plan'):
        workflow.start('apply', plan_id=plan['id'], confirmed=True)


def test_retry_partial_copy_creates_fresh_plan_and_preserves_success(workflow, monkeypatch):
    import ezctd.workspace as module
    original = module.linearize_copy
    failed_once = False

    def fail_second_file_once(source, *args, **kwargs):
        nonlocal failed_once
        if source.name == 'b.pdf' and not failed_once:
            failed_once = True
            raise OSError('synthetic transient copy failure before publication')
        return original(source, *args, **kwargs)

    monkeypatch.setattr(module, 'linearize_copy', fail_second_file_once)
    before = {doc.id: sha256_file(doc.path) for doc in workflow.docs.values()}
    plan = wait(workflow, workflow.start('plan', ['1', '2']))
    first = wait(workflow, workflow.start('apply', plan_id=plan['id'], confirmed=True))
    assert first['status'] == 'COMPLETED_WITH_ERRORS'
    assert [row['status'] for row in first['results']] == ['VERIFIED_COPY', 'ERROR']
    kept = workflow.output / first['results'][0]['output_relative']
    kept_sha = sha256_file(kept)
    retry = wait(workflow, workflow.retry(first['id']))
    assert retry['kind'] == 'plan' and retry['retry_of'] == first['id']
    assert retry['requested_ids'] == ['2'] and retry['can_apply']
    assert len(list((workflow.output / 'copies').rglob('*.pdf'))) == 1
    with pytest.raises(ValueError, match='unused completed plan'):
        workflow.start('apply', plan_id=plan['id'], confirmed=True)
    second = wait(workflow, workflow.start('apply', plan_id=retry['id'], confirmed=True))
    assert second['status'] == 'COMPLETED' and second['requested_ids'] == ['2']
    assert sha256_file(kept) == kept_sha
    assert len(list((workflow.output / 'copies').rglob('*.pdf'))) == 2
    assert {doc.id: sha256_file(doc.path) for doc in workflow.docs.values()} == before
    with pytest.raises(ValueError, match='no failed'):
        workflow.retry(second['id'])


def test_cancelled_scan_keeps_success_and_retries_cancelled_and_pending_only(workflow, monkeypatch):
    original = workflow._native
    second_started = threading.Event()
    calls = 0

    def scheduled(request, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            second_started.set()
            assert kwargs['cancel_event'].wait(10), 'test never requested cancellation'
            raise RuntimeError('synthetic wait cancelled')
        return original(request, **kwargs)

    monkeypatch.setattr(workflow, '_native', scheduled)
    ident = workflow.start('scan', ['1', '2', '3'])
    assert second_started.wait(10)
    history = workflow.job_history()
    assert history['active_job_id'] == ident
    assert history['jobs'][0]['counts']['succeeded'] == 1
    assert history['jobs'][0]['counts']['pending'] == 2
    assert 'results' not in history['jobs'][0]
    with pytest.raises(ValueError, match='finish'):
        workflow.retry(ident)
    workflow.cancel(ident)
    cancelled = wait(workflow, ident)
    assert cancelled['status'] == 'CANCELLED'
    assert [row['status'] for row in cancelled['results']] == ['SCANNED', 'CANCELLED', 'NOT_STARTED']
    assert cancelled['counts'] == {'succeeded': 1, 'errors': 0, 'cancelled': 1,
                                   'pending': 1, 'blocked': 0, 'skipped': 0}
    assert cancelled['done'] == 2 and cancelled['remaining'] == 1
    assert cancelled['retryable_count'] == 2
    saved = json.loads((workflow.output / 'jobs' / (ident + '.json')).read_text(encoding='utf-8'))
    assert saved['requested_ids'] == ['1', '2', '3']
    assert saved['results'][2]['status'] == 'NOT_STARTED'
    monkeypatch.setattr(workflow, '_native', original)
    retry = wait(workflow, workflow.retry(ident))
    assert retry['kind'] == 'scan' and retry['retry_of'] == ident
    assert retry['requested_ids'] == ['2', '3'] and retry['status'] == 'COMPLETED'
    history = workflow.session()
    assert history['active_job_id'] is None
    assert [job['id'] for job in history['jobs']] == [retry['id'], ident]
    assert history['history_scope'] == 'CURRENT_SERVER_SESSION'
    assert sum(history['files'][0]['scan_summary'].values()) == 26
    history['jobs'][0]['counts']['succeeded'] = 999
    assert workflow.job(retry['id'])['counts']['succeeded'] == 2


def test_cancelled_plan_is_not_directly_actionable(workflow, monkeypatch):
    import ezctd.workspace as module
    original = module.inspect_linearization
    gate = threading.Event()
    calls = 0

    def scheduled(source, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            gate.set()
            assert kwargs['cancel_event'].wait(10)
            raise RuntimeError('synthetic preflight cancellation')
        return original(source, **kwargs)

    monkeypatch.setattr(module, 'inspect_linearization', scheduled)
    ident = workflow.start('plan', ['1', '2', '3'])
    assert gate.wait(10)
    workflow.cancel(ident)
    result = wait(workflow, ident)
    assert result['status'] == 'CANCELLED' and not result['can_apply']
    assert result['results'][0]['eligibility'] == 'ELIGIBLE'
    assert result['retryable_count'] == 2
    assert ident not in workflow.plans


def test_reader_cache_uses_native_result_and_separates_all_request_parameters(workflow, monkeypatch):
    original = workflow._native
    requests = []

    def counted(request, **kwargs):
        requests.append(dict(request))
        return original(request, **kwargs)

    monkeypatch.setattr(workflow, '_native', counted)
    first = workflow.document_action('1', 'navigation')
    original_title = first['bookmarks'][0]['title']
    first['bookmarks'][0]['title'] = 'caller mutation must not enter cache'
    second = workflow.document_action('1', 'navigation')
    assert second['bookmarks'][0]['title'] == original_title
    assert len(requests) == 1
    page = workflow.document_action('1', 'view-page', page=1, dpi=72, query=None)
    assert workflow.document_action('1', 'view-page', query=None, dpi=72, page=1) == page
    assert len(requests) == 2
    query = workflow.document_action('1', 'view-page', page=1, dpi=72, query='12.50')
    assert query['search_matches'] and len(requests) == 3
    workflow.document_action('1', 'view-page', page=1, dpi=120, query=None)
    workflow.document_action('1', 'view-page', page=2, dpi=72, query=None)
    workflow.document_action('2', 'navigation')
    assert len(requests) == 6
    assert all(request['expected_sha256'] for request in requests)
    assert workflow.read_cache.stats()['entries'] == 6
    workflow.close()
    assert workflow.read_cache.stats()['bytes'] == 0
    with pytest.raises(ValueError, match='closed'):
        workflow.document_action('1', 'navigation')


def test_cached_reader_rehashes_even_when_size_and_mtime_are_unchanged(workflow):
    source = workflow.docs['1'].path
    source.write_bytes(source.read_bytes() + b'\n% cache-version-A\n')
    plan = wait(workflow, workflow.start('plan', ['1']))
    assert plan['can_apply']
    workflow.document_action('1', 'navigation')
    before = source.stat()
    source.write_bytes(source.read_bytes().replace(b'cache-version-A', b'cache-version-B'))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        workflow.document_action('1', 'navigation')
    assert workflow.read_cache.stats()['entries'] == 0
    assert not workflow.job(plan['id'])['can_apply']
    assert workflow.job(plan['id'])['invalidated_plan_ids'] == ['1']
    with pytest.raises(ValueError, match='No eligible'):
        workflow.start('apply', plan_id=plan['id'], confirmed=True)
    assert workflow.plans[plan['id']]['used'] is False


def test_reader_failures_are_never_cached(tmp_path, monkeypatch):
    source = tmp_path / 'input'
    source.mkdir()
    (source / 'corrupt.pdf').write_bytes(b'%PDF-1.7\nsynthetic malformed input\n')
    workspace = Workspace(source, tmp_path / 'workspace', _default_rulepack())
    original = workspace._native
    calls = []

    def counted(request, **kwargs):
        calls.append(request)
        return original(request, **kwargs)

    monkeypatch.setattr(workspace, '_native', counted)
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError):
                workspace.document_action('1', 'navigation')
        assert len(calls) == 2 and workspace.read_cache.stats()['entries'] == 0
    finally:
        workspace.close()


def test_read_cache_bounds_bytes_entries_and_retains_recent_reads():
    cache = ReadCache(max_bytes=1024, max_entries=2)
    one, two, three = [('doc', str(number), 'page', '{}') for number in range(3)]
    value = {'text': 'x' * 200}
    assert cache.put(one, value) and cache.put(two, value)
    assert cache.get(one) == value  # retain this read rather than the older one
    assert cache.put(three, value)
    assert cache.get(two) is None and cache.get(one) == value
    assert cache.stats()['entries'] == 2 and cache.stats()['bytes'] <= 1024
    assert not cache.put(('other', 'large', 'page', '{}'), {'png_base64': 'x' * 2048})
    assert cache.stats()['entries'] == 2
    byte_limited = ReadCache(max_bytes=300, max_entries=32)
    assert byte_limited.put(one, value) and byte_limited.put(two, value)
    assert byte_limited.get(one) is None
    assert byte_limited.stats()['entries'] == 1 and byte_limited.stats()['bytes'] <= 300
    cache.invalidate_document('doc')
    assert cache.stats()['entries'] == 0 and cache.stats()['bytes'] == 0


def test_cancellation_during_successful_worker_communication_wins(monkeypatch):
    import ezctd.process_runner as module
    cancelled = threading.Event()

    class CompletedWorker:
        returncode = 0

        def __init__(self, *args, **kwargs):
            self.output = kwargs['stdout']

        def communicate(self, data, timeout):
            self.output.write(b'{"worker_status":"OK","result":{"synthetic":true}}')
            self.output.flush()
            cancelled.set()
            return None, None

    monkeypatch.setattr(module.subprocess, 'Popen', CompletedWorker)
    result = run_worker({'operation': 'synthetic'}, cancel_event=cancelled)
    assert result['worker_status'] == 'CANCELLED'
    assert 'result' not in result


@pytest.mark.parametrize('interruption', ['source_changed', 'closed'])
def test_cache_hit_rechecks_identity_and_closure_after_decoding(workflow, monkeypatch, interruption):
    plan = wait(workflow, workflow.start('plan', ['1']))
    workflow.document_action('1', 'navigation')  # cache a real native result
    original_get = workflow.read_cache.get

    def interrupted_get(key):
        cached = original_get(key)
        assert cached is not None
        if interruption == 'source_changed':
            source = workflow.docs['1'].path
            source.write_bytes(source.read_bytes() + b'\n% changed during cache lookup\n')
        else:
            workflow.close()
        return cached

    monkeypatch.setattr(workflow.read_cache, 'get', interrupted_get)
    with pytest.raises(ValueError, match='SOURCE_CHANGED' if interruption == 'source_changed' else 'closed'):
        workflow.document_action('1', 'navigation')
    assert workflow.read_cache.stats()['entries'] == 0
    assert not workflow.job(plan['id'])['can_apply']


def test_mismatched_native_result_still_invalidates_changed_source(workflow, monkeypatch):
    plan = wait(workflow, workflow.start('plan', ['1']))
    workflow.document_action('1', 'navigation')
    original_native = workflow._native

    def changed_before_native(request, **kwargs):
        source = workflow.docs['1'].path
        source.write_bytes(source.read_bytes() + b'\n% changed before native read\n')
        result = original_native(request, **kwargs)
        assert result['input_sha256'] == sha256_file(source)
        return result

    monkeypatch.setattr(workflow, '_native', changed_before_native)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        workflow.document_action('1', 'view-page', page=1, dpi=72)
    assert workflow.read_cache.stats()['entries'] == 0
    assert not workflow.job(plan['id'])['can_apply']
    assert workflow.job(plan['id'])['invalidated_plan_ids'] == ['1']


def test_cancellation_during_real_worker_json_decode_wins(workflow, monkeypatch):
    import ezctd.process_runner as module
    cancelled = threading.Event()
    original_load = module.json.load
    decoded = []

    def cancel_after_decode(*args, **kwargs):
        payload = original_load(*args, **kwargs)
        decoded.append(payload)
        cancelled.set()
        return payload

    monkeypatch.setattr(module.json, 'load', cancel_after_decode)
    source = workflow.docs['1'].path
    result = run_worker({'operation': 'navigation', 'path': str(source),
                         'expected_sha256': sha256_file(source)}, cancel_event=cancelled)
    assert decoded[0]['worker_status'] == 'OK' and decoded[0]['result']['bookmarks']
    assert result['worker_status'] == 'CANCELLED'
    assert 'result' not in result


@pytest.mark.parametrize('requested_ids', [['1'], ['1', '2']])
def test_plan_publication_cannot_restore_source_invalidated_during_record_save(
        workflow, monkeypatch, requested_ids):
    import ezctd.workspace as module
    original_write = module.write_new_text
    saved_bytes = []
    observed = []

    def changed_while_saving(path, text, **kwargs):
        result = original_write(path, text, **kwargs)
        saved_bytes.append(path.read_bytes())
        source = workflow.docs['1'].path
        source.write_bytes(source.read_bytes() + b'\n% changed during job record save\n')
        # This is a separate request observing invalidation while the plan job
        # is finalizing; the final registration must not reintroduce the file.
        try:
            workflow.details('1')
        except ValueError as exc:
            observed.append(str(exc))
        return result

    monkeypatch.setattr(module, 'write_new_text', changed_while_saving)
    ident = workflow.start('plan', requested_ids)
    job = wait(workflow, ident)
    assert observed and 'SOURCE_CHANGED' in observed[0]
    assert job['invalidated_plan_ids'] == ['1']
    remaining = [item for item in requested_ids if item != '1']
    assert job['eligible_count'] == len(remaining)
    assert job['can_apply'] == bool(remaining)
    assert job['plan_eligible_ids'] == remaining
    if remaining:
        assert [entry['id'] for entry in workflow.plans[ident]['entries']] == remaining
    else:
        assert ident not in workflow.plans
    # No-clobber job evidence remains the original preflight snapshot; current
    # eligibility is tracked separately and never inferred from that old file.
    record = workflow.output / 'jobs' / (ident + '.json')
    assert record.read_bytes() == saved_bytes[0]
    assert json.loads(saved_bytes[0])['plan_eligible_ids'] == requested_ids
