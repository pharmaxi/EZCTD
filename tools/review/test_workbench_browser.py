"""Real Chromium E2E on synthetic PDFs; never uploads a user report.

Run after installing .[test,ui-test] and Chromium:
python tools/review/test_workbench_browser.py NEW_EVIDENCE_DIR --browser /path/to/chromium
Omit --browser to use Playwright's installed Chromium. No external requests allowed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import re
from pathlib import Path
import sys
import threading
import time

from playwright.sync_api import sync_playwright, expect
from ezctd import __version__
from ezctd.cli import _default_rulepack
from ezctd.safe_io import sha256_file
from ezctd.workspace import ACTIVE_JOB_STATES, Workspace
from ezctd.workbench import LocalServer


def load_module(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def pdf_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix():sha256_file(p) for p in root.rglob('*.pdf')}


def wait_for_condition(page,condition,message: str,timeout: float=120):
    deadline=time.monotonic()+timeout
    while not condition():
        if time.monotonic()>=deadline:raise AssertionError(message)
        page.wait_for_timeout(25)


class BrowserDiagnostics:
    """Only explicitly injected HTTP failures are expected console diagnostics."""
    def __init__(self,page,errors,expected):
        self.errors=errors;self.expected=expected;self.allowed=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',self.console)

    def permit(self,url: str,fragment: str,case: str):
        self.allowed.append({'url':url,'fragment':fragment,'case':case,'remaining':1})

    def console(self,message):
        if message.type!='error':return
        url=message.location.get('url','')
        for allowed in self.allowed:
            if allowed['remaining'] and allowed['url']==url and allowed['fragment'] in message.text:
                allowed['remaining']-=1
                self.expected.append({'case':allowed['case'],'url':url,'message':message.text})
                return
        self.errors.append('console: '+message.text)


def start_ui_job(page, server, selector: str, route: str) -> dict:
    """Click the real control, then follow the actual task and its rendered result."""
    with page.expect_response(lambda response:response.url==server.origin+'/api/'+route) as answer:
        page.click(selector)
    response=answer.value
    assert response.ok,response.text()
    ident=response.json()['job_id'];deadline=time.monotonic()+120
    while True:
        job=server.workspace.job(ident)
        if job['status'] not in ACTIVE_JOB_STATES:break
        if time.monotonic()>=deadline:raise AssertionError(f'Task did not finish: {job["status"]}')
        page.wait_for_timeout(40)
    expect(page.locator('#job-results')).to_be_visible(timeout=120000)
    expect(page.locator('#job-text')).to_contain_text(f'{job["done"]}/{job["total"]}')
    if job['kind'] in ('plan','apply'):
        page.wait_for_selector('#task-dialog[open]',timeout=120000)
    return job


def select_only(page,fragments: list[str]):
    page.select_option('#file-status','all');page.fill('#file-filter','')
    for checkbox in page.locator('.file-row input[type=checkbox]').all():checkbox.uncheck()
    for fragment in fragments:
        # Filename and directory are separate visible nodes; title holds their
        # exact relative path, including the slash between them.
        page.locator('.file-row').filter(has=page.locator(f'.file-open[title*="{fragment}"]')).locator('input[type=checkbox]').check()


def open_history_job(page,ident: str):
    if page.locator('#task-dialog').is_visible():page.click('#close-dialog')
    page.click('#history');page.wait_for_selector('#history-dialog[open]')
    page.locator(f'.history-job[data-job-id="{ident}"]').click()
    page.wait_for_selector('#task-dialog[open]')


def extended_reader_case(browser,demo,output,checks,errors,external,expected_diagnostics,controls):
    """Separate real 201-page fixture; the original eight PDFs remain unchanged."""
    import pikepdf
    fixture=output/'extended-reader';fixture.mkdir()
    draft=fixture/'draft.pdf';demo.make_pdf(draft,pages=201)
    source=fixture/'input';source.mkdir()
    with pikepdf.open(draft) as pdf:
        with pdf.open_outline() as outline:
            outline.root[0].children.append(pikepdf.OutlineItem('Unique nested needle',200))
        pdf.save(source/'long-nested.pdf')
    draft.unlink();before=pdf_hashes(source)
    workspace=Workspace(source,fixture/'workspace',_default_rulepack())
    server=LocalServer(workspace);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    context=browser.new_context(viewport={'width':1500,'height':1000});page=context.new_page()
    page.set_default_timeout(30000);search_requests=[]
    BrowserDiagnostics(page,errors,expected_diagnostics)
    def route(request):
        if request.request.url.startswith(server.origin+'/'):request.continue_()
        else:external.append(request.request.url);request.abort()
    def record_search(request):
        if request.url==server.origin+'/api/search':search_requests.append(request.post_data_json)
    context.route('**/*',route);page.on('request',record_search)
    try:
        page.goto(server.origin+'/#key='+server.token)
        expect(page).to_have_title(re.compile('EZCTD.*临床 PDF 工作台'))
        expect(page.locator('.file-row')).to_have_count(1)
        page.locator('.file-open').click()
        expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 1 / 201'))
        page.click('[data-tab=nav]');expect(page.locator('.bookmark')).to_have_count(3)
        # Delay two genuine native responses so collapse always happens while
        # the bounded group is pending. No thumbnail bytes are fabricated.
        held=[]
        def hold_thumbnail(request):
            if request.request.post_data_json['page']<=2:held.append((request,request.fetch()))
            else:request.continue_()
        # Keep the handler installed until both concurrent routes are released;
        # auto-expiring it can resume another pending route in older Chromium.
        page.route(server.origin+'/api/thumbnail',hold_thumbnail)
        page.click('#show-thumbnails')
        wait_for_condition(page,lambda:len(held)==2,'First thumbnail responses were not received')
        page.click('#show-thumbnails');expect(page.locator('#thumbnail-panel')).to_be_hidden()
        for request,response in held:request.fulfill(response=response)
        expect(page.locator('#thumbnails-more')).to_contain_text('12 / 201',timeout=120000)
        expect(page.locator('#thumbnails-more')).to_be_enabled()
        page.unroute(server.origin+'/api/thumbnail',hold_thumbnail)
        page.click('#show-thumbnails')
        expect(page.locator('#thumbnails .thumbnail')).to_have_count(12)
        expect(page.locator('#thumbnails img')).to_have_count(12,timeout=120000)
        expect(page.locator('#thumbnails')).not_to_contain_text('正在读取')
        page.wait_for_function('() => [...document.querySelectorAll("#thumbnails img")].every(image => image.complete && image.naturalWidth > 0)')
        page.locator('#thumbnails .thumbnail').nth(11).click()
        expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 12 / 201'))
        expect(page.locator('#thumbnails .thumbnail').nth(11)).to_have_attribute('aria-pressed','true')
        checks.append('thumbnail_collapse_reopen_finishes_all_12_native_previews_in_pending_group')
        controls.append({'case':'thumbnail_collapse_reopen','mechanism':'delay_two_genuine_native_responses_until_panel_collapsed','fabricated_native_payload':False})
        page.screenshot(path=str(output/'workbench-thumbnail-reopen.png'),full_page=True)
        page.fill('#bookmark-filter','Unique nested needle')
        expect(page.locator('.bookmark')).to_have_count(2)
        expect(page.locator('#bookmarks')).to_contain_text('1. Pharmacokinetic results')
        expect(page.locator('#bookmarks')).not_to_contain_text('2. Review notes')
        page.locator('.bookmark').filter(has_text='Unique nested needle').click()
        expect(page.locator('#page-number')).to_have_value('201')
        expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 201 / 201'))
        checks.append('bookmark_filter_keeps_matching_child_ancestor_and_real_target')
        page.screenshot(path=str(output/'workbench-nested-bookmarks.png'),full_page=True)
        page.fill('#bookmark-filter','');expect(page.locator('.bookmark')).to_have_count(3)
        page.fill('#search-query','12.50');page.click('#search-doc')
        expect(page.locator('.search-hit')).to_have_count(200,timeout=120000)
        expect(page.locator('#search-more')).to_be_visible()
        expect(page.locator('#search-results-summary')).to_contain_text('200')
        page.click('#search-more')
        expect(page.locator('.search-hit')).to_have_count(201,timeout=120000)
        expect(page.locator('#search-more')).to_be_hidden()
        assert len(search_requests)==2
        assert search_requests[0].get('start_page',1)==1
        assert search_requests[1]['start_page']==201
        assert all(request.get('page_limit',200)==200 for request in search_requests)
        checks.append('full_search_continues_from_page_201_without_repeating_first_200')
        page.screenshot(path=str(output/'workbench-search-continuation.png'),full_page=True)
        page.click('#clear-search');expect(page.locator('.search-hit')).to_have_count(0)
        expect(page.locator('#search-query')).to_have_value('')
        expect(page.locator('#search-more')).to_be_hidden()
    except Exception as exc:
        page.screenshot(path=str(output/'workbench-extended-failure.png'),full_page=True)
        raise RuntimeError(str(exc).replace(server.token,'<redacted-session-token>')) from None
    finally:
        context.close();server.shutdown();server.server_close();thread.join(2)
        unchanged=before==pdf_hashes(source)
        (fixture/'INPUT_INTEGRITY.json').write_text(json.dumps({'synthetic_only':True,
             'input_count':len(before),'before_sha256':before,'unchanged':unchanged},indent=2),encoding='utf-8')
    assert unchanged


def reader_control_cases(page,server,output,checks,monitor,controls):
    """Exercise UI scheduling/invalidation; injected failures are not native tests."""
    page.set_viewport_size({'width':1500,'height':1000})
    page.locator('.file-open[title="m5/5.3.1.2/fasting/clinical-report.pdf"]').click()
    expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 1 / 3'))
    expect(page.locator('#issues .rule-row')).to_have_count(26)
    page.click('#clear-search');expect(page.locator('#page-canvas')).to_be_visible()
    baseline=page.locator('#page-canvas').evaluate('(canvas) => canvas.toDataURL()')
    held=[]
    def hold_page(request):held.append((request,request.fetch()))
    page.route(server.origin+'/api/page',hold_page,times=1)
    page.fill('#search-query','12.50');page.click('#search-page')
    wait_for_condition(page,lambda:len(held)==1,'Native page response was not received')
    assert held[0][1].json()['search_matches'], 'Delayed native response must contain real matches'
    page.fill('#search-query','99.90')
    held[0][0].fulfill(response=held[0][1])
    expect(page.locator('#page-canvas')).to_be_visible()
    expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 1 / 3'))
    expect(page.locator('#search-query')).to_have_value('99.90')
    expect(page.locator('#search-count')).to_have_text('')
    page.wait_for_function('(expected) => document.getElementById("page-canvas").toDataURL() === expected',arg=baseline)
    checks.append('delayed_native_page_response_cannot_draw_previous_query_highlights_or_count')
    controls.append({'case':'page_query_response_race','mechanism':'delay_genuine_native_match_response_until_query_changes','fabricated_native_payload':False})
    page.fill('#search-query','12.50');page.click('#search-page')
    expect(page.locator('#search-count')).to_contain_text('1 处')
    marked=page.locator('#page-canvas').evaluate('(canvas) => canvas.toDataURL()')
    assert marked!=baseline, 'The real native-coordinate highlight must alter the canvas'
    page.fill('#search-query','99.90');expect(page.locator('#search-count')).to_have_text('')
    expect(page.locator('#page-canvas')).to_be_visible()
    page.wait_for_function('(expected) => document.getElementById("page-canvas").toDataURL() === expected',arg=baseline)
    checks.append('editing_query_clears_existing_canvas_highlights_without_discarding_valid_page')
    (output/'PAGE_QUERY_EVIDENCE.json').write_text(json.dumps({
        'synthetic_only':True,'native_response_bytes_unchanged':True,
        'unmarked_canvas_sha256':hashlib.sha256(baseline.encode()).hexdigest(),
        'marked_canvas_sha256':hashlib.sha256(marked.encode()).hexdigest(),
        'canvas_after_query_edit_matches_unmarked':True},indent=2),encoding='utf-8')
    page.screenshot(path=str(output/'workbench-query-invalidation.png'),full_page=True)

    page.fill('#search-query','12.50');page.click('#search-page')
    expect(page.locator('#search-count')).to_contain_text('1 处')
    page.click('#search-doc');expect(page.locator('.search-hit')).to_have_count(3)
    expect(page.locator('.bookmark')).to_have_count(2)
    page.click('#show-thumbnails');expect(page.locator('#thumbnails img')).to_have_count(3)
    report_count=page.locator('#report-issues .rule-row').count();assert report_count>0
    page_url=server.origin+'/api/page'
    ordinary='Synthetic ordinary preview failure'
    monitor.permit(page_url,'400 (Bad Request)','ordinary_page_error_control')
    page.route(page_url,lambda request:request.fulfill(status=400,content_type='application/json',
        body=json.dumps({'error':ordinary,'error_type':'RuntimeError'})),times=1)
    page.click('#search-page');expect(page.locator('#notice')).to_contain_text(ordinary)
    expect(page.locator('#page-canvas')).to_be_hidden()
    expect(page.locator('#issues .rule-row')).to_have_count(26)
    expect(page.locator('.bookmark')).to_have_count(2)
    expect(page.locator('.search-hit')).to_have_count(3)
    expect(page.locator('#thumbnails img')).to_have_count(3)
    expect(page.locator('#report-issues .rule-row')).to_have_count(report_count)
    checks.append('injected_ordinary_page_error_keeps_unrelated_rules_navigation_search_and_report')
    controls.append({'case':'ordinary_page_error_control','mechanism':'one_injected_HTTP_400_response','native_source_mutation':False})
    page.click('#search-page');expect(page.locator('#page-canvas')).to_be_visible()
    expect(page.locator('#search-count')).to_contain_text('1 处')
    changed='Input changed while reading; discard this page result'
    monitor.permit(page_url,'400 (Bad Request)','source_identity_error_control')
    page.route(page_url,lambda request:request.fulfill(status=400,content_type='application/json',
        body=json.dumps({'error':changed,'error_type':'RuntimeError','error_code':'SOURCE_CHANGED'})),times=1)
    page.click('#search-page');expect(page.locator('#identity')).to_contain_text('文件身份已失效')
    expect(page.locator('#page-canvas')).to_be_hidden();expect(page.locator('#page-text')).to_have_value('')
    expect(page.locator('#issues .rule-row')).to_have_count(0)
    expect(page.locator('.bookmark')).to_have_count(0)
    expect(page.locator('.search-hit')).to_have_count(0)
    expect(page.locator('#thumbnails .thumbnail')).to_have_count(0)
    expect(page.locator('#report-issues .rule-row')).to_have_count(0)
    expect(page.locator('#search-more')).to_be_hidden()
    checks.append('injected_native_text_source_changed_error_clears_all_stale_document_evidence')
    controls.append({'case':'source_identity_error_control','mechanism':'one_injected_HTTP_400_with_actual_native_error_text_and_SOURCE_CHANGED_code','native_source_mutation':False})
    page.screenshot(path=str(output/'workbench-source-invalidation.png'),full_page=True)


def submission_recovery_case(browser,demo,output,checks,errors,external,expected_diagnostics,controls,accepted: bool):
    """A fresh session loses the first submission response and its history read."""
    name='control-recovery-accepted' if accepted else 'control-recovery-rejected'
    fixture=output/name;source=fixture/'input';source.mkdir(parents=True)
    demo.make_pdf(source/'synthetic-recovery.pdf',pages=2);before=pdf_hashes(source)
    workspace=Workspace(source,fixture/'workspace',_default_rulepack())
    server=LocalServer(workspace);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    context=browser.new_context(viewport={'width':1500,'height':1000});page=context.new_page()
    page.set_default_timeout(30000);monitor=BrowserDiagnostics(page,errors,expected_diagnostics)
    scan_requests=[];accepted_jobs=[]
    def local_only(request):
        if request.request.url.startswith(server.origin+'/'):request.continue_()
        else:external.append(request.request.url);request.abort()
    def record_scan(request):
        if request.url==server.origin+'/api/scan':scan_requests.append(request.post_data_json)
    context.route('**/*',local_only);page.on('request',record_scan)
    try:
        page.goto(server.origin+'/#key='+server.token)
        expect(page).to_have_title(re.compile('EZCTD.*临床 PDF 工作台'))
        expect(page.locator('.file-row')).to_have_count(1)
        expect(page.locator('#page-canvas')).to_be_visible()
        assert workspace.job_history()['jobs']==[]
        page.locator('.file-row input[type=checkbox]').check()
        def lose_submission(request):
            if accepted:
                response=request.fetch();assert response.ok,response.text()
                accepted_jobs.append(response.json()['job_id'])
            request.abort('failed')
        monitor.permit(server.origin+'/api/scan','net::ERR_FAILED',name)
        monitor.permit(server.origin+'/api/history','net::ERR_FAILED',name)
        page.route(server.origin+'/api/scan',lose_submission,times=1)
        page.route(server.origin+'/api/history',lambda request:request.abort('failed'),times=1)
        page.click('#scan-selected')
        expect(page.locator('#resume-job')).to_be_visible()
        expect(page.locator('#scan-selected')).to_be_disabled()
        page.screenshot(path=str(output/(name+'-unknown.png')),full_page=True)
        if accepted:
            assert len(accepted_jobs)==1
            wait_for_condition(page,lambda:workspace.job(accepted_jobs[0])['status'] not in ACTIVE_JOB_STATES,
                               'Accepted scan did not finish before reconnect')
        page.click('#resume-job')
        expect(page.locator('#scan-selected')).to_be_enabled(timeout=120000)
        expect(page.locator('#scan-all')).to_be_enabled()
        expect(page.locator('#resume-job')).to_be_hidden()
        expect(page.locator('#notice')).not_to_contain_text(re.compile('状态未知|尚未确认'))
        history=workspace.job_history()
        assert len(scan_requests)==1, 'Reconnect must never submit another scan'
        assert len(history['jobs'])==int(accepted)
        if accepted:
            assert history['jobs'][0]['id']==accepted_jobs[0]
            job=workspace.job(accepted_jobs[0]);assert job['total']==1 and job['status']=='COMPLETED'
            expect(page.locator('#job-results')).to_be_visible()
            expect(page.locator('#job-text')).to_contain_text('1/1')
            expect(page.locator('#issues .rule-row')).to_have_count(26)
            checks.append('lost_first_accepted_submission_and_history_responses_recover_completed_job_without_resubmission')
        else:
            expect(page.locator('#job-results')).to_be_hidden()
            checks.append('failed_first_submission_and_history_recover_empty_session_without_stuck_busy_controls')
        controls.append({'case':name,'mechanism':'abort_first_browser_submission_response_and_first_history_response',
                         'submission_reached_real_server':accepted,'accepted_job_count':len(history['jobs']),
                         'browser_scan_POST_count':len(scan_requests),'fabricated_native_payload':False})
        page.screenshot(path=str(output/(name+'-recovered.png')),full_page=True)
    except Exception as exc:
        page.screenshot(path=str(output/(name+'-failure.png')),full_page=True)
        raise RuntimeError(str(exc).replace(server.token,'<redacted-session-token>')) from None
    finally:
        context.close();server.shutdown();server.server_close();thread.join(2)
        unchanged=before==pdf_hashes(source)
        (fixture/'INPUT_INTEGRITY.json').write_text(json.dumps({'synthetic_only':True,
            'input_count':len(before),'before_sha256':before,'unchanged':unchanged},indent=2),encoding='utf-8')
    assert unchanged


def plan_source_change_case(browser,demo,output,checks,errors,external,expected_diagnostics):
    """Deliberately mutate only synthetic A; B and the other 11 inputs stay intact."""
    fixture=output/'control-plan-source-change';source=fixture/'input';source.mkdir(parents=True)
    a=source/'a-changed.pdf';b=source/'b-preserved.pdf'
    demo.make_pdf(a,pages=2,title='SYNTHETIC SOURCE CHANGE CONTROL A')
    demo.make_pdf(b,pages=2,title='SYNTHETIC SOURCE CHANGE CONTROL B')
    before=pdf_hashes(source)
    changed_bytes=a.read_bytes()+b'\n% EZCTD SYNTHETIC TEST: deliberate source identity change.\n'
    expected_after={**before,'a-changed.pdf':hashlib.sha256(changed_bytes).hexdigest()}
    mutation_performed=False;plan_id=None;eligible_before=None;eligible_after=None;response_code=None
    workspace=Workspace(source,fixture/'workspace',_default_rulepack())
    server=LocalServer(workspace);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    context=browser.new_context(viewport={'width':1500,'height':1000});page=context.new_page()
    page.set_default_timeout(30000);monitor=BrowserDiagnostics(page,errors,expected_diagnostics)
    def local_only(request):
        if request.request.url.startswith(server.origin+'/'):request.continue_()
        else:external.append(request.request.url);request.abort()
    context.route('**/*',local_only)
    try:
        page.goto(server.origin+'/#key='+server.token)
        expect(page).to_have_title(re.compile('EZCTD.*临床 PDF 工作台'))
        expect(page.locator('.file-row')).to_have_count(2)
        page.locator('.file-open[title="a-changed.pdf"]').click()
        expect(page.locator('#page-canvas')).to_be_visible()
        page.locator('#select-all').check()
        plan=start_ui_job(page,server,'#plan','plan');plan_id=plan['id'];eligible_before=plan['eligible_count']
        assert eligible_before==2 and plan['can_apply']
        expect(page.locator('#apply-plan')).to_contain_text('2 份副本')
        page.click('#close-dialog')
        # This fixture-only mutation is intentional and exactly hash-accounted;
        # unlike the UI response injection above, the native service sees it.
        a.write_bytes(changed_bytes);mutation_performed=True
        assert pdf_hashes(source)==expected_after
        page_url=server.origin+'/api/page'
        monitor.permit(page_url,'400 (Bad Request)','deliberate_synthetic_source_change_native_response')
        with page.expect_response(lambda response:response.url==page_url) as answer:
            page.click('#search-page')
        response=answer.value;assert response.status==400
        response_code=response.json().get('error_code');assert response_code=='SOURCE_CHANGED'
        expect(page.locator('#identity')).to_contain_text('文件身份已失效')
        expect(page.locator('#page-canvas')).to_be_hidden()
        open_history_job(page,plan_id)
        expect(page.locator('#dialog-rows tr').filter(has_text='a-changed.pdf').locator('td').nth(1)).to_have_text('计划失效')
        expect(page.locator('#dialog-rows tr').filter(has_text='b-preserved.pdf').locator('td').nth(1)).to_have_text('可生成副本')
        expect(page.locator('#apply-plan')).to_contain_text('1 份副本')
        expect(page.locator('#apply-plan')).to_be_enabled()
        revised=workspace.job(plan_id);eligible_after=revised['eligible_count']
        assert eligible_after==1 and revised['can_apply']
        checks.append('real_source_change_invalidates_only_affected_plan_row_and_preserves_other_eligible_entry')
        page.screenshot(path=str(output/'workbench-plan-source-invalidation.png'),full_page=True)
    except Exception as exc:
        page.screenshot(path=str(output/'workbench-plan-source-invalidation-failure.png'),full_page=True)
        raise RuntimeError(str(exc).replace(server.token,'<redacted-session-token>')) from None
    finally:
        context.close();server.shutdown();server.server_close();thread.join(2)
        after=pdf_hashes(source)
        integrity={'synthetic_only':True,'input_count':2,'deliberately_modified_input':'a-changed.pdf',
                   'preserved_input':'b-preserved.pdf','mutation':'append_exact_synthetic_PDF_comment',
                   'mutation_performed':mutation_performed,'before_sha256':before,
                   'expected_after_sha256':expected_after,'actual_after_sha256':after,
                   'matches_exact_intended_mutation':mutation_performed and after==expected_after,
                   'unmodified_input_unchanged':after['b-preserved.pdf']==before['b-preserved.pdf'],
                   'source_error_code':response_code,'plan_id':plan_id,
                   'eligible_count_before':eligible_before,'eligible_count_after':eligible_after,
                   'response_injected':False,'not_part_of_11_unchanged_input_claim':True}
        (fixture/'INPUT_INTEGRITY.json').write_text(json.dumps(integrity,indent=2),encoding='utf-8')
    assert integrity['matches_exact_intended_mutation'] and integrity['unmodified_input_unchanged']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--browser')
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    demo=load_module(root/'tools/demo/build_workbench_demo.py','demo_builder')
    report=load_module(root/'tests/cro_pdf/test_workbench.py','report_fixture')
    assets=demo.build(args.output)
    source=Path(assets['input']);workspace=Workspace(source,Path(assets['workspace']),_default_rulepack())
    before={p.relative_to(source).as_posix():sha256_file(p) for p in source.rglob('*.pdf')}
    server=LocalServer(workspace);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    failures=[];errors=[];external=[];checks=[];viewports=[];browser_version=None
    expected_diagnostics=[];source_change_diagnostics=[];controls=[]
    assets_before={name:sha256_file(root/'src/ezctd/web'/name) for name in ('app.js','index.html','style.css')}
    python_before={path.relative_to(root).as_posix():sha256_file(path) for path in sorted((root/'src/ezctd').rglob('*.py'))}
    try:
        with sync_playwright() as engine:
            options={'headless':True}
            if args.browser:options['executable_path']=args.browser
            browser=engine.chromium.launch(**options)
            browser_version=browser.version
            context=browser.new_context(viewport={'width':1500,'height':1000})
            viewports.append('1500x1000')
            page=context.new_page();page.set_default_timeout(30000)
            monitor=BrowserDiagnostics(page,errors,expected_diagnostics)
            def route(request):
                if request.request.url.startswith(server.origin+'/'):
                    request.continue_()
                else:
                    external.append(request.request.url);request.abort()
            context.route('**/*',route)
            page.goto(server.origin+'/#key='+server.token)
            expect(page).to_have_title(re.compile('EZCTD.*临床 PDF 工作台'))
            expect(page.locator('.file-row')).to_have_count(8)
            assert page.url==server.origin+'/'
            assert page.locator('vite-error-overlay, #webpack-dev-server-client-overlay, nextjs-portal').count()==0
            page.locator('.file-open').filter(has_text='m5/5.3.1.2/fasting').click()
            page.locator('#page-canvas').wait_for(state='visible')
            expect(page.locator('#page-text')).to_have_value(re.compile('12\\.50'))
            checks.append('real_pdf_page_rendered_and_text_extracted')
            page.fill('#search-query','12.50');page.click('#search-page')
            expect(page.locator('#search-count')).to_contain_text('1 处')
            checks.append('numeric_query_highlighted_with_native_coordinates')
            page.click('#next');expect(page.locator('#page-number')).to_have_value('2')
            expect(page.locator('#reader-status')).to_contain_text('×')
            expect(page.locator('#page-canvas')).to_be_visible()
            page.click('[data-tab=nav]');page.locator('.bookmark').first.click()
            expect(page.locator('#page-number')).to_have_value('1')
            checks.append('page_navigation_and_bookmark_targets')
            page.click('#show-thumbnails')
            expect(page.locator('#thumbnails .thumbnail')).to_have_count(3)
            expect(page.locator('#thumbnails img').last).to_be_visible()
            page.locator('#thumbnails .thumbnail').nth(2).click()
            expect(page.locator('#page-number')).to_have_value('3')
            expect(page.locator('#page-text')).to_have_value(re.compile('Physical page 3 / 3'))
            page.locator('.bookmark').first.click();expect(page.locator('#page-number')).to_have_value('1')
            checks.append('native_thumbnails_change_and_track_physical_page')
            page.click('#focus-mode');expect(page.locator('body')).to_have_class(re.compile(r'\breading-focus\b'))
            expect(page.locator('#page-canvas')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(args.output/'workbench-focus.png'),full_page=True)
            page.click('#focus-mode');expect(page.locator('body')).not_to_have_class(re.compile(r'\breading-focus\b'))
            checks.append('reading_focus_toggle_keeps_document_and_layout')
            page.click('#search-doc');page.wait_for_selector('.search-hit')
            assert page.locator('.search-hit').count()==3
            checks.append('full_document_search_three_pages')
            page.click('#clear-search');expect(page.locator('#search-query')).to_have_value('')
            expect(page.locator('.search-hit')).to_have_count(0);expect(page.locator('#search-more')).to_be_hidden()
            checks.append('clear_search_removes_results_and_continuation')
            page.click('[data-tab=issues]');page.fill('#node-id','5.3.1.2')
            page.select_option('#document-role','clinical-report');page.select_option('#language','zh');page.click('#save-context')
            expect(page.locator('#notice')).to_contain_text('上下文已更新')
            select_only(page,['m5/5.3.1.2/fasting'])
            selected=start_ui_job(page,server,'#scan-selected','scan')
            assert selected['total']==1 and len(selected['results'])==1
            assert selected['results'][0]['relative_path']=='m5/5.3.1.2/fasting/clinical-report.pdf'
            assert sum(file['scanned'] for file in workspace.session()['files'])==1
            expect(page.locator('#issues .rule-row')).to_have_count(26)
            page.select_option('#file-status','unscanned');expect(page.locator('.file-row')).to_have_count(7)
            page.select_option('#file-status','all');expect(page.locator('.file-row')).to_have_count(8)
            checks.append('selected_scan_only_one_pdf_and_unscanned_filter_seven')
            evaluations=selected['results'][0]['result']['rule_evaluations']
            fail_count=sum(row['status']=='FAIL' for row in evaluations);assert fail_count>0
            page.select_option('#issue-status','FAIL');expect(page.locator('#issues .rule-row')).to_have_count(fail_count)
            page.select_option('#issue-status','all');page.fill('#issue-query','6.22')
            expect(page.locator('#issues .rule-row')).to_have_count(1)
            expect(page.locator('#issues .rule-row b')).to_have_text('6.22')
            page.fill('#issue-query','');expect(page.locator('#issues .rule-row')).to_have_count(26)
            checks.append('issue_status_and_query_filters_restore_all_26_rules')
            all_scan=start_ui_job(page,server,'#scan-all','scan')
            assert all_scan['total']==8
            expect(page.locator('#job-results')).to_be_visible(timeout=120000)
            expect(page.locator('#issues .rule-row')).to_have_count(26)
            expect(page.locator('#issues .rule-row b').first).to_have_text('6.22')
            checks.append('actual_eight_pdf_scan_with_bad_and_password_inputs')
            checks.append('all_26_states_retained_with_explicit_issue_first')
            fixture=args.output/'synthetic-report.html';raw=report.report_bytes('./m5/5.3.1.2/fasting/clinical-report.pdf');fixture.write_bytes(raw)
            page.locator('#report-file').set_input_files(str(fixture))
            expect(page.locator('#notice')).to_contain_text('1 条路径候选')
            expect(page.locator('[data-tab=report]')).to_have_attribute('aria-selected', 'true')
            expect(page.locator('#report-issues')).to_contain_text('未证明')
            assert page.evaluate('window.PWNED') is None
            assert workspace.report['source_sha256']==hashlib.sha256(raw).hexdigest()
            checks.append('report_import_inert_and_bom_preserved')
            page.screenshot(path=str(args.output/'workbench-reader.png'),full_page=True)
            for text in ['m5/5.3.1.2/fasting','m2/2.5','references','certificates']:
                page.locator('.file-row').filter(has_text=text).locator('input[type=checkbox]').check()
            plan=start_ui_job(page,server,'#plan','plan')
            expect(page.locator('#apply-plan')).to_contain_text('2 份副本')
            assert sum(row.get('eligibility')=='ELIGIBLE' for row in plan['results'])==2
            assert sum(row.get('eligibility')=='BLOCKED' for row in plan['results'])==1
            assert sum(row.get('eligibility')=='NO_CHANGE_NEEDED' for row in plan['results'])==1
            page.screenshot(path=str(args.output/'workbench-plan.png'),full_page=True)
            checks.append('plan_two_eligible_one_signature_block_one_noop')
            page.click('#apply-plan');page.wait_for_selector('#task-dialog[open]',timeout=120000)
            expect(page.locator('#dialog-rows')).to_contain_text('副本已复验')
            assert page.locator('#dialog-rows tr').count()==3
            assert len(list((workspace.output/'copies').rglob('*.pdf')))==2
            checks.append('two_real_linearized_copies_published_with_proof')
            page.screenshot(path=str(args.output/'workbench-result.png'),full_page=True)
            open_history_job(page,plan['id']);expect(page.locator('#apply-plan')).to_be_hidden()
            assert workspace.job(plan['id'])['can_apply'] is False
            assert len(list((workspace.output/'copies').rglob('*.pdf')))==2
            checks.append('history_opens_consumed_plan_without_reapply')
            page.screenshot(path=str(args.output/'workbench-history-plan.png'),full_page=True)
            page.click('#close-dialog')
            select_only(page,['m5/5.3.1.2/fed','blocked/corrupt.pdf'])
            mixed=start_ui_job(page,server,'#plan','plan')
            assert mixed['status']=='COMPLETED_WITH_ERRORS'
            assert mixed['eligible_count']==1 and mixed['can_apply']
            eligible=next(row for row in mixed['results'] if row.get('eligibility')=='ELIGIBLE')
            failed=next(row for row in mixed['results'] if row['status']=='ERROR')
            expect(page.locator('#apply-plan')).to_contain_text('1 份副本')
            expect(page.locator('#apply-plan')).to_be_enabled()
            expect(page.locator('#dialog-rows')).to_contain_text('blocked/corrupt.pdf')
            page.screenshot(path=str(args.output/'workbench-mixed-plan.png'),full_page=True)
            mixed_applied=start_ui_job(page,server,'#apply-plan','apply')
            assert mixed_applied['requested_ids']==[eligible['id']]
            assert mixed_applied['status']=='COMPLETED'
            expect(page.locator('#dialog-rows')).to_contain_text('副本已复验')
            copies_before_retry=pdf_hashes(workspace.output/'copies');assert len(copies_before_retry)==3
            checks.append('mixed_valid_and_corrupt_plan_applies_only_verified_eligible_file')
            open_history_job(page,mixed['id']);expect(page.locator('#apply-plan')).to_be_hidden()
            expect(page.locator('#retry-job')).to_be_visible()
            retried=start_ui_job(page,server,'#retry-job','retry')
            assert retried['retry_of']==mixed['id'] and retried['requested_ids']==[failed['id']]
            assert retried['total']==1 and retried['kind']=='plan' and not retried['can_apply']
            assert pdf_hashes(workspace.output/'copies')==copies_before_retry
            expect(page.locator('#dialog-rows')).not_to_contain_text(eligible['relative_path'])
            expect(page.locator('#apply-plan')).to_be_hidden()
            checks.append('retry_failed_subset_excludes_success_and_preserves_published_copies')
            page.screenshot(path=str(args.output/'workbench-retry.png'),full_page=True)
            page.click('#close-dialog');page.set_viewport_size({'width':1000,'height':800})
            viewports.append('1000x800')
            page.screenshot(path=str(args.output/'workbench-1000.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert page.locator('footer').evaluate('(el) => el.getBoundingClientRect().bottom <= window.innerHeight + 1')
            checks.append('1000px_layout_no_document_overflow_and_footer_visible')
            reader_control_cases(page,server,args.output,checks,monitor,controls)
            context.close()
            extended_reader_case(browser,demo,args.output,checks,errors,external,expected_diagnostics,controls)
            submission_recovery_case(browser,demo,args.output,checks,errors,external,expected_diagnostics,controls,accepted=True)
            submission_recovery_case(browser,demo,args.output,checks,errors,external,expected_diagnostics,controls,accepted=False)
            plan_source_change_case(browser,demo,args.output,checks,errors,external,source_change_diagnostics)
            browser.close()
    except Exception as exc:
        failures.append(f'{type(exc).__name__}: {exc}'.replace(server.token, '<redacted-session-token>'))
        raise RuntimeError(failures[-1]) from None
    finally:
        server.shutdown();server.server_close();thread.join(2)
        after={p.relative_to(source).as_posix():sha256_file(p) for p in source.rglob('*.pdf')}
        assets_after={name:sha256_file(root/'src/ezctd/web'/name) for name in assets_before}
        python_after={path.relative_to(root).as_posix():sha256_file(path) for path in sorted((root/'src/ezctd').rglob('*.py'))}
        assets_unchanged=assets_before==assets_after;python_unchanged=python_before==python_after
        if not assets_unchanged:failures.append('Web assets changed during the run; this result cannot verify the final UI.')
        if not python_unchanged:failures.append('Python source changed during the run; this result cannot verify the final backend.')
        extended_evidence=args.output/'extended-reader/INPUT_INTEGRITY.json'
        extended_integrity=json.loads(extended_evidence.read_text(encoding='utf-8')) if extended_evidence.exists() else None
        recovery_integrity={path.parent.name:json.loads(path.read_text(encoding='utf-8'))
                            for path in sorted(args.output.glob('control-recovery-*/INPUT_INTEGRITY.json'))}
        source_control_evidence=args.output/'control-plan-source-change/INPUT_INTEGRITY.json'
        source_control_integrity=json.loads(source_control_evidence.read_text(encoding='utf-8')) if source_control_evidence.exists() else None
        result={'synthetic_only':True,'browser':'Chromium via Playwright','checks':checks,
                'browser_version':browser_version,'playwright_version':importlib.metadata.version('playwright'),
                'application_source_version':__version__,'application_installed_version':importlib.metadata.version('ezctd'),
                'dependency_versions':{name:importlib.metadata.version(name) for name in ('pikepdf','pypdfium2','Pillow','pytest','playwright')},
                'browser_plugin':'not available','viewports':viewports,
                'errors':errors,'external_requests':external,'failures':failures,
                'expected_injected_network_diagnostics':expected_diagnostics,'ui_control_response_cases':controls,
                'expected_deliberate_source_change_diagnostics':source_change_diagnostics,
                'inputs_unchanged':before==after,'input_count':len(before),'official_validator_run':False,
                'extended_reader_integrity':extended_integrity,'recovery_case_integrity':recovery_integrity,
                'deliberate_source_change_integrity':source_control_integrity,
                'web_asset_sha256':assets_before,'web_assets_unchanged_during_run':assets_unchanged,
                'web_asset_sha256_after':assets_after,'python_source_sha256':python_before,
                'python_source_unchanged_during_run':python_unchanged,
                'result':'PASS' if not failures and not errors and not external and before==after and assets_unchanged and python_unchanged else 'FAIL'}
        (args.output/'BROWSER_TEST_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    assert not errors and not external and before==after and assets_unchanged and python_unchanged


if __name__=='__main__':main()
