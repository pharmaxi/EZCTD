from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pikepdf
import pytest
from PIL import Image

from ezctd.assurance import assess_result
from ezctd.batch import discover_pdfs, scan_directory, render_batch_html
from ezctd.catalog import RuleCatalog
from ezctd.cli import _default_rulepack, main
from ezctd.models import PdfContext
from ezctd.page_tools import page_operation
from ezctd.pdf_observer import ExperimentalPdfObserver, _destination_zoom, _destination_valid, _path_kind
from ezctd.pdf_resources import CDE_STANDARD_FONT_NAMES, collect_page_resources
from ezctd.process_runner import run_worker
from ezctd.read_scope import ReadScope, UnsafeInputError
from ezctd.safe_io import sha256_file


def observe(path, **kwargs):
    context = PdfContext(path, path.parent, node_id='5.3.1.2', document_role='clinical-report', language='zh', **kwargs)
    return ExperimentalPdfObserver(RuleCatalog.from_json(_default_rulepack())).scan(context).to_dict()


def test_actual_page_text_query_rectangles_and_render(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'input' / '中文报告.pdf')
    before = sha256_file(source)
    result = page_operation(source, page_number=1, query='12.50')
    assert '12.50' in result['text']
    assert result['coordinate_system'] == 'PDF_CANVAS_LOWER_LEFT_LBRT'
    assert result['search_matches'][0]['char_count'] == 5
    assert len(result['search_matches'][0]['rectangles']) == 5
    for left, bottom, right, top in result['search_matches'][0]['rectangles']:
        assert 0 <= left < right <= 300 and 0 <= bottom < top <= 400
    output = tmp_path / 'preview.png'
    assert main(['render-page', str(source), '--output', str(output), '--dpi', '72']) == 0
    with Image.open(output) as image:
        assert image.size == (300, 400)
        assert image.convert('L').getextrema()[0] < 200  # Visible text, not a blank image.
    assert sha256_file(source) == before


def test_rotated_crop_and_page_label_not_confused(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'input' / 'original.pdf')
    adjusted = source.with_name('rotated.pdf')
    with pikepdf.open(source) as pdf:
        pdf.pages[0].obj.Rotate = 90
        pdf.pages[0].obj.CropBox = pikepdf.Array([10, 20, 290, 380])
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([0, pikepdf.Dictionary(S=pikepdf.Name('/r'))]))
        pdf.save(adjusted)
    result = page_operation(adjusted, page_number=1, query='Cmax')
    assert result['physical_page'] == 1 and result['page_label'] == 'i'
    assert result['rotation_degrees'] == 90
    assert result['bbox'] == [10.0, 20.0, 290.0, 380.0]
    assert result['search_matches']


@pytest.mark.parametrize('kwargs', [{'page_number':0}, {'page_number':2},
        {'page_number':1,'query':''}, {'page_number':1,'query':'x'*257},
        {'page_number':1,'render':True,'dpi':900}])
def test_invalid_page_requests_are_explicit(tmp_path, pdf_factory, kwargs):
    source = pdf_factory(tmp_path / 'input' / 'sample.pdf')
    with pytest.raises(ValueError): page_operation(source, **kwargs)


def test_outside_target_not_even_probed(tmp_path, monkeypatch):
    root = tmp_path / 'input'; root.mkdir()
    source = root / 'source.pdf'; source.write_bytes(b'not parsed')
    scope = ReadScope((root,))
    old_stat = Path.stat
    touched = []
    def guarded_stat(self, *a, **kw):
        if self == tmp_path / 'outside.pdf':
            touched.append(str(self)); raise AssertionError('Outside access')
        return old_stat(self, *a, **kw)
    monkeypatch.setattr(Path, 'stat', guarded_stat)
    assert scope.resolve_reference(source, '../outside.pdf').state == 'NOT_PROVIDED'
    assert scope.resolve_reference(source, r'\\server\share\outside.pdf').state == 'ABSOLUTE_NOT_FOLLOWED'
    assert scope.resolve_reference(source, 'file:///outside.pdf').state == 'EXTERNAL_NOT_FOLLOWED'
    assert not touched


