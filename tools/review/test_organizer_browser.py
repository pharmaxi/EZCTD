"""Real page-organization workflow, imported by the existing Chromium gate.

All PDFs are synthetic. Output assertions reopen the actual published PDF with
pikepdf and PDFium; a changed grid or a successful HTTP response is not enough.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import re
import threading

from playwright.sync_api import expect

from ezctd.cli import _default_rulepack
from ezctd.safe_io import sha256_file
from ezctd.workspace import ACTIVE_JOB_STATES, Workspace
from ezctd.workbench import LocalServer


def build_organizer_fixture(root: Path, demo) -> dict:
    import pikepdf

    root.mkdir()
    source = root / 'input'
    source.mkdir()
    intermediate = root / 'synthetic-draft.pdf'
    demo.make_pdf(intermediate, pages=6, title='SYNTHETIC PAGE ORGANIZATION')
    with pikepdf.open(intermediate) as pdf:
        pdf.pages[1].obj.Rotate = 90
        pdf.pages[3].obj.CropBox = pikepdf.Array([12, 20, 583, 824])
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
            0, pikepdf.Dictionary(S=pikepdf.Name.r),
            2, pikepdf.Dictionary(S=pikepdf.Name.D),
        ]))
        with pdf.open_outline() as outline:
            outline.root[0].children.append(pikepdf.OutlineItem('Appendix target page six', 5))
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            pikepdf.String('ResultsFive'), pikepdf.Array([pdf.pages[4].obj, pikepdf.Name.Fit]),
        ])))
        pdf.pages[0].obj.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([40, 740, 260, 765]), Border=pikepdf.Array([0, 0, 0]),
            Dest=pikepdf.Array([pdf.pages[3].obj, pikepdf.Name.Fit]),
        ))])
        pdf.pages[2].obj.Annots = pikepdf.Array([pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([40, 740, 260, 765]), Border=pikepdf.Array([0, 0, 0]),
            Dest=pikepdf.String('ResultsFive'),
        ))])
        pdf.save(source / '01-report-with-navigation.pdf')
    intermediate.unlink()
    demo.make_pdf(source / '02-other-report.pdf', pages=2, title='SYNTHETIC SECOND DOCUMENT')
    demo.make_pdf(source / '03-signature-signal.pdf', pages=1, signature_signal=True)
    return {'source': source, 'output': root / 'workspace'}


def inspect_published_pdf(path: Path) -> dict:
    """Independent assertions against known fixture relationships, not proof flags."""
    import pikepdf
    import pypdfium2 as pdfium

    with pikepdf.open(path, attempt_recovery=False) as pdf:
        assert not pdf.check_pdf_syntax()
        by_object = {page.obj.objgen: i + 1 for i, page in enumerate(pdf.pages)}
        first = pdf.Root.Outlines.First
        bookmarks = {
            'first': by_object[first.Dest[0].objgen],
            'nested_six': by_object[first.First.Dest[0].objgen],
            'second': by_object[first.Next.Dest[0].objgen],
        }
        links = []
        for i, page in enumerate(pdf.pages, 1):
            for annot in page.obj.get('/Annots', []):
                if str(annot.get('/Subtype', '')) != '/Link':
                    continue
                destination = annot.Dest
                if isinstance(destination, pikepdf.String):
                    names = pdf.Root.Names.Dests.Names
                    target = next(names[n + 1] for n in range(0, len(names), 2)
                                  if str(names[n]) == str(destination))
                else:
                    target = destination
                links.append({'from': i, 'to': by_object[target[0].objgen]})
    pages = []
    with closing(pdfium.PdfDocument(path)) as pdf:
        for i in range(len(pdf)):
            with closing(pdf[i]) as page, closing(page.get_textpage()) as text:
                value = text.get_text_bounded(errors='strict')
                original = re.search(r'Physical page (\d+) / 6', value)
                assert original, f'Output page {i + 1} lost its synthetic source marker'
                pages.append({'output_page': i + 1, 'source_page': int(original[1]),
                              'rotation_degrees': page.get_rotation(),
                              'page_label': pdf.get_page_label(i), 'size': list(page.get_size())})
    return {'sha256': sha256_file(path), 'pages': pages, 'bookmarks': bookmarks, 'links': links}


def organizer_case(browser, demo, output, checks, errors, external, expected_diagnostics,
                   controls, viewports, helpers):
    """Select/move/rotate/undo/redo/save/reopen through actual visible controls."""
    BrowserDiagnostics, pdf_hashes, wait_for_condition = helpers
    fixture = output / 'page-organizer'
    paths = build_organizer_fixture(fixture, demo)
    source = paths['source']
    before = pdf_hashes(source)
    workspace = Workspace(source, paths['output'], _default_rulepack())
    server = LocalServer(workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport={'width': 1500, 'height': 1000})
    page = context.new_page()
    page.set_default_timeout(30000)
    monitor = BrowserDiagnostics(page, errors, expected_diagnostics)
    published_evidence = None
    requests = []
    http_diagnostics = []

    def route(request):
        if request.request.url.startswith(server.origin + '/'):
            request.continue_()
        else:
            external.append(request.request.url)
            request.abort()

    def record(request):
        if '/api/editor/' in request.url:
            requests.append({'endpoint': request.url.rsplit('/api/', 1)[1],
                             'payload': request.post_data_json})

    def record_response(response):
        if '/api/editor/' not in response.url or response.status < 400:
            return
        item = {'endpoint': response.url.rsplit('/api/', 1)[1], 'status': response.status,
                'payload': response.request.post_data_json}
        try:
            item['body'] = response.json()
        except Exception as error:
            item['unavailable_body'] = str(error).replace(server.token, '<redacted-session-token>')
        http_diagnostics.append(item)

    def grid_order():
        return page.locator('#organizer-pages .organizer-page').evaluate_all(
            '(items) => items.map(item => Number(item.dataset.sourcePage))')

    def ready():
        expect(page.locator('#organizer-canvas')).to_be_visible(timeout=120000)
        expect(page.locator('#organizer-rotate-cw')).to_be_enabled(timeout=120000)

    context.route('**/*', route)
    page.on('request', record)
    page.on('response', record_response)
    try:
        page.goto(server.origin + '/#key=' + server.token)
        expect(page).to_have_title(re.compile('EZCTD.*临床 PDF 工作台'))
        expect(page.locator('.file-row')).to_have_count(3)
        page.locator('.file-open[title="01-report-with-navigation.pdf"]').click()
        expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 1 / 6'))
        page.click('#mode-organize')
        expect(page.locator('#organizer-pages .organizer-page')).to_have_count(6, timeout=120000)
        expect(page.locator('#organizer-canvas')).to_be_visible(timeout=120000)
        assert grid_order() == [1, 2, 3, 4, 5, 6]
        expect(page.locator('#organizer-save')).to_be_disabled()
        checks.append('organizer_opens_real_six_page_document_with_original_identity_and_noop_save_disabled')

        page.locator('#organizer-pages [data-source-page="2"]').click()
        page.locator('#organizer-pages [data-source-page="3"]').click(modifiers=['Shift'])
        expect(page.locator('#organizer-pages .organizer-page[aria-pressed="true"]')).to_have_count(2)
        page.locator('#organizer-pages [data-source-page="2"]').drag_to(
            page.locator('#organizer-pages [data-source-page="5"]'))
        wait_for_condition(page, lambda: grid_order() == [1, 4, 2, 3, 5, 6], 'Dragging selected pages did not move the group')
        ready()
        page.click('#organizer-undo')
        wait_for_condition(page, lambda: grid_order() == [1, 2, 3, 4, 5, 6], 'Undo did not restore the dragged group')
        ready()
        checks.append('organizer_shift_multiselect_and_real_pointer_drag_move_the_selected_group')

        page.fill('#organizer-range', '2-3')
        page.click('#organizer-select-range')
        expect(page.locator('#organizer-pages .organizer-page[aria-pressed="true"]')).to_have_count(2)
        page.fill('#organizer-move-position', '5')
        page.click('#organizer-move-to')
        wait_for_condition(page, lambda: grid_order() == [1, 4, 5, 6, 2, 3], 'Selected page group was not moved')
        ready()
        page.click('#organizer-rotate-cw')
        expect(page.locator('#organizer-undo')).to_be_enabled(timeout=120000)
        ready()
        page.fill('#organizer-page-number', '6')
        page.press('#organizer-page-number', 'Enter')
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 3 / 6'), timeout=120000)
        expect(page.locator('#organizer-canvas')).to_be_visible()
        wait_for_condition(page, lambda: page.locator('#organizer-canvas').evaluate('(c) => c.width > c.height'),
                           'Persistent rotation did not render a landscape preview')
        checks.append('organizer_multiselect_moves_group_and_renders_actual_rotated_pdf_bytes')
        page.screenshot(path=str(output / 'organizer-edited-1500.png'), full_page=True)

        page.click('#organizer-undo')
        ready()
        page.click('#organizer-undo')
        wait_for_condition(page, lambda: grid_order() == [1, 2, 3, 4, 5, 6], 'Undo did not restore source order')
        ready()
        page.click('#organizer-redo')
        wait_for_condition(page, lambda: grid_order() == [1, 4, 5, 6, 2, 3], 'Redo did not restore edited order')
        ready()
        page.click('#organizer-redo')
        ready()
        checks.append('organizer_undo_redo_restores_both_page_order_and_rotation')

        page.locator('.file-open[title="02-other-report.pdf"]').click()
        page.locator('.file-open[title="01-report-with-navigation.pdf"]').click()
        page.click('#mode-organize')
        wait_for_condition(page, lambda: grid_order() == [1, 4, 5, 6, 2, 3], 'Switching documents lost the editing draft')
        expect(page.locator('#organizer-undo')).to_be_enabled(timeout=120000)
        expect(page.locator('#organizer-save')).to_be_enabled(timeout=120000)
        checks.append('organizer_document_switch_preserves_draft_and_edit_history')

        for width, height in [(1000, 800), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            expect(page.locator('#organizer-save')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'{width}px page overflow'
            page.screenshot(path=str(output / f'organizer-{width}.png'), full_page=True)
            if f'{width}x{height}' not in viewports:
                viewports.append(f'{width}x{height}')
        checks.append('organizer_desktop_narrow_and_mobile_layouts_keep_controls_without_document_overflow')
        page.set_viewport_size({'width': 1500, 'height': 1000})

        with page.expect_response(lambda response: response.url == server.origin + '/api/editor/save') as answer:
            page.click('#organizer-save')
        response = answer.value
        assert response.ok, response.text()
        job_id = response.json()['job_id']
        wait_for_condition(page, lambda: workspace.job(job_id)['status'] not in ACTIVE_JOB_STATES,
                           'Page organization save did not finish', timeout=180)
        job = workspace.job(job_id)
        assert job['kind'] == 'organize' and job['status'] == 'COMPLETED', job
        outputs = list(workspace.output.rglob('*.pdf'))
        assert len(outputs) == 1, outputs
        actual = inspect_published_pdf(outputs[0])
        assert [p['source_page'] for p in actual['pages']] == [1, 4, 5, 6, 2, 3]
        assert [p['rotation_degrees'] for p in actual['pages']] == [0, 0, 0, 0, 180, 90]
        assert [p['page_label'] for p in actual['pages']] == ['i', '2', '3', '4', 'ii', '1']
        assert actual['bookmarks'] == {'first': 1, 'nested_six': 4, 'second': 5}
        assert actual['links'] == [{'from': 1, 'to': 2}, {'from': 6, 'to': 3}]
        proof = json.loads(outputs[0].with_name(outputs[0].name + '.ezctd.json').read_text(encoding='utf-8'))
        assert proof['output_sha256'] == actual['sha256']
        assert proof['source_sha256'] == before['01-report-with-navigation.pdf']
        assert proof['verification_status'] == 'VERIFIED_LOCAL_INVARIANTS'
        published_evidence = {'job_id': job_id, 'actual_pdf': actual, 'proof': proof,
                              'output_relative_path': outputs[0].relative_to(workspace.output).as_posix()}
        checks.append('organizer_publishes_real_reordered_rotated_pdf_with_bookmarks_links_named_targets_and_labels_preserved')

        # The same save request is a retry of an uncertain response, not a second publication.
        saved_request = next(row['payload'] for row in reversed(requests) if row['endpoint'] == 'editor/save')
        again = page.request.post(server.origin + '/api/editor/save',
                                  headers={'Origin': server.origin, 'Authorization': 'Bearer ' + server.token},
                                  data=saved_request)
        assert again.ok and again.json()['job_id'] == job_id
        assert len(list(workspace.output.rglob('*.pdf'))) == 1
        checks.append('organizer_same_revision_save_replay_returns_existing_job_without_duplicate_output')

        # The worker can finish before the browser's next job poll. Wait for
        # the actual result control instead of racing the modal's appearance.
        expect(page.locator('#task-dialog')).to_be_visible(timeout=120000)
        expect(page.locator('#open-edited-output')).to_be_visible(timeout=120000)
        page.click('#open-edited-output')
        expect(page.locator('#organizer-canvas')).to_be_visible(timeout=120000)
        page.fill('#organizer-page-number', '6')
        page.press('#organizer-page-number', 'Enter')
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 3 / 6'), timeout=120000)
        wait_for_condition(page, lambda: page.locator('#organizer-canvas').evaluate('(c) => c.width > c.height'),
                           'Reopened saved output did not preserve actual page rotation')
        expect(page.locator('#organizer-save')).to_be_disabled()
        page.click('#organizer-navigation summary')
        expect(page.locator('#organizer-bookmarks .organizer-bookmark[data-page="4"]')).to_be_visible()
        page.locator('#organizer-bookmarks .organizer-bookmark[data-page="4"]').click()
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 6 / 6'), timeout=120000)
        page.screenshot(path=str(output / 'organizer-saved-reopened.png'), full_page=True)
        checks.append('organizer_reopens_actual_saved_pdf_and_its_remapped_bookmark_target_in_readonly_mode')

        # Hold a genuine old PDF preview across a revision change. The client
        # must discard/cancel it; the rendered bytes are never fabricated.
        page.locator('.file-open[title="02-other-report.pdf"]').click()
        page.click('#mode-organize')
        ready()
        old_revision = int(page.locator('#organizer-panel').get_attribute('data-revision'))
        held = []

        def hold_old_preview(request):
            payload = request.request.post_data_json
            if payload['revision'] == old_revision and payload.get('page') == 2 and not payload.get('thumbnail'):
                response = request.fetch()
                assert response.ok, response.text()
                held.append((request, response))
            else:
                request.continue_()

        page.route(server.origin + '/api/editor/page', hold_old_preview)
        page.locator('#organizer-pages [data-source-page="2"]').click()
        wait_for_condition(page, lambda: len(held) == 1, 'Old native preview was not captured')
        assert held[0][1].json()['rotation_degrees'] == 0
        page.click('#organizer-rotate-cw')
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-revision', str(old_revision + 1), timeout=120000)
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 2 / 2'))
        current_pixels = page.locator('#organizer-canvas').evaluate('(canvas) => canvas.toDataURL()')
        assert page.locator('#organizer-canvas').evaluate('(canvas) => canvas.width > canvas.height')
        held[0][0].fulfill(response=held[0][1])
        page.unroute(server.origin + '/api/editor/page', hold_old_preview)
        page.wait_for_timeout(100)  # Deliver the intentionally late route completion.
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-revision', str(old_revision + 1))
        assert current_pixels == page.locator('#organizer-canvas').evaluate('(canvas) => canvas.toDataURL()')
        checks.append('organizer_late_native_preview_cannot_replace_the_new_revision_or_its_pixels')
        controls.append({'case': 'organizer_late_preview', 'mechanism': 'hold_genuine_native_old_revision_response_across_rotate',
                         'fabricated_native_payload': False, 'old_revision': old_revision, 'new_revision': old_revision + 1})

        # The server really accepts and publishes this edit, but both the save
        # response and first state-recovery request are lost at the browser.
        # The visible reconnect control must find that same job without saving
        # or rotating again.
        accepted_jobs = []
        saves_before = sum(row['endpoint'] == 'editor/save' for row in requests)

        def lose_accepted_save(request):
            response = request.fetch()
            assert response.ok, response.text()
            accepted_jobs.append(response.json()['job_id'])
            request.abort('failed')

        monitor.permit(server.origin + '/api/editor/save', 'net::ERR_FAILED', 'organizer_double_lost_response')
        monitor.permit(server.origin + '/api/editor/state', 'net::ERR_FAILED', 'organizer_double_lost_response')
        page.route(server.origin + '/api/editor/save', lose_accepted_save, times=1)
        page.route(server.origin + '/api/editor/state', lambda request: request.abort('failed'), times=1)
        page.click('#organizer-save')
        expect(page.locator('#organizer-reconnect')).to_be_visible(timeout=120000)
        expect(page.locator('#organizer-save')).to_be_disabled()
        expect(page.locator('#organizer-rotate-cw')).to_be_disabled()
        page.screenshot(path=str(output / 'organizer-save-unknown.png'), full_page=True)
        assert len(accepted_jobs) == 1
        recovery_job_id = accepted_jobs[0]
        wait_for_condition(page, lambda: workspace.job(recovery_job_id)['status'] not in ACTIVE_JOB_STATES,
                           'Accepted edit did not complete while its response was lost', timeout=180)
        assert workspace.job(recovery_job_id)['status'] == 'COMPLETED'
        page.click('#organizer-reconnect')
        expect(page.locator('#task-dialog')).to_be_visible(timeout=120000)
        expect(page.locator('#open-edited-output')).to_be_visible()
        assert sum(row['endpoint'] == 'editor/save' for row in requests) - saves_before == 1
        assert len(list(workspace.output.rglob('*.pdf'))) == 2
        page.click('#open-edited-output')
        page.fill('#organizer-page-number', '2')
        page.press('#organizer-page-number', 'Enter')
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 2 / 2'), timeout=120000)
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-revision', str(old_revision + 1))
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-mode', 'saved')
        assert page.locator('#organizer-canvas').evaluate('(canvas) => canvas.width > canvas.height')
        import pikepdf
        recovered_path = next(path for path in workspace.output.rglob('*.pdf') if path.name == '02-other-report.pdf')
        with pikepdf.open(recovered_path) as pdf:
            assert len(pdf.pages) == 2
            assert [int(p.obj.get('/Rotate', 0)) for p in pdf.pages] == [0, 90]
        recovered_proof = json.loads(recovered_path.with_name(recovered_path.name + '.ezctd.json').read_text(encoding='utf-8'))
        assert recovered_proof['order'] == [1, 2] and recovered_proof['rotations'] == [0, 90]
        assert recovered_proof['output_sha256'] == sha256_file(recovered_path)
        published_evidence['recovered_save'] = {'job_id': recovery_job_id, 'proof': recovered_proof,
                                               'browser_save_request_count': 1}
        page.screenshot(path=str(output / 'organizer-save-recovered.png'), full_page=True)
        checks.append('organizer_lost_accepted_save_and_state_responses_recover_one_actual_output_without_replaying_edits')
        controls.append({'case': 'organizer_double_lost_response',
                         'mechanism': 'abort_accepted_save_response_and_first_state_recovery_request',
                         'submission_reached_real_server': True, 'browser_save_request_count': 1,
                         'recovered_job_id': recovery_job_id, 'fabricated_native_payload': False})

        page.locator('.file-open[title="03-signature-signal.pdf"]').click()
        page.click('#mode-organize')
        expect(page.locator('#organizer-message')).to_contain_text(re.compile('签名|SIGNATURE'), timeout=120000)
        expect(page.locator('#organizer-save')).to_be_disabled()
        assert len(list(workspace.output.rglob('*.pdf'))) == 2
        checks.append('organizer_signature_signal_blocks_editing_and_publishes_no_additional_pdf')
        page.screenshot(path=str(output / 'organizer-signature-blocked.png'), full_page=True)
        assert page.locator('vite-error-overlay, #webpack-dev-server-client-overlay, nextjs-portal').count() == 0
    except Exception as exc:
        page.screenshot(path=str(output / 'organizer-failure.png'), full_page=True)
        raise RuntimeError(str(exc).replace(server.token, '<redacted-session-token>')) from None
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
        after = pdf_hashes(source)
        (fixture / 'INPUT_INTEGRITY.json').write_text(json.dumps({
            'synthetic_only': True, 'input_count': len(before), 'before_sha256': before,
            'after_sha256': after, 'unchanged': before == after,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        (fixture / 'PUBLISHED_PDF_EVIDENCE.json').write_text(json.dumps(published_evidence,
            ensure_ascii=False, indent=2), encoding='utf-8')
        (fixture / 'EDITOR_REQUESTS.json').write_text(json.dumps(requests,
            ensure_ascii=False, indent=2), encoding='utf-8')
        (fixture / 'HTTP_DIAGNOSTICS.json').write_text(json.dumps(http_diagnostics,
            ensure_ascii=False, indent=2), encoding='utf-8')
    assert before == after


def organizer_source_change_recovery_case(browser, demo, output, checks, errors, external,
                                          expected_diagnostics, controls, helpers):
    """A deliberately changed synthetic source must not hide its saved copy."""
    BrowserDiagnostics, pdf_hashes, wait_for_condition = helpers
    fixture = output / 'control-organizer-source-change'
    fixture.mkdir()
    source = fixture / 'input'
    source.mkdir()
    original = source / 'report.pdf'
    demo.make_pdf(original, pages=2, title='SYNTHETIC ORIGINAL BEFORE SAVE')
    changed = fixture / 'changed-source.pdf'
    demo.make_pdf(changed, pages=3, title='SYNTHETIC DELIBERATE SOURCE REPLACEMENT')
    changed_bytes = changed.read_bytes()
    changed.unlink()
    before = pdf_hashes(source)
    workspace = Workspace(source, fixture / 'workspace', _default_rulepack())
    server = LocalServer(workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport={'width': 1500, 'height': 1000})
    page = context.new_page()
    page.set_default_timeout(30000)
    monitor = BrowserDiagnostics(page, errors, expected_diagnostics)
    accepted_jobs, save_requests = [], []
    mutation_performed = False
    expected_after = before
    output_before = None
    output_path = None

    def local_only(request):
        if request.request.url.startswith(server.origin + '/'):
            request.continue_()
        else:
            external.append(request.request.url)
            request.abort()

    def lose_accepted_save(request):
        save_requests.append(request.request.post_data_json)
        response = request.fetch()
        assert response.ok, response.text()
        accepted_jobs.append(response.json()['job_id'])
        request.abort('failed')

    context.route('**/*', local_only)
    try:
        page.goto(server.origin + '/#key=' + server.token)
        expect(page.locator('.file-row')).to_have_count(1)
        page.locator('.file-open').click()
        expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 1 / 2'))
        page.click('#mode-organize')
        expect(page.locator('#organizer-rotate-cw')).to_be_enabled(timeout=120000)
        page.click('#organizer-rotate-cw')
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-revision', '1', timeout=120000)
        expect(page.locator('#organizer-pages img')).to_have_count(2, timeout=120000)
        monitor.permit(server.origin + '/api/editor/save', 'net::ERR_FAILED', 'organizer_source_change_recovery')
        monitor.permit(server.origin + '/api/editor/state', 'net::ERR_FAILED', 'organizer_source_change_recovery')
        page.route(server.origin + '/api/editor/save', lose_accepted_save, times=1)
        page.route(server.origin + '/api/editor/state', lambda request: request.abort('failed'), times=1)
        page.click('#organizer-save')
        expect(page.locator('#organizer-reconnect')).to_be_visible(timeout=120000)
        assert len(accepted_jobs) == 1
        job_id = accepted_jobs[0]
        wait_for_condition(page, lambda: workspace.job(job_id)['status'] not in ACTIVE_JOB_STATES,
                           'Save did not finish before deliberate source replacement', timeout=180)
        assert workspace.job(job_id)['status'] == 'COMPLETED'
        output_path, = workspace.output.rglob('*.pdf')
        output_before = sha256_file(output_path)

        # This is the only deliberate input write in this isolated case; both
        # hashes are recorded separately from the untouched ordinary fixtures.
        original.write_bytes(changed_bytes)
        mutation_performed = True
        expected_after = pdf_hashes(source)
        assert expected_after != before
        for _ in range(2):
            monitor.permit(server.origin + '/api/editor/state', '400 (Bad Request)',
                           'organizer_native_source_changed_after_published_save')
        page.click('#organizer-reconnect')
        expect(page.locator('#task-dialog')).to_be_visible(timeout=120000)
        expect(page.locator('#organizer-message')).to_contain_text('源文件已变化')
        expect(page.locator('#organizer-save')).to_be_disabled()
        expect(page.locator('#organizer-canvas')).to_be_hidden()
        checks.append('organizer_real_source_replacement_invalidates_the_unsaved_editor_identity')
        page.click('#open-edited-output')
        expect(page.locator('#organizer-canvas')).to_have_attribute('data-mode', 'saved', timeout=120000)
        expect(page.locator('#organizer-state-dot')).to_have_class('saved')
        expect(page.locator('#document-draft-badge')).to_have_text('草稿已失效')
        expect(page.locator('#organizer-page-text')).to_have_value(re.compile('Physical page 1 / 2'))
        expect(page.locator('#organizer-preview-count')).to_have_text('/ 2')
        expect(page.locator('#identity')).to_contain_text(output_before)
        assert len(save_requests) == 1 and len(list(workspace.output.rglob('*.pdf'))) == 1
        assert sha256_file(output_path) == output_before
        proof = json.loads(output_path.with_name(output_path.name + '.ezctd.json').read_text(encoding='utf-8'))
        assert proof['source_sha256'] == before['report.pdf']
        assert proof['output_sha256'] == output_before and proof['page_count'] == 2
        page.screenshot(path=str(output / 'organizer-output-after-source-change.png'), full_page=True)
        checks.append('organizer_recovers_exact_published_job_after_source_change_without_repeating_the_save')
        controls.append({'case': 'organizer_source_change_recovery', 'submission_reached_real_server': True,
                         'mechanism': 'lose_save_and_state_responses_then_replace_synthetic_source_after_real_publication',
                         'browser_save_request_count': len(save_requests), 'recovered_job_id': job_id,
                         'fabricated_native_payload': False})
    except Exception as exc:
        page.screenshot(path=str(output / 'organizer-source-change-failure.png'), full_page=True)
        raise RuntimeError(str(exc).replace(server.token, '<redacted-session-token>')) from None
    finally:
        context.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
        after = pdf_hashes(source)
        (fixture / 'INPUT_INTEGRITY.json').write_text(json.dumps({
            'synthetic_only': True, 'deliberate_source_mutation': mutation_performed,
            'before_sha256': before, 'expected_after_sha256': expected_after, 'after_sha256': after,
            'only_deliberate_change_observed': after == expected_after,
            'saved_output_sha256_before_source_change': output_before,
            'saved_output_sha256_after_source_change': sha256_file(output_path) if output_path else None,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    assert mutation_performed and after == expected_after


def main():
    """Focused iteration entry; the full browser gate also runs this same case."""
    import argparse
    import importlib.metadata
    from playwright.sync_api import sync_playwright
    from test_workbench_browser import BrowserDiagnostics, load_module, pdf_hashes, wait_for_condition

    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--browser')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    demo = load_module(root / 'tools/demo/build_workbench_demo.py', 'organizer_demo')
    checks, errors, external, expected, controls, viewports, failures = [], [], [], [], [], ['1500x1000'], []
    source_before = {p.relative_to(root).as_posix(): sha256_file(p)
                     for p in sorted((root / 'src/ezctd').rglob('*'))
                     if p.is_file() and p.suffix in ('.py', '.js', '.html', '.css')}
    browser_version = None
    try:
        with sync_playwright() as engine:
            options = {'headless': True}
            if args.browser:
                options['executable_path'] = args.browser
            browser = engine.chromium.launch(**options)
            browser_version = browser.version
            try:
                organizer_case(browser, demo, args.output, checks, errors, external, expected,
                               controls, viewports, (BrowserDiagnostics, pdf_hashes, wait_for_condition))
                organizer_source_change_recovery_case(browser, demo, args.output, checks, errors, external,
                                                      expected, controls, (BrowserDiagnostics, pdf_hashes, wait_for_condition))
            finally:
                browser.close()
    except Exception as exc:
        failures.append(f'{type(exc).__name__}: {exc}')
        raise
    finally:
        source_after = {name: sha256_file(root / name) for name in source_before}
        result = {'synthetic_only': True, 'browser_plugin': 'not available',
                  'browser': 'Chromium via Playwright', 'browser_version': browser_version,
                  'playwright_version': importlib.metadata.version('playwright'),
                  'checks': checks, 'errors': errors, 'external_requests': external,
                  'expected_diagnostics': expected, 'controls': controls, 'viewports': viewports,
                  'failures': failures, 'source_sha256': source_before,
                  'source_unchanged_during_run': source_before == source_after,
                  'result': 'PASS' if not failures and not errors and not external and source_before == source_after else 'FAIL'}
        (args.output / 'ORGANIZER_BROWSER_RESULT.json').write_text(json.dumps(result,
            ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
    assert not failures and not errors and not external and source_before == source_after


if __name__ == '__main__':
    main()
