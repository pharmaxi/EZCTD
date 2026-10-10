"""Real native page edits with deterministic scheduling and I/O failure controls.

These use synthetic PDFs. Thread events force the documented races; they do not
replace the native transform, rendering, hash checks, or filesystem publication.
"""
from __future__ import annotations

import json
from pathlib import Path
import threading

import pikepdf
import pytest

from ezctd.cli import _default_rulepack
from ezctd.editor import EditorConflict, EditorStore
from ezctd.safe_io import sha256_file
from ezctd.workspace import Workspace
from test_workbench import wait


@pytest.fixture
def editor_workspace(tmp_path):
    source = tmp_path / 'input' / 'clinical.pdf'
    source.parent.mkdir()
    with pikepdf.Pdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                                 Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for index, label in enumerate(('Alpha', 'Beta', 'Gamma')):
            page = pdf.add_blank_page(page_size=(300, 400))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            page.obj.Contents = pdf.make_stream(f'BT /F1 16 Tf 30 320 Td ({label} page) Tj ET'.encode())
            if index == 1:
                page.obj.Rotate = 90
        with pdf.open_outline() as outline:
            outline.root.extend([pikepdf.OutlineItem('Alpha section', 0),
                                 pikepdf.OutlineItem('Gamma section', 2)])
        pdf.save(source)
    workspace = Workspace(source.parent, tmp_path / 'output', _default_rulepack())
    yield workspace
    workspace.close()


def reorder(workspace):
    draft = workspace.editor_open('1')
    return workspace.editor_edit(draft['draft_id'], draft['revision'],
                                 {'type': 'reorder', 'order': [3, 1, 2]})


def test_page_editor_saves_real_reorder_rotation_and_reopens_navigation(editor_workspace):
    w = editor_workspace
    source = w.docs['1'].path
    before = sha256_file(source)
    draft = reorder(w)
    assert w.editor_open('1')['draft_id'] == draft['draft_id']
    draft = w.editor_edit(draft['draft_id'], draft['revision'],
                          {'type': 'rotate', 'pages': [1], 'degrees': 90})
    assert draft['order'] == [3, 1, 2] and draft['rotations'] == [90, 0, 0]
    preview = w.editor_page(draft['draft_id'], draft['revision'], page=2, dpi=72)
    assert preview['source_page'] == 1 and preview['output_position'] == 2
    assert (preview['width_px'], preview['height_px']) == (400, 300)
    assert preview['preview_only'] and preview['png_base64']
    assert preview['source_sha256'] == before
    nav = w.editor_navigation(draft['draft_id'], draft['revision'])
    assert [row['physical_page'] for row in nav['bookmarks']] == [2, 1]
    job_id = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    job = wait(w, job_id)
    assert job['status'] == 'COMPLETED', job
    assert job['kind'] == 'organize' and job['counts']['succeeded'] == 1
    assert not job['can_retry'] and job['retryable_count'] == 0
    row = job['results'][0]
    assert row['status'] == 'VERIFIED_COPY' and row['saved_revision'] == draft['revision']
    output = w.output / row['output_relative']
    proof = json.loads(output.with_name(output.name + '.ezctd.json').read_text(encoding='utf-8'))
    assert proof['order'] == [3, 1, 2] and proof['rotations'] == [90, 0, 0]
    assert [item['source_page'] for item in proof['page_mapping']] == [3, 1, 2]
    with pikepdf.open(output) as pdf:
        texts = [page.obj.Contents.read_bytes() for page in pdf.pages]
        assert all(word in text for word, text in zip((b'Gamma', b'Alpha', b'Beta'), texts, strict=True))
        assert [int(page.obj.get('/Rotate', 0)) for page in pdf.pages] == [0, 90, 90]
    actual = w.editor_output(job_id, 'navigation')
    assert [item['physical_page'] for item in actual['bookmarks']] == [2, 1]
    assert actual['page_mapping'] == proof['page_mapping']
    opened = w.editor_output(job_id, 'page', page=2, dpi=72)
    assert 'Alpha page' in opened['text'] and opened['read_only']
    assert opened['output_sha256'] == sha256_file(output)
    saved = w.editor_state(draft['draft_id'])
    assert not saved['dirty'] and saved['has_changes'] and saved['can_undo']
    assert saved['save_revision'] == saved['last_saved_revision'] == draft['revision']
    undone = w.editor_history(draft['draft_id'], saved['revision'])
    assert undone['order'] == [3, 1, 2] and undone['rotations'] == [0, 0, 0]
    assert undone['dirty'] and undone['can_redo']
    redone = w.editor_history(draft['draft_id'], undone['revision'], redo=True)
    assert not redone['dirty'] and redone['rotations'] == [90, 0, 0]
    assert sha256_file(source) == before and job['input_integrity'][0]['unchanged']


