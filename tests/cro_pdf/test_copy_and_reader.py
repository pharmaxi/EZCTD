from contextlib import closing
import json
from pathlib import Path
import threading
import time

import pikepdf
import pytest

from ezctd.copy_service import inspect_linearization, linearize_copy
from ezctd.pdf_copy import inspect_copy, linearize_stage, semantic_fingerprint, _visual_evidence
from ezctd.page_tools import page_operation
from ezctd.process_runner import run_worker
from ezctd.reader import navigation, search_document
from ezctd.safe_io import sha256_file


def test_native_copy_preserves_all_pages_and_graph(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'source.pdf', pages=3, bookmark=True)
    digest = sha256_file(source); output = tmp_path/'out'/'source.pdf'
    result = linearize_copy(source, output, roots=(source.parent,), expected=digest)
    assert result['verification_status'] == 'VERIFIED_LOCAL_INVARIANTS'
    assert len(result['pages']) == 3 and all(p['pixels_equal'] and p['text_equal'] for p in result['pages'])
    assert result['semantic_graph_before'] == result['semantic_graph_after']
    assert sha256_file(source) == digest
    assert json.loads(output.with_name(output.name+'.ezctd.json').read_text(encoding='utf-8')) == result
    with pikepdf.open(output) as pdf:
        assert pdf.is_linearized and pdf.check_linearization()
        assert list(pdf.open_outline().root)[0].title == 'Clinical section'


def test_copy_idempotence_means_skip_not_repeat_rewrite(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'a.pdf', linearize=True)
    before = sha256_file(source)
    assert inspect_copy(source, before)['eligibility'] == 'NO_CHANGE_NEEDED'
    with pytest.raises(ValueError, match='No change needed'):
        linearize_stage(source, before, tmp_path/'stage.pdf')
    assert not (tmp_path/'stage.pdf').exists()


@pytest.mark.parametrize('signal', ['sig', 'byterange', 'docmdp', 'form', 'js', 'attachment'])
def test_structural_blockers_never_write(tmp_path, pdf_factory, signal):
    seed = pdf_factory(tmp_path/'seed'/'x.pdf')
    source = tmp_path/'input'/'source.pdf'; source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        if signal == 'sig': pdf.Root.Guard = pikepdf.Dictionary(FT=pikepdf.Name.Sig)
        if signal == 'byterange': pdf.Root.Guard = pikepdf.Dictionary(ByteRange=pikepdf.Array([0, 12, 22, 100]))
        if signal == 'docmdp': pdf.Root.Perms = pikepdf.Dictionary(DocMDP=pikepdf.Dictionary())
        if signal == 'form': pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
        if signal == 'js': pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS='app.alert(1)')
        if signal == 'attachment': pdf.attachments['synthetic.txt'] = b'not executed'
        pdf.save(source)
    before = sha256_file(source)
    assert inspect_copy(source, before)['eligibility'] == 'BLOCKED'
    with pytest.raises((ValueError, RuntimeError)):
        linearize_copy(source, tmp_path/'out.pdf', roots=(source.parent,), expected=before)
    assert not (tmp_path/'out.pdf').exists() and sha256_file(source) == before


