"""Reader regressions using synthetic PDFs; no clinical input or network access."""
import base64
from contextlib import closing
from io import BytesIO
import math

import pikepdf
from PIL import Image
import pypdfium2 as pdfium
import pytest

import ezctd.reader as reader
from ezctd.page_tools import MAX_PIXELS, _render_scale, page_operation
from ezctd.safe_io import sha256_file


def _document(path, pages):
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.Pdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for lines in pages:
            page = pdf.add_blank_page(page_size=(600, 800))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            escaped = [line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') for line in lines]
            stream = 'BT /F1 9 Tf 12 TL 20 780 Td\n' + '\n'.join(f'({line}) Tj T*' for line in escaped) + '\nET'
            page.obj.Contents = pdf.make_stream(stream.encode('ascii'))
        pdf.save(path)
    return path


def test_huge_page_adapts_resolution_and_preserves_all_four_edges(tmp_path):
    source = tmp_path / 'oversized.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(12000, 9000))
        # Four different corner squares expose whole-page clipping or stretching.
        page.obj.Contents = pdf.make_stream(
            b'1 0 0 rg 0 0 1200 900 re f '
            b'0 1 0 rg 10800 0 1200 900 re f '
            b'0 0 1 rg 0 8100 1200 900 re f '
            b'0 0 0 rg 10800 8100 1200 900 re f')
        pdf.save(source)
    digest = sha256_file(source)
    result = page_operation(source, page_number=1, render=True, dpi=120)
    assert result['requested_dpi'] == 120
    assert 0 < result['dpi'] == result['effective_dpi'] < 36
    assert result['resolution_reduced']
    assert result['resolution_state'] == 'REDUCED_TO_PIXEL_LIMIT'
    assert result['width_px'] * result['height_px'] <= MAX_PIXELS
    assert result['width_px'] / result['height_px'] == pytest.approx(4 / 3, abs=.001)
    assert result['render_limits'] == {'max_pixels': MAX_PIXELS, 'full_page': True}
    with Image.open(BytesIO(base64.b64decode(result['png_base64']))) as image:
        assert image.size == (result['width_px'], result['height_px'])
        w, h = image.size
        assert image.getpixel((w // 20, h // 20))[:3] == (0, 0, 255)
        assert image.getpixel((19 * w // 20, h // 20))[:3] == (0, 0, 0)
        assert image.getpixel((w // 20, 19 * h // 20))[:3] == (255, 0, 0)
        assert image.getpixel((19 * w // 20, 19 * h // 20))[:3] == (0, 255, 0)
    assert sha256_file(source) == digest


def test_thumbnail_budget_and_normal_requested_resolution(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'source.pdf')
    normal = page_operation(source, page_number=1, render=True, dpi=120)
    assert normal['dpi'] == 120 and not normal['resolution_reduced']
    thumbnail = page_operation(source, page_number=1, render=True, dpi=36, max_pixels=180000)
    assert thumbnail['width_px'] * thumbnail['height_px'] <= 180000
    assert thumbnail['physical_page'] == 1 and 'text' not in thumbnail


@pytest.mark.parametrize('width,height,budget', [(934000000, 1, 180000), (1, 934000000, 180000),
                                               (799.99, 1199.99, 180000), (600, 800, 1)])
def test_render_budget_handles_rounding_and_extreme_aspect_ratio(width, height, budget):
    scale = _render_scale(width, height, 300, budget)
    assert 0 < scale <= 300 / 72
    assert 0 < math.ceil(width * scale) * math.ceil(height * scale) <= budget


@pytest.mark.parametrize('width,height', [(0, 10), (-1, 10), (float('inf'), 10), (10, float('nan'))])
def test_invalid_page_dimensions_are_rejected_before_allocation(width, height):
    with pytest.raises(ValueError, match='Invalid page dimensions'):
        _render_scale(width, height, 120, MAX_PIXELS)


@pytest.mark.parametrize('budget', [0, MAX_PIXELS + 1, 1.5, True])
def test_invalid_thumbnail_budget_cannot_expand_allocation(tmp_path, pdf_factory, budget):
    source = pdf_factory(tmp_path / 'source.pdf')
    with pytest.raises(ValueError, match='Pixel limit'):
        page_operation(source, page_number=1, render=True, max_pixels=budget)


def test_search_snippet_contains_late_match_and_uses_native_character_range(tmp_path):
    source = _document(tmp_path / 'long-page.pdf', [
        ['Background paragraph with a deliberately long prefix.'] * 24
        + ['Outcome: UNIQUE_ENDPOINT is reported here.', 'Following context is retained.']])
    digest = sha256_file(source)
    result = reader.search_document(source, digest, 'UNIQUE_ENDPOINT')
    item = result['matches'][0]
    assert item['char_index'] > 600 and item['snippet_char_index'] > 0
    assert 'UNIQUE_ENDPOINT' in item['snippet'] and 'Following context' in item['snippet']
    assert item['snippet_coordinate_system'] == 'PDFIUM_CHARACTER_INDEX'
    with closing(pdfium.PdfDocument(source.read_bytes())) as doc, closing(doc[0]) as page:
        with closing(page.get_textpage()) as text, closing(text.search('UNIQUE_ENDPOINT')) as search:
            assert search.get_next() == (item['char_index'], item['char_count'])
            assert text.get_text_range(item['snippet_char_index'], item['snippet_char_count'], errors='strict') == item['snippet']
    assert result['results_complete'] and sha256_file(source) == digest


def test_search_continuation_does_not_skip_pages_or_claim_earlier_coverage(tmp_path):
    source = _document(tmp_path / 'chunks.pdf', [['target first'], [], ['target third'], ['target fourth']])
    digest = sha256_file(source)
    first = reader.search_document(source, digest, 'target', page_limit=2)
    assert (first['start_page'], first['last_page_visited'], first['next_page']) == (1, 2, 3)
    assert first['pages_scanned'] == 2 and first['pages_without_text'] == [2]
    assert first['batch_complete'] and not first['page_coverage_complete']
    assert first['truncated'] and 'PAGE_BATCH_LIMIT' in first['limit_reasons']
    second = reader.search_document(source, digest, 'target', start_page=first['next_page'], page_limit=2)
    assert (second['start_page'], second['last_page_visited'], second['next_page']) == (3, 4, None)
    assert second['batch_complete'] and not second['results_complete']
    assert 'EARLIER_PAGES_NOT_IN_BATCH' in second['limit_reasons']
    assert [m['physical_page'] for r in (first, second) for m in r['matches']] == [1, 3, 4]
    assert sha256_file(source) == digest


def test_image_only_page_is_explicitly_no_text_without_claiming_ocr(tmp_path):
    source = tmp_path / 'image-only.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(600, 800))
        bitmap = pdf.make_stream(b'\x30\x60\x90')
        bitmap.Type, bitmap.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        bitmap.Width, bitmap.Height, bitmap.BitsPerComponent = 1, 1, 8
        bitmap.ColorSpace = pikepdf.Name.DeviceRGB
        page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im1=bitmap))
        page.obj.Contents = pdf.make_stream(b'q 600 0 0 800 0 0 cm /Im1 Do Q')
        pdf.save(source)
    result = reader.search_document(source, sha256_file(source), 'Cmax')
    assert result['matches'] == [] and result['pages_without_text'] == [1]
    assert result['page_coverage_complete'] and result['results_complete']
    assert 'OCR not performed' in result['search_scope']


@pytest.mark.parametrize('occurrences,exact', [(500, True), (501, False)])
def test_per_page_match_cap_is_an_explicit_lower_bound(tmp_path, occurrences, exact):
    lines = ['needle ' * 10] * 50 + (['needle'] if occurrences == 501 else [])
    source = _document(tmp_path / 'repeated.pdf', [lines])
    result = reader.search_document(source, sha256_file(source), 'needle')
    item = result['matches'][0]
    assert item['hit_count'] == 500 and item['hit_count_exact'] is exact
    assert item['hit_count_lower_bound'] == occurrences
    assert result['page_coverage_complete']
    assert result['results_complete'] is exact and result['truncated'] is not exact
    assert result['match_count_truncated_pages'] == ([] if exact else [1])


def test_matching_page_cap_returns_next_unvisited_page(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'MAX_SEARCH_HIT_PAGES', 2)
    source = _document(tmp_path / 'many-hits.pdf', [['target'], ['target'], ['target']])
    digest = sha256_file(source)
    first = reader.search_document(source, digest, 'target')
    assert first['next_page'] == 3 and first['pages_scanned'] == 2
    assert 'MATCH_PAGE_LIMIT' in first['limit_reasons']
    second = reader.search_document(source, digest, 'target', start_page=3)
    assert second['matches'][0]['physical_page'] == 3 and second['next_page'] is None


def test_text_limit_preserves_following_results_but_marks_missing_page(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'MAX_TEXT_CHARS', 20)
    source = _document(tmp_path / 'text-limit.pdf', [['x' * 40], ['target']])
    result = reader.search_document(source, sha256_file(source), 'target')
    assert result['matches'][0]['physical_page'] == 2
    assert result['unsearched_pages'] == [{'physical_page': 1, 'reason': 'TEXT_CHAR_LIMIT'}]
    assert result['pages_scanned'] == 1 and result['pages_visited'] == 2
    assert result['next_page'] is None and result['truncated'] and not result['batch_complete']
    assert not result['page_coverage_complete'] and not result['results_complete']


@pytest.mark.parametrize('kwargs', [{'start_page': 0}, {'start_page': True}, {'page_limit': 0},
                                    {'page_limit': 2001}, {'page_limit': 1.5}])
def test_search_rejects_unbounded_or_invalid_intervals(tmp_path, pdf_factory, kwargs):
    source = pdf_factory(tmp_path / 'source.pdf')
    with pytest.raises(ValueError):
        reader.search_document(source, sha256_file(source), 'Cmax', **kwargs)


def test_invalid_unicode_query_is_rejected_before_native_search(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'source.pdf')
    with pytest.raises(ValueError, match='valid Unicode'):
        reader.search_document(source, sha256_file(source), '\ud800')
    with pytest.raises(ValueError, match='valid Unicode'):
        page_operation(source, page_number=1, query='\ud800')


def test_navigation_hierarchy_labels_and_external_target_remain_inert(tmp_path):
    source = tmp_path / 'navigation.pdf'
    with pikepdf.Pdf.new() as pdf:
        for _ in range(4):
            pdf.add_blank_page(page_size=(300, 400))
        with pdf.open_outline() as outline:
            parent = pikepdf.OutlineItem('PK results', 0)
            parent.children.append(pikepdf.OutlineItem('Cmax', 2))
            outline.root.append(parent)
            outline.root.append(pikepdf.OutlineItem('External source', action=pikepdf.Dictionary(
                S=pikepdf.Name.URI, URI='https://example.invalid/do-not-open')))
        pdf.Root.PageLabels = pikepdf.Dictionary(Nums=pikepdf.Array([
            0, pikepdf.Dictionary(S=pikepdf.Name.r),
            2, pikepdf.Dictionary(S=pikepdf.Name.D, P='CSR-', St=1)]))
        pdf.save(source)
    digest = sha256_file(source)
    result = reader.navigation(source, digest)
    parent, child, external = result['bookmarks']
    assert parent['has_children'] and child['parent_id'] == parent['id']
    assert child['physical_page'] == 3 and child['level'] == 1
    assert external['physical_page'] is None and external['destination_state'] == 'NO_INTERNAL_PAGE_DESTINATION'
    assert [p['page_label'] for p in result['page_labels']] == ['i', 'ii', 'CSR-1', 'CSR-2']
    assert result['bookmarks_complete'] and result['page_labels_complete'] and not result['truncated']
    assert sha256_file(source) == digest


def test_navigation_depth_and_label_limits_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'MAX_BOOKMARK_DEPTH', 2)
    monkeypatch.setattr(reader, 'MAX_PAGE_LABELS', 2)
    source = tmp_path / 'deep-outline.pdf'
    with pikepdf.Pdf.new() as pdf:
        for _ in range(3):
            pdf.add_blank_page(page_size=(300, 400))
        with pdf.open_outline() as outline:
            root = pikepdf.OutlineItem('Root', 0)
            child = pikepdf.OutlineItem('Child', 1)
            child.children.append(pikepdf.OutlineItem('Deep child', 2))
            root.children.append(child)
            outline.root.append(root)
            outline.root.append(pikepdf.OutlineItem('Other root', 2))
        pdf.save(source)
    result = reader.navigation(source, sha256_file(source))
    assert [item['title'] for item in result['bookmarks']] == ['Root', 'Child', 'Other root']
    assert result['bookmarks'][1]['children_truncated']
    assert not result['bookmarks_complete'] and not result['page_labels_complete']
    assert result['limit_reasons'] == ['BOOKMARK_DEPTH_LIMIT', 'PAGE_LABEL_COUNT_LIMIT']


@pytest.mark.parametrize('cycle', ['sibling', 'child'])
def test_exposed_circular_outline_is_bounded_and_not_claimed_complete(tmp_path, cycle):
    source = tmp_path / 'cyclic-outline.pdf'
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page(page_size=(300, 400))
        outline = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Outlines))
        item = pdf.make_indirect(pikepdf.Dictionary(Title='Cycle', Parent=outline,
            Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit])))
        other = pdf.make_indirect(pikepdf.Dictionary(Title='Other', Parent=outline,
            Dest=pikepdf.Array([page.obj, pikepdf.Name.Fit])))
        # PDFium suppresses a direct self-sibling before exposing it. A two-node
        # cycle exercises the reader's traversal guard using actual native handles.
        if cycle == 'sibling':
            item.Next, other.Next = other, item
        else:
            item.First, other.First = other, item
        outline.First, outline.Last, outline.Count = item, other, 2
        pdf.Root.Outlines = outline
        pdf.save(source)
    result = reader.navigation(source, sha256_file(source))
    assert len(result['bookmarks']) == 2
    assert result['coverage_scope'] == 'PDFIUM_EXPOSED_NAVIGATION'
    assert not result['bookmarks_complete'] and 'BOOKMARK_CYCLE' in result['limit_reasons']


def test_navigation_count_limit_does_not_falsely_truncate_at_exact_cap(tmp_path, monkeypatch):
    source = tmp_path / 'count-outline.pdf'
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(300, 400))
        with pdf.open_outline() as outline:
            outline.root.extend([pikepdf.OutlineItem('A', 0), pikepdf.OutlineItem('B', 0)])
        pdf.save(source)
    monkeypatch.setattr(reader, 'MAX_BOOKMARKS', 2)
    assert reader.navigation(source, sha256_file(source))['bookmarks_complete']
    monkeypatch.setattr(reader, 'MAX_BOOKMARKS', 1)
    truncated = reader.navigation(source, sha256_file(source))
    assert len(truncated['bookmarks']) == 1 and 'BOOKMARK_ITEM_LIMIT' in truncated['limit_reasons']


def test_frozen_source_identity_is_required_for_navigation_and_search(tmp_path, pdf_factory):
    source = pdf_factory(tmp_path / 'changed.pdf')
    digest = sha256_file(source)
    source.write_bytes(source.read_bytes() + b'\n% synthetic revision\n')
    for action in (lambda: reader.navigation(source, digest),
                   lambda: reader.search_document(source, digest, 'Cmax')):
        with pytest.raises(ValueError, match='changed'):
            action()