@pytest.mark.parametrize('command', [
    {'type': 'reorder', 'order': [1, 1, 3]},
    {'type': 'reorder', 'order': [1, 2]},
    {'type': 'reorder', 'order': [True, 2, 3]},
    {'type': 'rotate', 'pages': [1, 1], 'degrees': 90},
    {'type': 'rotate', 'pages': [4], 'degrees': 90},
    {'type': 'rotate', 'pages': [1], 'degrees': 90.0},
    {'type': 'rotate', 'pages': [1], 'degrees': 180},
    {'type': 'reset', 'path': '/etc/passwd'},
])
def test_editor_rejects_ambiguous_commands_without_altering_history(editor_workspace, command):
    w = editor_workspace
    draft = w.editor_open('1')
    with pytest.raises(ValueError):
        w.editor_edit(draft['draft_id'], draft['revision'], command)
    assert w.editor_state(draft['draft_id']) == draft


def test_history_branching_revision_and_bounds(editor_workspace):
    w = editor_workspace
    draft = reorder(w)
    with pytest.raises(EditorConflict, match='changed'):
        w.editor_edit(draft['draft_id'], 0, {'type': 'reset'})
    with pytest.raises(ValueError, match='nonnegative integer'):
        w.editor_history(draft['draft_id'], None)
    restored = w.editor_history(draft['draft_id'], draft['revision'])
    assert not restored['dirty'] and restored['can_redo']
    branch = w.editor_edit(draft['draft_id'], restored['revision'],
                           {'type': 'rotate', 'pages': [2], 'degrees': -90})
    assert not branch['can_redo'] and branch['rotations'] == [0, 270, 0]
    # Pure state history bound; no fake native operation is asserted by this loop.
    for _ in range(55):
        branch = w.editors.edit(branch['draft_id'], branch['revision'],
                                 {'type': 'rotate', 'pages': [1], 'degrees': 90})
    assert len(w.editors.get(branch['draft_id']).undo) == 50


def test_source_invalidation_is_permanent_even_if_bytes_are_restored(editor_workspace):
    w = editor_workspace
    draft = reorder(w)
    source = w.docs['1'].path
    original = source.read_bytes()
    source.write_bytes(original + b'\n% deterministic changed source\n')
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_state(draft['draft_id'])
    source.write_bytes(original)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_open('1')
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    assert not w.jobs and not list(w.output.rglob('*.pdf'))


def test_late_native_preview_cannot_return_for_a_new_revision(editor_workspace, monkeypatch):
    w = editor_workspace
    draft = reorder(w)
    native = w._native
    reached, release = threading.Event(), threading.Event()
    outcomes = []

    def pause_after_render(request, **kwargs):
        result = native(request, **kwargs)
        reached.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(w, '_native', pause_after_render)

    def read():
        try:
            outcomes.append(w.editor_page(draft['draft_id'], draft['revision'], page=1))
        except Exception as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=read)
    thread.start()
    try:
        assert reached.wait(10)
        w.editor_edit(draft['draft_id'], draft['revision'], {'type': 'reset'})
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and len(outcomes) == 1
    assert isinstance(outcomes[0], EditorConflict) and outcomes[0].code == 'STALE_DRAFT'


