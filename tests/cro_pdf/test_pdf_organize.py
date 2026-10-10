"""Real pikepdf/PDFium organization tests using only synthetic PDF content."""
from contextlib import closing
from io import BytesIO
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium
import pytest

from ezctd.pdf_organize import (inspect_organize, organize_preview, organize_stage,
                                _mapped_visual_evidence)
from ezctd.process_runner import run_worker
from ezctd.safe_io import sha256_file


def complex_pdf(tmp_path, *, nested=False, labels=True):
    source = tmp_path / 'input' / 'complex.pdf'
    source.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.Pdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for i in range(3):
            page = pdf.add_blank_page(page_size=(300, 400))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            page.obj.Contents = pdf.make_stream(
                f'0.2 0.5 0.8 rg 24 260 90 40 re f BT /F1 12 Tf 30 320 Td (Clinical page {i + 1} Cmax {12 + i}.50) Tj ET'.encode())
            page.obj.SourceMarker = i + 1
            page.obj.CropBox = pikepdf.Array([10, 20, 285, 380])
            if i == 1:
                page.obj.Rotate = 90
        pages = [page.obj for page in pdf.pages]
        pdf.docinfo.Title = 'Synthetic source metadata must survive'
        pdf.Root.OpenAction = pikepdf.Array([pages[1], pikepdf.Name.XYZ, 30, 320, None])
        pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array([
            'analysis', pikepdf.Array([pages[2], pikepdf.Name.FitH, 320])
        ])))
        with pdf.open_outline() as outline:
            parent = pikepdf.OutlineItem('Report', pikepdf.Array([pages[0], pikepdf.Name.Fit]))
            parent.children.append(pikepdf.OutlineItem('Statistics', pikepdf.String('analysis')))
            parent.children.append(pikepdf.OutlineItem('PK', pikepdf.Array([pages[1], pikepdf.Name.Fit])))
            outline.root.append(parent)
        pages[0].Annots = pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([25, 255, 120, 280]), Border=pikepdf.Array([0, 0, 1]),
                Dest=pikepdf.String('analysis'))),
            pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([25, 290, 120, 310]), Border=pikepdf.Array([0, 0, 1]),
                A=pikepdf.Dictionary(S=pikepdf.Name.GoTo, D=pikepdf.Array([pages[1], pikepdf.Name.Fit])))),
            pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link,
                Rect=pikepdf.Array([130, 255, 180, 275]), Border=pikepdf.Array([0, 0, 0]),
                A=pikepdf.Dictionary(S=pikepdf.Name.GoToR, F='missing-external.pdf',
                                     D=pikepdf.Array([7, pikepdf.Name.Fit]))))
        ])
        if labels:
            pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
                0, pikepdf.Dictionary(S=pikepdf.Name.r),
                1, pikepdf.Dictionary(S=pikepdf.Name.D, P='A-', St=7)
            ]))
        if nested:
            root = pdf.Root.Pages
            parent = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Pages, Count=2,
                Kids=pikepdf.Array(pages[:2]), Parent=root, Rotate=270,
                MediaBox=pikepdf.Array([0, 0, 300, 400]), CropBox=pikepdf.Array([10, 20, 285, 380]),
                Resources=pages[0].Resources, VendorKeep=pikepdf.Dictionary(Note='do not remove')))
            for page in pages[:2]:
                page.Parent = parent
                for key in ('/MediaBox', '/CropBox', '/Resources'):
                    del page[key]
            root.Kids = pikepdf.Array([parent, pages[2]])
        pdf.save(source, min_version='1.7')
    return source