def test_authorized_reference_root_is_separate_from_completeness(tmp_path):
    root = tmp_path / 'input'; root.mkdir(); refs = tmp_path / 'provided'; refs.mkdir()
    target = refs / 'target.pdf'; target.write_bytes(b'path-test')
    source = root / 'source.pdf'; source.write_bytes(b'path-test')
    assert ReadScope((root,)).resolve_reference(source, '../provided/target.pdf').state == 'NOT_PROVIDED'
    found = ReadScope((root,refs)).resolve_reference(source, '../provided/target.pdf')
    assert found.state == 'AVAILABLE' and found.path == target


def test_discovery_does_not_follow_directory_or_file_links(tmp_path, pdf_factory):
    root = tmp_path / 'input'; pdf_factory(root / 'a.PDF')
    outside = pdf_factory(tmp_path / 'outside' / 'secret.pdf')
    try:
        (root / 'linked.pdf').symlink_to(outside)
        (root / 'linked-dir').symlink_to(outside.parent, target_is_directory=True)
    except OSError as exc: pytest.skip(str(exc))
    files, notices = discover_pdfs(root)
    assert [p.name for p in files] == ['a.PDF']
    assert sum(n['status'] == 'LINK_NOT_FOLLOWED' for n in notices) == 2
    with pytest.raises(UnsafeInputError): ReadScope((root,)).authorize(root / 'linked.pdf')


@pytest.mark.parametrize('zoom', [None, 0])
def test_xyz_zero_and_null_keep_zoom(zoom):
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page()
        assert _destination_zoom(pdf, pikepdf.Array([page.obj, pikepdf.Name.XYZ, None, None, zoom]))[2] == 'inherit'


def test_windows_drive_is_not_uri():
    assert _path_kind(r'C:\clinical\report.pdf') == 'windows-absolute'


def test_remote_name_resolves_in_target_not_source(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'source.pdf')
    plain = pdf_factory(tmp_path / 'plain.pdf', pages=2)
    target = tmp_path / 'target.pdf'
    with pikepdf.open(plain) as pdf:
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            pikepdf.String('only-in-target'), pikepdf.Array([pdf.pages[1].obj,pikepdf.Name.XYZ,None,None,0])
        ])))
        pdf.save(target)
    with pikepdf.open(source) as pdf:
        ok, _ = _destination_valid(pdf, pikepdf.String('only-in-target'), target, ReadScope((tmp_path,)))
        assert ok is True
        assert _destination_valid(pdf, pikepdf.String('missing'), target, ReadScope((tmp_path,)))[0] is False
        assert _destination_valid(pdf, pikepdf.String('only-in-target'), target)[0] is None


def test_scan_does_not_open_outside_gotor(tmp_path, pdf_factory, monkeypatch):
    source = pdf_factory(tmp_path / 'input' / 'source.pdf')
    outside = pdf_factory(tmp_path / 'outside.pdf')
    modified = source.with_name('linked.pdf')
    with pikepdf.open(source) as pdf:
        annot = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([10,20,30,40]), A=pikepdf.Dictionary(S=pikepdf.Name.GoToR,
            F=pikepdf.String('../outside.pdf'), D=pikepdf.Array([0,pikepdf.Name.XYZ,None,None,0]))))
        pdf.pages[0].obj.Annots = pikepdf.Array([annot]); pdf.save(modified)
    old_open=pikepdf.open
    def guard(path,*a,**kw):
        if isinstance(path, (str,Path)) and Path(path) == outside:
            raise AssertionError('Unauthorized outside PDF read')
        return old_open(path,*a,**kw)
    monkeypatch.setattr(pikepdf,'open',guard)
    result=observe(modified)
    assert result['observations']['unresolved_targets']
    assert not {'6.9','6.10','6.13'} & {f['rule_id'] for f in result['findings']}


def test_exact_cde_font_policy_not_base14():
    assert 'Arial' in CDE_STANDARD_FONT_NAMES and '宋体' in CDE_STANDARD_FONT_NAMES
    assert 'Helvetica' not in CDE_STANDARD_FONT_NAMES and 'Times-Roman' not in CDE_STANDARD_FONT_NAMES