def test_cached_edit_preview_rechecks_source_after_cache_decode(editor_workspace, monkeypatch):
    w = editor_workspace
    draft = reorder(w)
    w.editor_page(draft['draft_id'], draft['revision'], page=1)
    cached_get = w.read_cache.get
    source = w.docs['1'].path

    def change_during_decode(key):
        result = cached_get(key)
        assert result is not None
        source.write_bytes(source.read_bytes() + b'\n% change during cached preview\n')
        return result

    monkeypatch.setattr(w.read_cache, 'get', change_during_decode)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_page(draft['draft_id'], draft['revision'], page=1)
    assert w.editors.get(draft['draft_id']).invalidated


def test_save_replay_is_idempotent_and_edit_is_locked_until_completion(editor_workspace, monkeypatch):
    import ezctd.workspace as module
    w = editor_workspace
    draft = reorder(w)
    original = module.organize_copy
    reached, release = threading.Event(), threading.Event()

    def scheduled(*args, **kwargs):
        reached.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, 'organize_copy', scheduled)
    job_id = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    try:
        assert reached.wait(10)
        assert w.editor_save(draft['draft_id'], draft['revision'], confirmed=True) == job_id
        assert w.editor_save(draft['draft_id'], draft['revision'], confirmed=True, retry=True) == job_id
        current = w.editor_state(draft['draft_id'])
        assert current['saving'] and current['save_job_id'] == job_id
        assert current['save_revision'] == draft['revision']
        with pytest.raises(EditorConflict, match='save'):
            w.editor_edit(draft['draft_id'], draft['revision'], {'type': 'reset'})
        with pytest.raises(ValueError, match='active'):
            w.start('scan', ['1'])
    finally:
        release.set()
    assert wait(w, job_id)['status'] == 'COMPLETED'
    assert len(w.jobs) == 1 and len(list(w.output.rglob('*.pdf'))) == 1
    assert w.editor_save(draft['draft_id'], draft['revision'], confirmed=True) == job_id


def test_cancelled_save_requires_explicit_retry_and_a_new_output_identity(editor_workspace, monkeypatch):
    import ezctd.workspace as module
    w = editor_workspace
    draft = reorder(w)
    original = module.organize_copy
    reached = threading.Event()

    def scheduled(*args, **kwargs):
        reached.set()
        assert kwargs['cancel_event'].wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, 'organize_copy', scheduled)
    first = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    assert reached.wait(10)
    w.cancel(first)
    cancelled = wait(w, first)
    assert cancelled['status'] == 'CANCELLED' and not cancelled['can_retry']
    assert not list(w.output.rglob('*.pdf'))
    assert w.editor_save(draft['draft_id'], draft['revision'], confirmed=True) == first
    with pytest.raises(ValueError, match='explicit confirmation'):
        w.retry(first)
    monkeypatch.setattr(module, 'organize_copy', original)
    second = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True, retry=True)
    assert second != first
    completed = wait(w, second)
    assert completed['status'] == 'COMPLETED' and completed['retry_of'] == first
    assert completed['output_relative_root'] != cancelled['output_relative_root']
    assert len(list(w.output.rglob('*.pdf'))) == 1


@pytest.mark.parametrize('failure', ['proof_write', 'cancel_after_proof', 'source_after_proof'])
def test_publication_failure_rolls_back_new_pdf_and_proof(editor_workspace, monkeypatch, failure):
    import ezctd.copy_service as service
    w = editor_workspace
    draft = reorder(w)
    original = service.write_new_text
    before = sha256_file(w.docs['1'].path)

    def injected(path, *args, **kwargs):
        if failure == 'proof_write':
            raise OSError('synthetic proof publication failure')
        result = original(path, *args, **kwargs)
        if failure == 'cancel_after_proof':
            next(event for ident, event in w.events.items() if w.jobs[ident]['kind'] == 'organize').set()
        else:
            source = w.docs['1'].path
            source.write_bytes(source.read_bytes() + b'\n% synthetic external source update\n')
        return result

    monkeypatch.setattr(service, 'write_new_text', injected)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    assert job['status'] in ('COMPLETED_WITH_ERRORS', 'CANCELLED')
    assert job['results'][0]['status'] in ('ERROR', 'CANCELLED')
    assert not list(w.output.rglob('*.pdf')) and not list(w.output.rglob('*.ezctd.json'))
    assert not w.editor_outputs
    if failure != 'source_after_proof':
        assert sha256_file(w.docs['1'].path) == before


