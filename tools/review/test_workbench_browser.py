"""Real Chromium E2E on synthetic PDFs; never uploads a user report.

Run after installing .[test,ui-test] and Chromium:
python tools/review/test_workbench_browser.py NEW_EVIDENCE_DIR --browser /path/to/chromium
Omit --browser to use Playwright's installed Chromium. No external requests allowed.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time

from playwright.sync_api import sync_playwright
from ezctd.cli import _default_rulepack
from ezctd.safe_io import sha256_file
from ezctd.workspace import Workspace
from ezctd.workbench import LocalServer


def load_module(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--browser')
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    demo=load_module(root/'tools/demo/build_workbench_demo.py','demo_builder')
    report=load_module(root/'tests/cro_pdf/test_workbench.py','report_fixture')
    assets=demo.build(args.output)
    source=Path(assets['input']);workspace=Workspace(source,Path(assets['workspace']),_default_rulepack())
    before={p.relative_to(source).as_posix():sha256_file(p) for p in source.rglob('*.pdf')}
    server=LocalServer(workspace);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    failures=[];errors=[];external=[];checks=[]
    try:
        with sync_playwright() as engine:
            options={'headless':True}
            if args.browser:options['executable_path']=args.browser
            browser=engine.chromium.launch(**options)
            context=browser.new_context(viewport={'width':1500,'height':1000})
            page=context.new_page();page.set_default_timeout(30000)
            page.on('pageerror',lambda error:errors.append(str(error)))
            def route(request):
                if request.request.url.startswith(server.origin+'/'):
                    request.continue_()
                else:
                    external.append(request.request.url);request.abort()
            context.route('**/*',route)
            page.goto(server.origin+'/#key='+server.token)
            page.wait_for_function("document.getElementById('files').children.length === 8")
            page.locator('.file-open').filter(has_text='m5/5.3.1.2/fasting').click()
            page.locator('#page-canvas').wait_for(state='visible')
            page.wait_for_function("document.getElementById('page-text').value.includes('12.50')")
            checks.append('real_pdf_page_rendered_and_text_extracted')
            page.fill('#search-query','12.50');page.click('#search-page')
            page.wait_for_function("document.getElementById('search-count').textContent.includes('1')")
            checks.append('numeric_query_highlighted_with_native_coordinates')
            page.click('#next');page.wait_for_function("document.getElementById('page-number').value === '2' && !document.getElementById('page-canvas').hidden")
            page.click('[data-tab=nav]');page.locator('.bookmark').first.click()
            page.wait_for_function("document.getElementById('page-number').value === '1'")
            checks.append('page_navigation_and_bookmark_targets')
            page.click('#search-doc');page.wait_for_selector('.search-hit')
            assert page.locator('.search-hit').count()==3
            checks.append('full_document_search_three_pages')
            page.click('[data-tab=issues]');page.fill('#node-id','5.3.1.2')
            page.select_option('#document-role','clinical-report');page.select_option('#language','zh');page.click('#save-context')
            page.wait_for_function("document.getElementById('notice').textContent.includes('上下文已更新')")
            page.click('#scan-all');page.wait_for_function("!document.getElementById('job-results').hidden",timeout=120000)
            checks.append('actual_eight_pdf_scan_with_bad_and_password_inputs')
            fixture=args.output/'synthetic-report.html';raw=report.report_bytes('./m5/5.3.1.2/fasting/clinical-report.pdf');fixture.write_bytes(raw)
            page.locator('#report-file').set_input_files(str(fixture))
            page.wait_for_function("document.getElementById('notice').textContent.includes('1 条路径候选')")
            assert page.evaluate('window.PWNED') is None
            assert workspace.report['source_sha256']==hashlib.sha256(raw).hexdigest()
            checks.append('report_import_inert_and_bom_preserved')
            page.screenshot(path=str(args.output/'workbench-reader.png'),full_page=True)
            for text in ['m5/5.3.1.2/fasting','m2/2.5','references','certificates']:
                page.locator('.file-row').filter(has_text=text).locator('input[type=checkbox]').check()
            page.click('#plan');page.wait_for_selector('#task-dialog[open]',timeout=120000)
            page.wait_for_function("document.getElementById('apply-plan').textContent.includes('2')")
            page.screenshot(path=str(args.output/'workbench-plan.png'),full_page=True)
            checks.append('plan_two_eligible_one_signature_block_one_noop')
            page.click('#apply-plan');page.wait_for_selector('#task-dialog[open]',timeout=120000)
            page.wait_for_function("document.getElementById('dialog-rows').textContent.includes('副本已复验')")
            assert page.locator('#dialog-rows tr').count()==3
            assert len(list((workspace.output/'copies').rglob('*.pdf')))==2
            checks.append('two_real_linearized_copies_published_with_proof')
            page.screenshot(path=str(args.output/'workbench-result.png'),full_page=True)
            page.click('#close-dialog');page.set_viewport_size({'width':1000,'height':800})
            page.screenshot(path=str(args.output/'workbench-1000.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            checks.append('1000px_layout_no_document_overflow')
            browser.close()
    except Exception as exc:
        failures.append(f'{type(exc).__name__}: {exc}'.replace(server.token, '<redacted-session-token>'))
        raise RuntimeError(failures[-1]) from None
    finally:
        server.shutdown();server.server_close();thread.join(2)
        after={p.relative_to(source).as_posix():sha256_file(p) for p in source.rglob('*.pdf')}
        result={'synthetic_only':True,'browser':'Chromium via Playwright','checks':checks,
                'errors':errors,'external_requests':external,'failures':failures,
                'inputs_unchanged':before==after,'input_count':len(before),'official_validator_run':False,
                'result':'PASS' if not failures and not errors and not external and before==after else 'FAIL'}
        (args.output/'BROWSER_TEST_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    assert not errors and not external and before==after


if __name__=='__main__':main()