def test_form_fonts_collected_with_resource_path(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        font = pdf.pages[0].obj.Resources.Font.F1
        form=pdf.make_stream(b'BT /FX 12 Tf 10 10 Td (inside form) Tj ET')
        form.Type=pikepdf.Name.XObject;form.Subtype=pikepdf.Name.Form
        form.BBox=pikepdf.Array([0,0,100,100])
        form.Resources=pikepdf.Dictionary(Font=pikepdf.Dictionary(FX=font))
        pdf.pages[0].obj.Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Form1=form))
        pdf.pages[0].obj.Contents=pdf.make_stream(b'q /Form1 Do Q')
        inventory=collect_page_resources(pdf.pages[0])
        assert len(inventory['fonts']) == 1 and not inventory['issues']


def test_inherited_page_resources_collected(tmp_path, pdf_factory):
    source=pdf_factory(tmp_path / 'source.pdf')
    with pikepdf.open(source) as pdf:
        pdf.pages[0].obj.Parent.Resources=pdf.pages[0].obj.Resources
        del pdf.pages[0].obj.Resources
        inventory=collect_page_resources(pdf.pages[0])
        assert len(inventory['fonts'])==1 and not inventory['issues']


def test_text_extraction_failure_never_passes_6_25(tmp_path,pdf_factory,monkeypatch):
    import ezctd.pdf_observer as module
    source=pdf_factory(tmp_path / 'source.pdf')
    def fail(*a,**kw): raise RuntimeError('synthetic extraction failure')
    monkeypatch.setattr(module, '_text_by_page',fail)
    result=observe(source)
    statuses={row['rule_id']:row['status'] for row in result['rule_evaluations']}
    assert statuses['6.25']=='INDETERMINATE'
    assert '6.25' not in result['observations']['rules_evaluated']
    assert result['diagnostics']['warnings']


def test_every_rule_has_explicit_status_on_password_failure(tmp_path,pdf_factory):
    source=pdf_factory(tmp_path / 'locked.pdf', password='synthetic-password')
    result=observe(source)
    rows={r['rule_id']:r['status'] for r in result['rule_evaluations']}
    assert len(rows)==26 and rows['6.21']=='FAIL' and rows['6.25']=='NOT_RUN'


def test_known_reference_exemption_and_unknown_context_are_distinct(tmp_path,pdf_factory):
    result={'findings':[], 'observations':{},'diagnostics':{'pikepdf_open':'PASS'},
            'context':{'node_id':'5.4','language':'zh','document_role':'reference'}}
    assert {r['rule_id']:r['status'] for r in assess_result(result)['rule_evaluations']}['6.22']=='NOT_APPLICABLE'
    result['context']={}
    assert {r['rule_id']:r['status'] for r in assess_result(result)['rule_evaluations']}['6.22']=='INDETERMINATE'


def test_native_worker_error_and_timeout_are_contained(tmp_path,pdf_factory):
    source=pdf_factory(tmp_path/'source.pdf')
    request={'operation':'inspect-page','path':str(source),'page':100}
    assert run_worker(request)['worker_status']=='ERROR'
    assert run_worker(request,timeout=0.0001)['worker_status']=='TIMEOUT'
    assert run_worker({**request,'page':1})['worker_status']=='OK'


def test_20_pdf_directory_isolation_and_integrity(tmp_path,pdf_factory):
    root=tmp_path/'clinical'
    for n in range(18): pdf_factory(root/f'group{n%2}'/f'case{n}.pdf', font='Arial')
    pdf_factory(root/'locked.pdf',password='private')
    (root/'broken.pdf').write_bytes(b'%PDF- broken synthetic')
    (root/'ignore.html').write_text('not a PDF',encoding='utf-8')
    before={p.relative_to(root).as_posix():sha256_file(p) for p in root.rglob('*.pdf')}
    output=tmp_path/'reports'/'scan.json'; htmlpath=tmp_path/'reports'/'scan.html'
    assert main(['scan-directory',str(root),'--output',str(output),'--html',str(htmlpath)]) in (1,3)
    result=json.loads(output.read_text(encoding='utf-8'))
    assert result['pdf_count']==20 and result['backbone_required'] is False
    assert result['input_integrity']['unchanged']==20
    assert len(result['files'])==20 and all(len(r['rule_evaluations'])==26 for r in result['files'])
    assert result['discovery_notices'][0]['status']=='NON_PDF_NOT_SCANNED'
    assert before=={p.relative_to(root).as_posix():sha256_file(p) for p in root.rglob('*.pdf')}
    assert '无法判定' in htmlpath.read_text(encoding='utf-8')