@pytest.mark.parametrize('nested', [False, True])
def test_reorder_rotate_reopens_and_preserves_navigation_labels_metadata(tmp_path, nested):
    source = complex_pdf(tmp_path, nested=nested)
    digest = sha256_file(source)
    inspection = inspect_organize(source, digest)
    assert inspection['eligibility'] == 'ELIGIBLE', inspection
    assert inspection['page_count'] == 3
    output = tmp_path / 'organized.pdf'
    proof = organize_stage(source, digest, output, [3, 1, 2], [90, 180, 270])
    assert proof['verification_status'] == 'VERIFIED_LOCAL_INVARIANTS'
    assert proof['semantic_graph_before'] == proof['semantic_graph_after_normalization']
    assert proof['navigation']['preserved']
    assert proof['navigation']['pdfium']['bookmark_count'] == 3
    assert proof['navigation']['pdfium']['link_count'] == 3
    assert proof['page_mapping'][0] == {'output_position': 1, 'source_page': 3,
        'rotation_delta': 270, 'source_rotation_degrees': 0, 'output_rotation_degrees': 270}
    assert len(proof['pages']) == 3
    assert all(p['pixels_equal_after_declared_rotation'] and p['text_equal'] for p in proof['pages'])
    assert sha256_file(source) == digest
    assert sha256_file(output) == proof['output_sha256']
    with pikepdf.open(output) as pdf:
        assert [p.SourceMarker for p in pdf.pages] == [3, 1, 2]
        assert [int(p.get('/Rotate', 0)) % 360 for p in pdf.pages] == [270, 0 if nested else 90, 270]
        # Destination still points at original page 2, now the third output page.
        assert pdf.Root.OpenAction[0].objgen == pdf.pages[2].obj.objgen
        assert pdf.Root.Names.Dests.Names[1][0].objgen == pdf.pages[0].obj.objgen
        assert pdf.pages[1].obj.Annots[1].A.D[0].objgen == pdf.pages[2].obj.objgen
        assert int(pdf.pages[1].obj.Annots[2].A.D[0]) == 7  # remote integer is inert and untouched
        assert str(pdf.docinfo.Title) == 'Synthetic source metadata must survive'
        if nested:
            assert str(pdf.Root.Pages.Kids[0].VendorKeep.Note) == 'do not remove'
    with closing(pdfium.PdfDocument(output)) as doc:
        assert [doc.get_page_label(i) for i in range(3)] == ['A-8', 'i', 'A-7']


@pytest.mark.parametrize('delta', [90, 180, 270])
def test_preview_is_real_pdf_bytes_with_persistent_rotation(tmp_path, delta):
    source = complex_pdf(tmp_path)
    before = sha256_file(source)
    result = organize_preview(source, before, [2, 3, 1], [0, delta, 0], page=1, dpi=72)
    assert result['source_page'] == 2 and result['output_position'] == 1
    assert result['rotation_degrees'] == (90 + delta) % 360
    assert result['source_sha256'] == before
    assert result['preview_pdf_sha256'] == result['input_sha256'] != before
    assert result['preview_only'] and result['verification_status'] == 'PREVIEW_NOT_VERIFIED'
    assert 'Clinical page 2' in result['text']
    assert result['png_base64']
    assert sorted(p.name for p in source.parent.iterdir()) == ['complex.pdf']
    assert sha256_file(source) == before


def test_preview_thumbnail_budget_and_no_label_invention(tmp_path):
    source = complex_pdf(tmp_path, labels=False)
    digest = sha256_file(source)
    thumbnail = organize_preview(source, digest, [3, 2, 1], [0, 90, 0], thumbnail=True)
    assert thumbnail['width_px'] * thumbnail['height_px'] <= 180_000
    assert 'text' not in thumbnail
    output = tmp_path / 'organized.pdf'
    organize_stage(source, digest, output, [3, 2, 1], [0, 0, 0])
    with pikepdf.open(output) as pdf:
        assert '/PageLabels' not in pdf.Root


@pytest.mark.parametrize('encoded_name', [b'/legacy', b'/Caf#e9', b'/#e7#ab#a0#e8#8a#82'])
def test_legacy_named_destination_preserves_raw_name_bytes_and_real_targets(tmp_path, encoded_name):
    seed = complex_pdf(tmp_path / 'seed')
    source = tmp_path / 'input' / 'legacy.pdf'
    source.parent.mkdir()
    name = pikepdf.Object.parse(encoded_name)
    with pikepdf.open(seed) as pdf:
        pdf.Root.Dests = pikepdf.Dictionary()
        pdf.Root.Dests[name] = pikepdf.Array([pdf.pages[0].obj, pikepdf.Name.Fit])
        pdf.pages[0].obj.Annots[0].Dest = name
        pdf.Root.Outlines.First.Dest = name
        pdf.save(source)
    digest = sha256_file(source)
    with pikepdf.open(source) as pdf:
        assert pdf.check_pdf_syntax() == []
    assert inspect_organize(source, digest)['eligibility'] == 'ELIGIBLE'
    output = tmp_path / 'organized.pdf'
    proof = organize_stage(source, digest, output, [3, 1, 2], [90, 0, 0])
    assert proof['verification_status'] == 'VERIFIED_LOCAL_INVARIANTS'
    assert proof['navigation']['preserved']
    with pikepdf.open(output) as pdf:
        assert bytes(pdf.Root.Outlines.First.Dest) == bytes(name)
        assert bytes(pdf.pages[1].obj.Annots[0].Dest) == bytes(name)
        assert pdf.Root.Dests[name][0].objgen == pdf.pages[1].obj.objgen
    assert sha256_file(source) == digest