def test_password_file_is_blocked(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf', password='private')
    result = inspect_linearization(source, roots=(source.parent,), expected=sha256_file(source))
    assert result['eligibility'] == 'BLOCKED' and result['blockers'] == ['PASSWORD_REQUIRED']


def test_permission_only_encryption_is_not_silently_removed(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf', password='')
    result = inspect_copy(source, sha256_file(source))
    assert result['eligibility'] == 'BLOCKED'
    assert 'ENCRYPTED_OR_PERMISSION_RESTRICTED' in result['blockers']


def test_source_change_rejects_plan(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf')
    digest = sha256_file(source)
    source.write_bytes(source.read_bytes()+b'\n%changed')
    with pytest.raises(ValueError, match='changed'):
        linearize_copy(source, tmp_path/'out.pdf', roots=(source.parent,), expected=digest)
    assert not (tmp_path/'out.pdf').exists()


@pytest.mark.parametrize('collision', ['output', 'proof', 'same_input'])
def test_no_output_collision_can_overwrite(tmp_path, pdf_factory, collision):
    source = pdf_factory(tmp_path/'input'/'x.pdf'); digest = sha256_file(source)
    output = source if collision == 'same_input' else tmp_path/'out.pdf'
    existing = output if collision == 'output' else output.with_name(output.name+'.ezctd.json')
    if collision != 'same_input': existing.write_bytes(b'existing user file')
    with pytest.raises(ValueError):
        linearize_copy(source, output, roots=(source.parent,), expected=digest)
    assert sha256_file(source) == digest
    if collision != 'same_input': assert existing.read_bytes() == b'existing user file'


def test_proof_failure_rolls_back_only_new_pdf(tmp_path, pdf_factory, monkeypatch):
    import ezctd.copy_service as service
    source = pdf_factory(tmp_path/'input'/'x.pdf'); output = tmp_path/'out.pdf'
    def failed(*a, **kw): raise OSError('synthetic proof disk failure')
    monkeypatch.setattr(service, 'write_new_text', failed)
    with pytest.raises(OSError): service.linearize_copy(source, output, roots=(source.parent,), expected=sha256_file(source))
    assert not output.exists()
    assert source.exists()


def test_cancelled_before_worker_produces_no_copy(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf'); event = threading.Event(); event.set()
    with pytest.raises(RuntimeError, match='Cancelled'):
        linearize_copy(source, tmp_path/'out.pdf', roots=(source.parent,), expected=sha256_file(source), cancel_event=event)
    assert not (tmp_path/'out.pdf').exists()


def test_cancel_running_native_worker(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf', pages=50)
    event = threading.Event(); timer = threading.Timer(.02, event.set); timer.start()
    result = run_worker({'operation':'search-document', 'path':str(source),
                         'expected_sha256':sha256_file(source),'query':'Clinical'}, cancel_event=event)
    timer.join()
    assert result['worker_status'] == 'CANCELLED'


def test_semantic_fingerprint_catches_hidden_metadata_change(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf')
    with pikepdf.open(source) as pdf:
        first = semantic_fingerprint(pdf)
        pdf.docinfo['/ClinicalTest'] = 'changed without pixel change'
        assert first != semantic_fingerprint(pdf)


def test_pixel_or_text_difference_rejected(tmp_path, pdf_factory):
    a = pdf_factory(tmp_path/'a'/'x.pdf',text='Cmax 12.50')
    b = pdf_factory(tmp_path/'b'/'x.pdf',text='Cmax 99.90')
    with pytest.raises(ValueError, match='text changed'):
        _visual_evidence(a.read_bytes(), b.read_bytes())


def test_native_navigation_and_full_document_search(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path/'input'/'x.pdf', pages=3, bookmark=True)
    nav = navigation(source,sha256_file(source))
    assert nav['bookmarks'][0]['physical_page'] == 1
    result = search_document(source,sha256_file(source),'12.50')
    assert result['pages_scanned'] == 3 and len(result['matches']) == 3 and not result['truncated']


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_native_pixel_rectangles_follow_rotation_and_crop(tmp_path, pdf_factory, rotation):
    seed = pdf_factory(tmp_path/'seed'/'x.pdf')
    source=tmp_path/'input'/'x.pdf';source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        pdf.pages[0].obj.CropBox = pikepdf.Array([10, 20, 280, 380])
        pdf.pages[0].obj.Rotate = rotation
        pdf.save(source)
    result=page_operation(source,page_number=1,query='12.50',render=True,include_text=True)
    assert result['text'] and result['search_matches']
    for rect in result['search_matches'][0]['rectangles_px']:
        assert 0 <= rect[0] < rect[2] <= result['width_px']
        assert 0 <= rect[1] < rect[3] <= result['height_px']


def test_worker_parent_stays_free_of_native_imports():
    import subprocess,sys
    p=subprocess.run([sys.executable,'-c',"import sys; import ezctd.workspace, ezctd.workbench; assert 'pikepdf' not in sys.modules; assert 'pypdfium2' not in sys.modules"],capture_output=True,text=True,timeout=15)
    assert p.returncode == 0,p.stderr


def test_bundled_rulepack_is_byte_identical_to_source():
    import ezctd
    root=Path(__file__).resolve().parents[2]
    official=root/'rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json'
    bundled=Path(ezctd.__file__).parent/'data/cde_ectd_v1_1.json'
    assert official.read_bytes()==bundled.read_bytes()


def test_cli_copy_requires_approval_and_frozen_identity(tmp_path,pdf_factory):
    from ezctd.cli import main
    source=pdf_factory(tmp_path/'input'/'x.pdf');expected=sha256_file(source)
    args=['linearize-copy',str(source),'--output',str(tmp_path/'out.pdf'),'--expected-sha256',expected]
    assert main(args)==2 and not (tmp_path/'out.pdf').exists()
    assert main([*args,'--approve'])==0
    assert sha256_file(source)==expected


def test_copy_preserves_link_annotation_and_metadata(tmp_path,pdf_factory):
    seed=pdf_factory(tmp_path/'seed'/'x.pdf');source=tmp_path/'input'/'x.pdf';source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        annotation=pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,Subtype=pikepdf.Name.Link,
            Rect=pikepdf.Array([10,20,30,40]),A=pikepdf.Dictionary(S=pikepdf.Name.URI,URI='https://example.invalid/reference')))
        pdf.pages[0].obj.Annots=pikepdf.Array([annotation])
        pdf.docinfo['/Title']='Synthetic metadata must survive'
        pdf.save(source)
    output=tmp_path/'out.pdf'
    proof=linearize_copy(source,output,roots=(source.parent,),expected=sha256_file(source))
    with pikepdf.open(output) as pdf:
        assert str(pdf.pages[0].obj.Annots[0].A.URI)=='https://example.invalid/reference'
        assert str(pdf.docinfo.Title)=='Synthetic metadata must survive'
    assert proof['semantic_graph_before']==proof['semantic_graph_after']


def test_raw_prior_revision_signature_marker_blocks(tmp_path,pdf_factory):
    source=pdf_factory(tmp_path/'input'/'x.pdf')
    source.write_bytes(source.read_bytes()+b'\n% historical /ByteRange [0 10 20 30]\n')
    result=inspect_copy(source,sha256_file(source))
    assert result['eligibility']=='BLOCKED'
    assert 'SIGNATURE_OR_PRIOR_REVISION_BYTE_SIGNAL' in result['blockers']