def test_batch_failed_worker_does_not_stop_next_file(tmp_path,pdf_factory,monkeypatch):
    import ezctd.batch as batch
    root=tmp_path/'clinical';pdf_factory(root/'a.pdf');pdf_factory(root/'b.pdf')
    original=batch.run_worker
    def crash_first(request,**kwargs):
        if request['path'].endswith('a.pdf'):return {'worker_status':'CRASH_OR_PROTOCOL_ERROR','exit_code':-11}
        return original(request,**kwargs)
    monkeypatch.setattr(batch,'run_worker',crash_first)
    result=scan_directory(root,rulepack=_default_rulepack())
    assert result['files'][0]['worker_status']=='CRASH_OR_PROTOCOL_ERROR'
    assert result['files'][1]['worker_status']=='OK'
    assert result['input_integrity']['unchanged']==2


def test_context_map_exact_path_and_no_input_tree_output(tmp_path,pdf_factory):
    root=tmp_path/'clinical';pdf_factory(root/'fasting'/'report.pdf');pdf_factory(root/'fed'/'report.pdf')
    mapping=tmp_path/'map.json';mapping.write_text(json.dumps({'report.pdf':{'node_id':'5.4'}}),encoding='utf-8')
    assert main(['scan-directory',str(root),'--context-map',str(mapping),'--output',str(tmp_path/'out.json')])==2
    assert main(['scan-directory',str(root),'--output',str(root/'out.json')])==2
    assert not (root/'out.json').exists()


def test_html_escapes_paths_instead_of_executing_them():
    result={'pdf_count':1,'input_integrity':{'unchanged':1,'checked':1},'discovery_notices':[],
            'files':[{'file':'<script>alert(1)</script>.pdf','worker_status':'OK','findings':[],'rule_evaluations':[]}]}
    text=render_batch_html(result)
    assert '<script>alert' not in text and '&lt;script&gt;' in text and 'default-src' in text


def test_parent_import_does_not_load_native_engines():
    # A real fresh interpreter, not sys.modules manipulation in a loaded test process.
    import sys
    run=subprocess.run([sys.executable,'-c',
        "import sys; import ezctd.cli; assert 'pikepdf' not in sys.modules; assert 'pypdfium2' not in sys.modules"],
        capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr


def test_same_page_inspection_is_repeatable(tmp_path,pdf_factory):
    path=pdf_factory(tmp_path/'source.pdf')
    a=page_operation(path,page_number=1,query='Cmax')
    b=page_operation(path,page_number=1,query='Cmax')
    assert a==b


def test_symbolic_input_rejected_before_native_scan(tmp_path,pdf_factory):
    src=pdf_factory(tmp_path/'input'/'source.pdf');alias=tmp_path/'alias.pdf'
    try:alias.symlink_to(src)
    except OSError as exc:pytest.skip(str(exc))
    assert main(['scan-pdf',str(alias)])==2


def test_fractional_page_boxes_are_json_serializable(tmp_path,pdf_factory):
    source=pdf_factory(tmp_path/'input'/'source.pdf');altered=source.with_name('fractional.pdf')
    with pikepdf.open(source) as pdf:
        pdf.pages[0].obj.CropBox=pikepdf.Array([0.5,1.25,299.5,399.75])
        pdf.save(altered)
    result=run_worker({'operation':'scan-pdf','path':str(altered),'roots':[str(altered.parent)],
                       'rulepack':str(_default_rulepack()),'node_id':'5.3.1.2','language':'zh'})
    assert result['worker_status']=='OK'
    assert result['result']['observations']['page_boxes'][0]['CropBox']==[0.5,1.25,299.5,399.75]