def test_saved_output_has_own_identity_and_rejects_unknown_or_modified_files(editor_workspace):
    w = editor_workspace
    draft = reorder(w)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    job_id = job['id']
    source = w.docs['1'].path
    source.write_bytes(source.read_bytes() + b'\n% later source edit\n')
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_state(draft['draft_id'])
    assert w.editor_output(job_id, 'page', page=1)['read_only']
    for unknown in ('/etc/passwd', '../jobs/' + job_id, 'other-session-job'):
        with pytest.raises(ValueError, match='Unknown session editor output'):
            w.editor_output(unknown, 'page')
    output = w.output / job['results'][0]['output_relative']
    original = output.read_bytes()
    output.write_bytes(original + b'\n% synthetic changed output\n')
    with pytest.raises(ValueError, match='OUTPUT_CHANGED'):
        w.editor_output(job_id, 'page')
    output.write_bytes(original)
    with pytest.raises(ValueError, match='OUTPUT_CHANGED'):
        w.editor_output(job_id, 'navigation')


def test_open_does_not_create_draft_after_source_invalidation_between_freeze_and_lock(editor_workspace, monkeypatch):
    w = editor_workspace
    original = w._freeze
    calls = 0

    def invalidated_after_final_freeze(doc):
        nonlocal calls
        result = original(doc)
        calls += 1
        if calls == 2:
            with w.lock:
                w._invalidate_document_locked(doc)
        return result

    monkeypatch.setattr(w, '_freeze', invalidated_after_final_freeze)
    with pytest.raises(ValueError, match='SOURCE_CHANGED'):
        w.editor_open('1')
    assert not w.editors.drafts


def test_observed_source_invalidation_cancels_save_even_after_bytes_restore(editor_workspace, monkeypatch):
    import ezctd.workspace as module
    w = editor_workspace
    draft = reorder(w)
    original = module.organize_copy
    reached, release = threading.Event(), threading.Event()

    def scheduled(*args, **kwargs):
        reached.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, 'organize_copy', scheduled)
    job_id = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    try:
        assert reached.wait(10)
        source = w.docs['1'].path
        initial = source.read_bytes()
        source.write_bytes(initial + b'\n% changed during save\n')
        with pytest.raises(ValueError, match='SOURCE_CHANGED'):
            w.details('1')
        source.write_bytes(initial)
        assert w.events[job_id].is_set()
    finally:
        release.set()
    job = wait(w, job_id)
    assert job['status'] == 'CANCELLED' and job['cancellation_reason'] == 'SOURCE_CHANGED'
    assert not list(w.output.rglob('*.pdf'))


def test_close_cancels_save_and_waits_for_cleanup(editor_workspace, monkeypatch):
    import ezctd.workspace as module
    w = editor_workspace
    draft = reorder(w)
    original = module.organize_copy
    reached = threading.Event()

    def scheduled(*args, **kwargs):
        reached.set()
        assert kwargs['cancel_event'].wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, 'organize_copy', scheduled)
    job_id = w.editor_save(draft['draft_id'], draft['revision'], confirmed=True)
    assert reached.wait(10)
    w.close()
    assert not w.editor_threads[job_id].is_alive()
    assert w.job(job_id)['status'] == 'CANCELLED'
    assert not list(w.output.rglob('*.pdf')) and not list(w.output.rglob('.ezctd-stage-*'))