def test_semantic_fingerprint_retains_every_non_utf8_name_byte():
    from ezctd.pdf_copy import semantic_fingerprint
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.Root.OpaqueName = pikepdf.Object.parse(b'/Caf#e9')
        original = semantic_fingerprint(pdf)
        pdf.Root.OpaqueName = pikepdf.Object.parse(b'/Caf#e8')
        assert semantic_fingerprint(pdf) != original
        pdf.Root.OpaqueName = pikepdf.Object.parse(b'/Caf#e9')
        assert semantic_fingerprint(pdf) == original


@pytest.mark.parametrize('order,rotations', [
    ([1, 1, 3], [0, 0, 0]), ([1, 2], [0, 0, 0]), ([0, 2, 3], [0, 0, 0]),
    ([True, 2, 3], [0, 0, 0]), ([1.0, 2, 3], [0, 0, 0]),
    ([1, 2, 3], [0, True, 0]), ([1, 2, 3], [0, 90.0, 0]),
    ([1, 2, 3], [0, -90, 0]), ([1, 2, 3], [0, 360, 0]), ([1, 2, 3], [90]),
])
def test_invalid_edit_never_writes(tmp_path, order, rotations):
    source = complex_pdf(tmp_path)
    output = tmp_path / 'stage.pdf'
    with pytest.raises(ValueError, match='Order|Rotations'):
        organize_stage(source, sha256_file(source), output, order, rotations)
    assert not output.exists()


def test_no_op_is_previewable_but_not_published(tmp_path):
    source = complex_pdf(tmp_path)
    digest = sha256_file(source)
    result = organize_preview(source, digest, [1, 2, 3], [0, 0, 0], page=2)
    assert 'Clinical page 2' in result['text']
    with pytest.raises(ValueError, match='No change needed'):
        organize_stage(source, digest, tmp_path / 'out.pdf', [1, 2, 3], [0, 0, 0])
    assert not (tmp_path / 'out.pdf').exists()


@pytest.mark.parametrize('signal', ['signature', 'raw_signature', 'form', 'attachment', 'integer_local',
                                     'integer_named', 'unresolved_local', 'label_unknown'])
def test_preflight_blockers_are_explicit_and_do_not_write(tmp_path, signal):
    seed = complex_pdf(tmp_path / 'seed')
    source = tmp_path / 'input' / 'blocked.pdf'
    source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        if signal == 'signature':
            pdf.Root.Signal = pikepdf.Dictionary(FT=pikepdf.Name.Sig)
        elif signal == 'form':
            pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array())
        elif signal == 'attachment':
            pdf.attachments['never-run.txt'] = b'never execute'
        elif signal == 'integer_local':
            pdf.Root.OpenAction = pikepdf.Array([0, pikepdf.Name.Fit])
        elif signal == 'integer_named':
            pdf.Root.Names.Dests.Names[1][0] = 2
        elif signal == 'unresolved_local':
            pdf.pages[0].obj.Annots[0].Dest = pikepdf.String('missing')
        elif signal == 'label_unknown':
            pdf.Root.PageLabels.Nums[1].UnknownSemantic = 'must not drop'
        pdf.save(source)
    if signal == 'raw_signature':
        source.write_bytes(source.read_bytes() + b'\n% /ByteRange historical marker\n')
    digest = sha256_file(source)
    inspected = inspect_organize(source, digest)
    assert inspected['eligibility'] == 'BLOCKED', inspected
    assert inspected['blockers']
    if signal.startswith('integer'):
        assert 'INTEGER_LOCAL_DESTINATION_NOT_SUPPORTED' in inspected['blockers']
    with pytest.raises(ValueError):
        organize_stage(source, digest, tmp_path / 'out.pdf', [3, 2, 1], [0, 0, 0])
    assert not (tmp_path / 'out.pdf').exists()
    assert sha256_file(source) == digest


@pytest.mark.parametrize('password', ['private', ''])
def test_password_and_permission_encryption_block_organization(tmp_path, pdf_factory, password):
    source = pdf_factory(tmp_path / 'input' / 'encrypted.pdf', pages=2, password=password)
    digest = sha256_file(source)
    assert inspect_organize(source, digest)['eligibility'] == 'BLOCKED'
    with pytest.raises((ValueError, pikepdf.PasswordError)):
        organize_stage(source, digest, tmp_path / 'out.pdf', [2, 1], [0, 0])
    assert not (tmp_path / 'out.pdf').exists()


