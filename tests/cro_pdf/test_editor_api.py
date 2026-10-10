"""Authenticated HTTP page-edit workflow against real disposable PDF workers."""
from __future__ import annotations

import json

import pikepdf
import pytest

from test_workbench import request, server, workspace, wait


def post(server, action, payload):
    status, body, _ = request(server, '/api/editor/' + action, payload)
    return status, json.loads(body)


def test_real_http_edit_save_reopen_and_refresh(server):
    status, draft = post(server, 'open', {'id': '1'})
    assert status == 200 and draft['eligibility'] == 'ELIGIBLE'
    assert post(server, 'open', {'id': '1'})[1] == draft
    status, edited = post(server, 'edit', {'draft_id': draft['draft_id'], 'revision': 0,
                                          'command': {'type': 'reorder', 'order': [2, 1]}})
    assert status == 200 and edited['dirty'] and edited['revision'] == 1
    assert post(server, 'state', {'draft_id': draft['draft_id']})[1] == edited
    status, rotated = post(server, 'edit', {'draft_id': draft['draft_id'], 'revision': 1,
                                           'command': {'type': 'rotate', 'pages': [1], 'degrees': 90}})
    assert status == 200 and rotated['rotations'] == [90, 0]
    common = {'draft_id': draft['draft_id'], 'revision': rotated['revision']}
    status, preview = post(server, 'page', {**common, 'page': 2, 'dpi': 72})
    assert status == 200 and preview['png_base64']
    assert (preview['source_page'], preview['output_position']) == (1, 2)
    assert (preview['width_px'], preview['height_px']) == (400, 300)
    status, nav = post(server, 'navigation', common)
    assert status == 200 and nav['bookmarks'][0]['physical_page'] == 2
    assert post(server, 'save', {**common, 'confirmed': False})[0] == 400
    assert not server.workspace.jobs
    status, response = post(server, 'save', {**common, 'confirmed': True})
    assert status == 200
    job_id = response['job_id']
    assert wait(server.workspace, job_id)['status'] == 'COMPLETED'
    assert post(server, 'save', {**common, 'confirmed': True})[1]['job_id'] == job_id
    job = json.loads(request(server, '/api/job', {'id': job_id})[1])
    assert job['results'][0]['page_count'] == 2
    assert job['results'][0]['saved_revision'] == rotated['revision']
    assert job['results'][0]['proof']['verification_status'] == 'VERIFIED_LOCAL_INVARIANTS'
    status, actual = post(server, 'output-navigation', {'job_id': job_id})
    assert status == 200 and actual['bookmarks'][0]['physical_page'] == 2
    assert actual['read_only'] and [p['source_page'] for p in actual['page_mapping']] == [2, 1]
    status, opened = post(server, 'output-page', {'job_id': job_id, 'page': 2, 'dpi': 72})
    assert status == 200 and 'Clinical Cmax' in opened['text']
    saved = post(server, 'state', {'draft_id': draft['draft_id']})[1]
    assert not saved['saving'] and not saved['dirty'] and saved['save_revision'] == rotated['revision']
    status, undone = post(server, 'undo', common)
    assert status == 200 and undone['rotations'] == [0, 0] and undone['can_redo']
    status, redone = post(server, 'redo', {**common, 'revision': undone['revision']})
    assert status == 200 and not redone['dirty']


@pytest.mark.parametrize(('action', 'payload'), [
    ('open', {'id': '/etc/passwd'}),
    ('open', {'id': '1', 'path': '/etc/passwd'}),
    ('state', {'draft_id': '../editor.json'}),
    ('output-page', {'job_id': '/etc/passwd'}),
    ('output-navigation', {'job_id': 'unknown-job'}),
    ('output-page', {'job_id': 'any', 'path': '/etc/passwd'}),
    ('save', {'draft_id': 'any', 'revision': 0, 'confirmed': True, 'output': '../input/x.pdf'}),
    ('navigation', {'draft_id': 'any', 'revision': 0, 'roots': ['/']}),
])
def test_editor_api_rejects_paths_unknown_ids_and_extra_parameters(server, action, payload):
    assert post(server, action, payload)[0] == 400
    assert not server.workspace.jobs


@pytest.mark.parametrize('revision', [None, True, -1, '0'])
def test_editor_api_requires_typed_revision(server, revision):
    draft = post(server, 'open', {'id': '1'})[1]
    status, _ = post(server, 'edit', {'draft_id': draft['draft_id'], 'revision': revision,
                                     'command': {'type': 'rotate', 'pages': [1], 'degrees': 90}})
    assert status == 400
    assert post(server, 'state', {'draft_id': draft['draft_id']})[1] == draft


def test_editor_api_returns_explicit_stale_revision_conflict(server):
    draft = post(server, 'open', {'id': '1'})[1]
    command = {'draft_id': draft['draft_id'], 'revision': 0, 'command': {'type': 'reorder', 'order': [2, 1]}}
    assert post(server, 'edit', command)[0] == 200
    status, error = post(server, 'edit', command)
    assert status == 409 and error['error_code'] == 'STALE_DRAFT'
    current = post(server, 'state', {'draft_id': draft['draft_id']})[1]
    assert current['order'] == [2, 1] and current['revision'] == 1


@pytest.mark.parametrize('blocker', ['signature', 'password'])
def test_editor_blockers_are_visible_without_fabricated_page_metadata(server, blocker, tmp_path):
    source = server.workspace.docs['1'].path
    altered = tmp_path / 'blocked.pdf'
    with pikepdf.open(source) as pdf:
        if blocker == 'signature':
            pdf.Root.Guard = pikepdf.Dictionary(FT=pikepdf.Name.Sig)
            pdf.save(altered)
        else:
            pdf.save(altered, encryption=pikepdf.Encryption(user='synthetic-password', owner='synthetic-owner'))
    source.write_bytes(altered.read_bytes())
    status, draft = post(server, 'open', {'id': '1'})
    assert status == 200, draft
    assert draft['eligibility'] == 'BLOCKED' and draft['blockers']
    assert draft['pages'] == [] and not draft['dirty'] and not draft['can_undo']
    if blocker == 'password':
        assert 'PASSWORD_REQUIRED' in draft['blockers']
    else:
        assert any('SIGNATURE' in item for item in draft['blockers'])
    common = {'draft_id': draft['draft_id'], 'revision': draft['revision']}
    assert post(server, 'page', common)[0] == 400
    assert post(server, 'save', {**common, 'confirmed': True})[0] == 400
    assert not server.workspace.jobs


def test_unrelated_job_cannot_open_any_output_and_output_hash_is_checked(server):
    w = server.workspace
    scan_id = w.start('scan', ['1'])
    assert wait(w, scan_id)['status'] == 'COMPLETED'
    assert post(server, 'output-page', {'job_id': scan_id})[0] == 400
    draft = post(server, 'open', {'id': '1'})[1]
    draft = post(server, 'edit', {'draft_id': draft['draft_id'], 'revision': draft['revision'],
                                  'command': {'type': 'reorder', 'order': [2, 1]}})[1]
    response = post(server, 'save', {'draft_id': draft['draft_id'], 'revision': draft['revision'],
                                    'confirmed': True})[1]
    job = wait(w, response['job_id'])
    output = w.output / job['results'][0]['output_relative']
    output.write_bytes(output.read_bytes() + b'\n% synthetic output edit\n')
    status, error = post(server, 'output-page', {'job_id': job['id']})
    assert status == 400 and error['error_code'] == 'OUTPUT_CHANGED'