@pytest.mark.parametrize('interruption', ['close', 'invalidation'])
def test_preview_final_boundary_cannot_restore_cache_after_interruption(editor_workspace, monkeypatch, interruption):
    w = editor_workspace
    draft = reorder(w)
    original = w._freeze
    calls = 0

    def interrupted_after_freeze(doc):
        nonlocal calls
        result = original(doc)
        calls += 1
        if calls == 2:
            if interruption == 'close':
                w.close()
            else:
                with w.lock:
                    w._invalidate_document_locked(doc)
        return result

    monkeypatch.setattr(w, '_freeze', interrupted_after_freeze)
    with pytest.raises(ValueError, match='closed|SOURCE_CHANGED'):
        w.editor_page(draft['draft_id'], draft['revision'], page=1)
    assert w.read_cache.stats()['entries'] == 0


def test_draft_capacity_rejects_overflow_without_evicting_edits(editor_workspace):
    w = editor_workspace
    doc = w.docs['1']
    inspected = w._native({'operation': 'inspect-organize', 'path': str(doc.path),
                           'expected_sha256': sha256_file(doc.path)})
    # The store limit is a native-free state policy, tested with real inspected metadata.
    store = EditorStore()
    drafts = [store.open(str(index), inspected) for index in range(16)]
    changed = store.edit(drafts[0].id, 0, {'type': 'rotate', 'pages': [1], 'degrees': 90})
    with pytest.raises(ValueError, match='limit reached'):
        store.open('17', inspected)
    assert len(store.drafts) == 16 and store.open('0', inspected).state() == changed


@pytest.mark.parametrize('action', ['page', 'navigation'])
def test_late_output_read_stays_invalid_after_observed_change_and_byte_restore(editor_workspace, monkeypatch, action):
    w = editor_workspace
    draft = reorder(w)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    assert job['status'] == 'COMPLETED'
    job_id = job['id']
    output = w.output / job['results'][0]['output_relative']
    initial = output.read_bytes()
    original = w._native
    reached, release = threading.Event(), threading.Event()
    outcomes = []

    def pause_after_native(request, **kwargs):
        result = original(request, **kwargs)
        reached.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(w, '_native', pause_after_native)

    def first_reader():
        try:
            outcomes.append(w.editor_output(job_id, action))
        except Exception as exc:
            outcomes.append(exc)

    thread = threading.Thread(target=first_reader)
    thread.start()
    try:
        assert reached.wait(10)
        output.write_bytes(initial + b'\n% changed while another output read was in flight\n')
        # This second request observes and permanently invalidates the output
        # before starting any native work of its own.
        with pytest.raises(ValueError, match='OUTPUT_CHANGED'):
            w.editor_output(job_id, action)
        assert w.editor_outputs[job_id]['invalidated']
        output.write_bytes(initial)
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive() and len(outcomes) == 1
    assert isinstance(outcomes[0], ValueError) and 'OUTPUT_CHANGED' in str(outcomes[0])


@pytest.mark.parametrize('action', ['page', 'navigation'])
def test_native_observed_output_change_permanently_invalidates_registration(editor_workspace, monkeypatch, action):
    w = editor_workspace
    draft = reorder(w)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    output = w.output / job['results'][0]['output_relative']
    initial = output.read_bytes()
    native = w._native

    def change_only_during_native_read(request, **kwargs):
        output.write_bytes(initial + b'\n% native observes changed output\n')
        try:
            return native(request, **kwargs)
        finally:
            output.write_bytes(initial)

    monkeypatch.setattr(w, '_native', change_only_during_native_read)
    with pytest.raises(ValueError, match='OUTPUT_CHANGED'):
        w.editor_output(job['id'], action)
    assert w.editor_outputs[job['id']]['invalidated']
    monkeypatch.setattr(w, '_native', native)
    with pytest.raises(ValueError, match='OUTPUT_CHANGED'):
        w.editor_output(job['id'], action)