def test_changed_source_is_rejected_before_preview_or_stage(tmp_path):
    source = complex_pdf(tmp_path)
    digest = sha256_file(source)
    source.write_bytes(source.read_bytes() + b'\n% deliberate source change\n')
    for operation in (
        lambda: inspect_organize(source, digest),
        lambda: organize_preview(source, digest, [3, 2, 1], [0, 0, 0]),
        lambda: organize_stage(source, digest, tmp_path / 'out.pdf', [3, 2, 1], [0, 0, 0]),
    ):
        with pytest.raises(ValueError, match='changed'):
            operation()
    assert not (tmp_path / 'out.pdf').exists()


def test_source_change_during_real_verification_discards_verified_bytes(tmp_path, monkeypatch):
    import ezctd.pdf_organize as native
    source = complex_pdf(tmp_path)
    expected = sha256_file(source)
    actual = native._mapped_visual_evidence

    def verify_then_change(*args, **kwargs):
        result = actual(*args, **kwargs)
        source.write_bytes(source.read_bytes() + b'\n% changed at publication boundary\n')
        return result

    monkeypatch.setattr(native, '_mapped_visual_evidence', verify_then_change)
    with pytest.raises(ValueError, match='changed during organize verification'):
        organize_stage(source, expected, tmp_path / 'out.pdf', [2, 1, 3], [0, 90, 0])
    assert not (tmp_path / 'out.pdf').exists()


def test_declared_reorder_and_rotation_can_be_reversed_without_losing_content(tmp_path):
    from ezctd.pdf_copy import _visual_evidence
    source = complex_pdf(tmp_path, nested=True)
    first_dir = tmp_path / 'first'
    first_dir.mkdir()
    first = first_dir / 'organized.pdf'
    organize_stage(source, sha256_file(source), first, [3, 1, 2], [90, 180, 270])
    # In the second session deltas are indexed by its own source pages.
    restored = tmp_path / 'restored.pdf'
    proof = organize_stage(first, sha256_file(first), restored, [2, 3, 1], [90, 270, 180])
    assert len(_visual_evidence(source.read_bytes(), restored.read_bytes())) == 3
    assert proof['navigation']['preserved']


@pytest.mark.parametrize('annotation_flags', [0, 16])
def test_visible_annotation_and_no_rotate_flag_survive_persistent_page_rotation(tmp_path, annotation_flags):
    seed = complex_pdf(tmp_path / 'seed')
    source = tmp_path / 'input' / 'annotated.pdf'
    source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        appearance = pdf.make_stream(b'1 0 0 rg 0 0 60 25 re f 0 0 1 rg 5 5 20 10 re f')
        appearance.Type = pikepdf.Name.XObject
        appearance.Subtype = pikepdf.Name.Form
        appearance.BBox = pikepdf.Array([0, 0, 60, 25])
        appearance.Resources = pikepdf.Dictionary()
        annotation = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
            Subtype=pikepdf.Name.Stamp, Rect=pikepdf.Array([90, 110, 150, 135]),
            F=annotation_flags, AP=pikepdf.Dictionary(N=appearance)))
        pdf.pages[0].obj.Annots.append(annotation)
        # Fractional crop coordinates exercise rotation/dimension rounding.
        pdf.pages[0].obj.CropBox = pikepdf.Array([10.25, 20.125, 284.75, 379.875])
        pdf.pages[0].obj.Rotate = 270
        pdf.save(source)
    output = tmp_path / 'organized.pdf'
    proof = organize_stage(source, sha256_file(source), output, [2, 3, 1], [180, 0, 0])
    assert proof['pages'][2]['output_rotation_degrees'] == 90
    assert proof['pages'][2]['pixels_equal_after_declared_rotation']
    assert proof['pages'][2]['expected_pixel_transform'] == 'SOURCE_PDFIUM_PERSISTENT_ROTATION'
    with pikepdf.open(output) as pdf:
        assert int(pdf.pages[2].obj.Annots[-1].F) == annotation_flags
        assert pdf.pages[2].obj.Annots[-1].AP.N.read_bytes() == b'1 0 0 rg 0 0 60 25 re f 0 0 1 rg 5 5 20 10 re f'


