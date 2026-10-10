"""Real loopback/API regressions for the bounded reading and task routes."""
import json

import pytest

from test_workbench import request, server, workspace, wait


@pytest.mark.parametrize('payload', [
    {'id': '1', 'query': 'Clinical', 'start_page': 0},
    {'id': '1', 'query': 'Clinical', 'start_page': True},
    {'id': '1', 'query': 'Clinical', 'page_limit': 2001},
    {'id': '1', 'query': 'Clinical', 'page_limit': False},
    {'id': '1', 'query': 'Clinical', 'page_limit': '200'},
    {'id': '1', 'query': '\x00'},
])
def test_search_rejects_invalid_or_unbounded_requests(server, payload):
    status, _, _ = request(server, '/api/search', payload)
    assert status == 400


def test_real_paged_search_has_a_followable_next_page(server):
    status, body, _ = request(server, '/api/search',
                             {'id': '1', 'query': 'Clinical', 'page_limit': 1})
    assert status == 200
    first = json.loads(body)
    assert first['next_page'] == 2 and first['truncated']
    status, body, _ = request(server, '/api/search',
                             {'id': '1', 'query': 'Clinical', 'start_page': first['next_page'], 'page_limit': 1})
    assert status == 200
    second = json.loads(body)
    assert second['next_page'] is None
    assert first['source_sha256'] == second['source_sha256']


def test_thumbnail_is_native_bounded_and_read_only(server):
    status, body, _ = request(server, '/api/thumbnail', {'id': '1', 'page': 2})
    assert status == 200
    page = json.loads(body)
    assert page['physical_page'] == 2 and page['page_count'] == 2
    assert 0 < page['width_px'] * page['height_px'] <= 180_000
    assert page['png_base64'] and 'text' not in page
    assert page['input_integrity']['unchanged']
    for payload in ({'id': '1', 'page': True}, {'id': '/etc/passwd', 'page': 1},
                    {'id': '1', 'page': 3}):
        assert request(server, '/api/thumbnail', payload)[0] == 400


def test_history_and_retry_are_session_scoped(server):
    status, body, _ = request(server, '/api/history')
    assert status == 200 and json.loads(body)['jobs'] == []
    ident = server.workspace.start('scan', ['1'])
    assert wait(server.workspace, ident)['status'] == 'COMPLETED'
    history = json.loads(request(server, '/api/history')[1])
    assert history['active_job_id'] is None
    assert history['jobs'][0]['id'] == ident
    assert history['jobs'][0]['can_retry'] is False
    assert request(server, '/api/retry', {'id': ident})[0] == 400
    assert request(server, '/api/retry', {'id': '../jobs/old.json'})[0] == 400