@pytest.mark.parametrize('kind', ['organize', 'linearize'])
def test_proof_temporary_cleanup_failure_rolls_back_pair_and_keeps_error_evidence(editor_workspace, monkeypatch, kind):
    import ezctd.safe_io as io
    w = editor_workspace
    draft = reorder(w)
    before = sha256_file(w.docs['1'].path)
    if kind == 'linearize':
        plan = wait(w, w.start('plan', ['1']))
        assert plan['can_apply']
    unlink = io.os.unlink
    injected = False

    def fail_first_proof_temporary_cleanup(path, *args, **kwargs):
        nonlocal injected
        if not injected and Path(path).name.startswith('.ezctd-output-') and 'copies' in Path(path).parts:
            injected = True
            raise PermissionError('synthetic unlink failure after successful proof publication')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(io.os, 'unlink', fail_first_proof_temporary_cleanup)
    job_id = (w.editor_save(draft['draft_id'], draft['revision'], confirmed=True) if kind == 'organize'
              else w.start('apply', plan_id=plan['id'], confirmed=True))
    job = wait(w, job_id)
    assert injected and job['status'] == 'COMPLETED_WITH_ERRORS'
    assert job['results'][0]['status'] == 'ERROR'
    message = job['results'][0]['message']
    assert 'PublishedOutputCleanupError' in message and 'PermissionError' in message
    assert 'synthetic unlink failure after successful proof publication' in message
    saved_job = json.loads((w.output / 'jobs' / f'{job_id}.json').read_text(encoding='utf-8'))
    assert saved_job['results'][0]['message'] == message
    assert not list(w.output.rglob('*.pdf')) and not list(w.output.rglob('*.ezctd.json'))
    assert not list(w.output.rglob('.ezctd-output-*'))
    assert sha256_file(w.docs['1'].path) == before


def test_cleanup_rollback_never_deletes_replaced_proof_with_a_different_inode(editor_workspace, monkeypatch):
    import ezctd.safe_io as io
    w = editor_workspace
    draft = reorder(w)
    unlink = io.os.unlink
    injected = False
    replacement = b'other user output: must not be removed by this transaction'

    def replace_proof_and_fail_temporary_cleanup(path, *args, **kwargs):
        nonlocal injected
        if not injected and Path(path).name.startswith('.ezctd-output-') and 'copies' in Path(path).parts:
            injected = True
            proof = next(Path(path).parent.glob('*.ezctd.json'))
            unlink(proof)
            proof.write_bytes(replacement)
            raise PermissionError('synthetic proof cleanup failure after external path replacement')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(io.os, 'unlink', replace_proof_and_fail_temporary_cleanup)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    assert injected and job['status'] == 'COMPLETED_WITH_ERRORS'
    proofs = list(w.output.rglob('*.ezctd.json'))
    assert len(proofs) == 1 and proofs[0].read_bytes() == replacement
    assert not list(w.output.rglob('*.pdf')) and not list(w.output.rglob('.ezctd-output-*'))


def test_successful_writer_receipt_never_takes_ownership_of_replacement_proof(editor_workspace, monkeypatch, tmp_path):
    import os
    import ezctd.copy_service as service
    w = editor_workspace
    draft = reorder(w)
    writer = service.write_new_text
    replacement = b'other user file replaced the proof path after publication'
    held = tmp_path / 'held-original-proof.json'
    identities = []

    def replace_after_success(path, *args, **kwargs):
        result = writer(path, *args, **kwargs)
        original = path.stat()
        os.link(path, held)  # Keep the old inode live; do not allow inode reuse to blur this test.
        path.unlink()
        path.write_bytes(replacement)
        changed = path.stat()
        identities.extend([(original.st_dev, original.st_ino), (changed.st_dev, changed.st_ino)])
        next(event for ident, event in w.events.items() if w.jobs[ident]['kind'] == 'organize').set()
        return result

    monkeypatch.setattr(service, 'write_new_text', replace_after_success)
    job = wait(w, w.editor_save(draft['draft_id'], draft['revision'], confirmed=True))
    assert job['status'] == 'CANCELLED' and job['results'][0]['status'] == 'CANCELLED'
    assert len(identities) == 2 and identities[0] != identities[1]
    proofs = list(w.output.rglob('*.ezctd.json'))
    assert len(proofs) == 1 and proofs[0].read_bytes() == replacement
    assert not list(w.output.rglob('*.pdf'))