@pytest.mark.parametrize('label_style', ['/A', '/r'])
def test_huge_native_page_label_is_blocked_before_render(tmp_path, label_style):
    seed = complex_pdf(tmp_path / 'seed')
    source = tmp_path / 'input' / 'label.pdf'
    source.parent.mkdir()
    with pikepdf.open(seed) as pdf:
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
            0, pikepdf.Dictionary(S=pikepdf.Name(label_style), St=1_000_000_000)]))
        pdf.save(source)
    result = inspect_organize(source, sha256_file(source))
    assert result['eligibility'] == 'BLOCKED'
    assert 'PAGE_LABEL_TEXT_LIMIT' in result['blockers']


@pytest.mark.parametrize('target_type', ['existing', 'input_tree', 'input_itself'])
def test_stage_cannot_overwrite_or_pollute_input_tree(tmp_path, target_type):
    source = complex_pdf(tmp_path)
    digest = sha256_file(source)
    output = {'existing': tmp_path / 'out.pdf', 'input_tree': source.parent / 'new.pdf',
              'input_itself': source}[target_type]
    if target_type == 'existing':
        output.write_bytes(b'existing user file')
    with pytest.raises(ValueError):
        organize_stage(source, digest, output, [3, 2, 1], [0, 0, 0])
    if target_type == 'existing':
        assert output.read_bytes() == b'existing user file'
    assert sha256_file(source) == digest


@pytest.mark.parametrize('damage', ['metadata', 'content', 'link_target', 'label', 'rotation', 'page_box'])
def test_real_output_corruption_fails_operation_specific_verification(tmp_path, monkeypatch, damage):
    import ezctd.pdf_organize as native
    source = complex_pdf(tmp_path)
    digest = sha256_file(source)
    actual = native._serialize_edit

    def damaged(*args, **kwargs):
        changed = actual(*args, **kwargs)
        with pikepdf.open(BytesIO(changed)) as pdf:
            if damage == 'metadata':
                pdf.docinfo.Title = 'undisclosed modification'
            elif damage == 'content':
                pdf.pages[0].obj.Contents = pdf.make_stream(b'')
            elif damage == 'link_target':
                pdf.pages[1].obj.Annots[1].A.D[0] = pdf.pages[0].obj
            elif damage == 'label':
                pdf.Root.PageLabels.Nums[1].P = 'wrong'
            elif damage == 'rotation':
                pdf.pages[0].obj.Rotate = 180
            elif damage == 'page_box':
                pdf.pages[0].obj.CropBox = pikepdf.Array([0, 0, 300, 400])
            buffer = BytesIO()
            pdf.save(buffer, fix_metadata_version=False)
            return buffer.getvalue()

    monkeypatch.setattr(native, '_serialize_edit', damaged)
    with pytest.raises(ValueError, match='graph|navigation|label|rotation'):
        organize_stage(source, digest, tmp_path / 'out.pdf', [3, 1, 2], [90, 0, 0])
    assert not (tmp_path / 'out.pdf').exists()
    assert sha256_file(source) == digest


def test_mapped_visual_check_detects_wrong_source_page_even_with_equal_page_count(tmp_path, pdf_factory):
    source = complex_pdf(tmp_path)
    changed = pdf_factory(tmp_path / 'other' / 'wrong.pdf', pages=3, text='Different Clinical value')
    with pytest.raises(ValueError):
        _mapped_visual_evidence(source.read_bytes(), changed.read_bytes(), [3, 2, 1], [0, 0, 0])


def test_all_worker_routes_use_actual_native_organization(tmp_path):
    source = complex_pdf(tmp_path)
    base = {'path': str(source), 'expected_sha256': sha256_file(source)}
    inspected = run_worker({**base, 'operation': 'inspect-organize'})
    assert inspected['worker_status'] == 'OK', inspected
    assert inspected['result']['eligibility'] == 'ELIGIBLE'
    edit = {**base, 'order': [2, 1, 3], 'rotations': [90, 0, 0]}
    preview = run_worker({**edit, 'operation': 'organize-preview', 'page': 1, 'thumbnail': True})
    assert preview['worker_status'] == 'OK', preview
    assert preview['result']['source_page'] == 2
    output = tmp_path / 'worker-stage.pdf'
    staged = run_worker({**edit, 'operation': 'organize-stage', 'stage_path': str(output)}, timeout=60)
    assert staged['worker_status'] == 'OK', staged
    assert staged['result']['output_sha256'] == sha256_file(output)
    assert staged['result']['order'] == edit['order']
    assert staged['result']['rotations'] == edit['rotations']
