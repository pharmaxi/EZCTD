"""Native page organization: complete permutations and persistent quarter turns.

The original page objects are retained. Only page-tree leaf order/parents,
explicit rotation and source-associated page labels are edited. Publication is
allowed only after reopening the bytes, checking actual navigation targets,
reversing those declared changes for a full semantic-graph comparison, and
comparing every mapped page's PDFium pixels and source-oriented text.

This module is imported by disposable workers only. It does not publish final
paths, follow external destinations, execute actions or validate signatures.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import closing
import ctypes
from decimal import Decimal
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .page_tools import page_operation_bytes
from .pdf_copy import (MAX_BYTES, MAX_OBJECTS, MAX_PAGES, MAX_PIXELS, VERIFY_DPI,
                       _read_frozen, rewrite_guards, semantic_fingerprint)
from .safe_io import sha256_file, validate_new_output

MAX_DESTINATIONS = 10_000
MAX_TREE_DEPTH = 64
MAX_LABEL_PREFIX_BYTES = 4096
MAX_LABEL_TEXT_BYTES = 64 * 1024
SIGNATURE_BYTES = re.compile(rb'/ByteRange\b|/DocMDP\b|/FT\s*/Sig\b')


class OrganizeBlocked(ValueError):
    """A concrete preflight condition this operation cannot preserve safely."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validate_edit(order, rotations, count: int, *, require_change: bool = False) -> None:
    if (not isinstance(order, list) or len(order) != count
            or any(type(p) is not int for p in order)
            or sorted(order) != list(range(1, count + 1))):
        raise ValueError('Order must be a complete permutation of every source page, without duplicates')
    if (not isinstance(rotations, list) or len(rotations) != count
            or any(type(v) is not int or v not in (0, 90, 180, 270) for v in rotations)):
        raise ValueError('Rotations must contain one 0, 90, 180 or 270 degree delta per source page')
    if require_change and order == list(range(1, count + 1)) and not any(rotations):
        raise ValueError('No change needed; page order and rotation are unchanged')


def _page_slots(pdf: pikepdf.Pdf) -> list[tuple]:
    """Keep the existing /Pages topology and every original indirect page.

    pikepdf's sequence slice assignment copies page dictionaries, so it must not
    be used here: links would continue pointing at the former page objects.
    Pdf.open's inherited-attribute pushdown makes crossing a parent boundary
    safe without removing unknown data from the intermediate /Pages nodes.
    """
    seen = set()
    slots = []

    def visit(node, depth: int) -> int:
        if (depth > MAX_TREE_DEPTH or not isinstance(node, pikepdf.Dictionary)
                or not node.is_indirect or node.objgen in seen):
            raise OrganizeBlocked('UNSUPPORTED_OR_CYCLIC_PAGE_TREE')
        seen.add(node.objgen)
        if len(seen) > MAX_OBJECTS:
            raise OrganizeBlocked('PAGE_TREE_OBJECT_LIMIT')
        if str(node.get('/Type', '')) != '/Pages' or not isinstance(node.get('/Kids'), pikepdf.Array):
            raise OrganizeBlocked('INVALID_PAGE_TREE')
        count = 0
        for index, child in enumerate(node.Kids):
            if (not isinstance(child, pikepdf.Dictionary) or not child.is_indirect
                    or child.get('/Parent') is None or child.Parent.objgen != node.objgen):
                raise OrganizeBlocked('INVALID_PAGE_PARENT')
            if str(child.get('/Type', '')) == '/Pages':
                count += visit(child, depth + 1)
            elif str(child.get('/Type', '')) == '/Page':
                if child.objgen in seen:
                    raise OrganizeBlocked('DUPLICATE_PAGE_OBJECT')
                seen.add(child.objgen)
                slots.append((node, index, child))
                count += 1
            else:
                raise OrganizeBlocked('INVALID_PAGE_TREE_CHILD')
        if type(node.get('/Count')) is not int or node.Count != count:
            raise OrganizeBlocked('PAGE_TREE_COUNT_MISMATCH')
        return count

    root = pdf.Root.get('/Pages')
    count = visit(root, 0)
    if not 0 < count <= MAX_PAGES:
        raise OrganizeBlocked('PAGE_LIMIT_OR_EMPTY_DOCUMENT')
    return slots


def _put_order(slots: list[tuple], pages: list, order: list[int]) -> None:
    for (parent, index, _), source_page in zip(slots, order):
        page = pages[source_page - 1]
        parent.Kids[index] = page
        page.Parent = parent


def _label_specs(pdf: pikepdf.Pdf, count: int) -> list[dict] | None:
    root = pdf.Root.get('/PageLabels')
    if root is None:
        return None
    ranges = []
    seen = set()

    def walk(node, depth=0):
        if not isinstance(node, pikepdf.Dictionary) or depth > MAX_TREE_DEPTH:
            raise OrganizeBlocked('UNSUPPORTED_PAGE_LABEL_TREE')
        if node.is_indirect:
            if node.objgen in seen:
                raise OrganizeBlocked('CYCLIC_PAGE_LABEL_TREE')
            seen.add(node.objgen)
        if set(node.keys()) - {'/Nums', '/Kids', '/Limits'}:
            raise OrganizeBlocked('UNSUPPORTED_PAGE_LABEL_TREE_DATA')
        if '/Nums' in node and '/Kids' in node:
            raise OrganizeBlocked('INVALID_PAGE_LABEL_TREE')
        if '/Nums' in node:
            nums = node.Nums
            if not isinstance(nums, pikepdf.Array) or len(nums) % 2:
                raise OrganizeBlocked('INVALID_PAGE_LABEL_NUMBERS')
            for i in range(0, len(nums), 2):
                start, entry = nums[i], nums[i + 1]
                if type(start) is not int or not 0 <= start < count:
                    raise OrganizeBlocked('INVALID_PAGE_LABEL_START')
                if not isinstance(entry, pikepdf.Dictionary) or set(entry.keys()) - {'/S', '/P', '/St'}:
                    raise OrganizeBlocked('UNSUPPORTED_PAGE_LABEL_DATA')
                spec = {}
                if '/S' in entry:
                    if not isinstance(entry.S, pikepdf.Name) or str(entry.S) not in ('/D', '/R', '/r', '/A', '/a'):
                        raise OrganizeBlocked('UNSUPPORTED_PAGE_LABEL_STYLE')
                    spec['style'] = str(entry.S)
                if '/P' in entry:
                    if not isinstance(entry.P, pikepdf.String) or len(bytes(entry.P)) > MAX_LABEL_PREFIX_BYTES:
                        raise OrganizeBlocked('PAGE_LABEL_PREFIX_LIMIT_OR_TYPE')
                    spec['prefix_hex'] = bytes(entry.P).hex()
                start_number = entry.get('/St', 1)
                if type(start_number) is not int or not 1 <= start_number <= 2**31 - count:
                    raise OrganizeBlocked('INVALID_PAGE_LABEL_COUNTER')
                spec['start'] = start_number
                ranges.append((start, spec))
                if len(ranges) > MAX_PAGES:
                    raise OrganizeBlocked('PAGE_LABEL_COUNT_LIMIT')
        elif '/Kids' in node:
            if not isinstance(node.Kids, pikepdf.Array):
                raise OrganizeBlocked('INVALID_PAGE_LABEL_TREE')
            for child in node.Kids:
                walk(child, depth + 1)
        else:
            raise OrganizeBlocked('EMPTY_PAGE_LABEL_TREE')

    walk(root)
    if not ranges or ranges[0][0] != 0 or any(a[0] >= b[0] for a, b in zip(ranges, ranges[1:])):
        raise OrganizeBlocked('UNORDERED_OR_MISSING_PAGE_LABEL_RANGE')
    specs = []
    current = 0
    for index in range(count):
        if current + 1 < len(ranges) and ranges[current + 1][0] == index:
            current += 1
        start, spec = ranges[current]
        current_spec = {**spec, 'start': spec['start'] + index - start}
        # Alphabetic PDF labels repeat one letter (A..Z, AA..ZZ, AAA..),
        # and Roman labels repeat M above 1000. Avoid requesting a native
        # multi-megabyte label just to find its length after allocation.
        number, style = current_spec['start'], current_spec.get('style')
        suffix_chars = (math.ceil(number / 26) if style in ('/A', '/a') else
                        number // 1000 + 15 if style in ('/R', '/r') else
                        10 if style == '/D' else 0)
        if (len(bytes.fromhex(current_spec.get('prefix_hex', ''))) + suffix_chars + 1) * 2 > MAX_LABEL_TEXT_BYTES:
            raise OrganizeBlocked('PAGE_LABEL_TEXT_LIMIT')
        specs.append(current_spec)
    return specs


def _set_labels(pdf: pikepdf.Pdf, specs: list[dict] | None, order: list[int]) -> None:
    if specs is None:
        if '/PageLabels' in pdf.Root:
            del pdf.Root['/PageLabels']
        return
    nums = pikepdf.Array()
    for position, source_page in enumerate(order):
        spec = specs[source_page - 1]
        entry = pikepdf.Dictionary(St=spec['start'])
        if 'style' in spec:
            entry.S = pikepdf.Name(spec['style'])
        if 'prefix_hex' in spec:
            entry.P = pikepdf.String(bytes.fromhex(spec['prefix_hex']))
        nums.extend([position, entry])
    # Only standard, validated label ranges are expanded. Unknown label data
    # is blocked; it is never silently removed during graph normalization.
    pdf.Root.PageLabels = pikepdf.Dictionary(Nums=nums)


def _named_destinations(pdf: pikepdf.Pdf) -> dict[bytes, object]:
    result = {}

    def add(key: bytes, value):
        if key in result or len(result) >= MAX_DESTINATIONS:
            raise OrganizeBlocked('DUPLICATE_OR_EXCESSIVE_NAMED_DESTINATIONS')
        result[key] = value

    if '/Dests' in pdf.Root:
        if not isinstance(pdf.Root.Dests, pikepdf.Dictionary):
            raise OrganizeBlocked('INVALID_NAMED_DESTINATION_DICTIONARY')
        for key, value in pdf.Root.Dests.items():
            # Dictionary keys use pikepdf's lossless surrogateescape decoding;
            # PDF Names are byte strings and need not be valid UTF-8. The
            # reference resolver uses bytes(Name)[1:] for the same identity.
            add(key[1:].encode('utf-8', errors='surrogateescape'), value)
    names = pdf.Root.get('/Names')
    if names is None:
        return result
    if not isinstance(names, pikepdf.Dictionary):
        raise OrganizeBlocked('INVALID_DOCUMENT_NAMES_DICTIONARY')
    if '/Dests' not in names:
        return result
    seen = set()

    def walk(node, depth=0):
        if not isinstance(node, pikepdf.Dictionary) or depth > MAX_TREE_DEPTH:
            raise OrganizeBlocked('INVALID_NAMED_DESTINATION_TREE')
        if node.is_indirect:
            if node.objgen in seen:
                raise OrganizeBlocked('CYCLIC_NAMED_DESTINATION_TREE')
            seen.add(node.objgen)
        if '/Names' in node:
            values = node.Names
            if not isinstance(values, pikepdf.Array) or len(values) % 2:
                raise OrganizeBlocked('INVALID_NAMED_DESTINATION_PAIRS')
            for i in range(0, len(values), 2):
                if not isinstance(values[i], pikepdf.String):
                    raise OrganizeBlocked('INVALID_NAMED_DESTINATION_KEY')
                add(bytes(values[i]), values[i + 1])
        if '/Kids' in node:
            if not isinstance(node.Kids, pikepdf.Array):
                raise OrganizeBlocked('INVALID_NAMED_DESTINATION_TREE')
            for child in node.Kids:
                walk(child, depth + 1)

    walk(names.Dests)
    return result


def _local_navigation(pdf: pikepdf.Pdf, pages: list, source_order: list[int]) -> dict:
    page_numbers = {page.objgen: source_order[i] for i, page in enumerate(pages)}
    names = _named_destinations(pdf)
    bindings = []

    def resolve(value, seen_names=frozenset(), depth=0):
        if depth > MAX_TREE_DEPTH:
            raise OrganizeBlocked('CYCLIC_OR_EXCESSIVE_LOCAL_DESTINATION')
        if isinstance(value, pikepdf.Dictionary) and '/D' in value:
            return resolve(value.D, seen_names, depth + 1)
        if isinstance(value, (pikepdf.String, pikepdf.Name)):
            key = bytes(value) if isinstance(value, pikepdf.String) else bytes(value)[1:]
            if key not in names or key in seen_names:
                raise OrganizeBlocked('UNRESOLVED_OR_CYCLIC_LOCAL_DESTINATION')
            return resolve(names[key], seen_names | {key}, depth + 1)
        if not isinstance(value, pikepdf.Array) or len(value) < 2:
            raise OrganizeBlocked('UNSUPPORTED_LOCAL_DESTINATION')
        target = value[0]
        if type(target) is int:
            raise OrganizeBlocked('INTEGER_LOCAL_DESTINATION_NOT_SUPPORTED')
        if (not isinstance(target, pikepdf.Dictionary) or not target.is_indirect
                or target.objgen not in page_numbers):
            raise OrganizeBlocked('LOCAL_DESTINATION_NOT_IN_PAGE_TREE')
        params = []
        for item in list(value)[1:]:
            if isinstance(item, pikepdf.Name):
                params.append(str(item))
            elif item is None:
                params.append(None)
            elif type(item) in (int, float, Decimal):
                params.append(str(Decimal(str(item)).normalize()))
            else:
                raise OrganizeBlocked('UNSUPPORTED_LOCAL_DESTINATION_PARAMETERS')
        return (page_numbers[target.objgen], json.dumps(params, separators=(',', ':')))

    def record(kind, value):
        bindings.append((kind, *resolve(value)))
        if len(bindings) > MAX_DESTINATIONS:
            raise OrganizeBlocked('LOCAL_DESTINATION_LIMIT')

    for key, value in names.items():
        record('named:' + key.hex(), value)
    initial = pdf.Root.get('/OpenAction')
    if initial is not None and not isinstance(initial, pikepdf.Dictionary):
        record('open', initial)
    queue = deque([pdf.Root])
    seen = set()
    visits = 0
    while queue:
        obj = queue.popleft()
        visits += 1
        if visits > MAX_OBJECTS * 4:
            raise OrganizeBlocked('NAVIGATION_TRAVERSAL_LIMIT')
        if not isinstance(obj, pikepdf.Object):
            continue
        if obj.is_indirect:
            if obj.objgen in seen:
                continue
            seen.add(obj.objgen)
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            if '/Dest' in obj:
                record('destination', obj.Dest)
            if str(obj.get('/S', '')) == '/GoTo':
                record('goto', obj.get('/D'))
            queue.extend(obj.values())
        elif isinstance(obj, pikepdf.Array):
            queue.extend(obj)
    # A multiset reports all parsed target bindings in source-page coordinates.
    # Owner relationships and destination arrays also remain covered by the full
    # reversible semantic-graph proof; this summary does not replace it.
    ordered = sorted(Counter(bindings).items())
    digest = hashlib.sha256(json.dumps(ordered, separators=(',', ':')).encode()).hexdigest()
    return {'binding_count': len(bindings), 'named_destination_count': len(names),
            'source_target_sha256': digest, 'integer_local_destinations': 'BLOCKED',
            'external_targets': 'PRESERVED_INERT_NOT_FOLLOWED'}


def _state(pdf: pikepdf.Pdf, data: bytes) -> dict:
    blockers = rewrite_guards(pdf)
    if SIGNATURE_BYTES.search(data):
        blockers.append('SIGNATURE_OR_PRIOR_REVISION_BYTE_SIGNAL')
    if pdf.check_pdf_syntax():
        blockers.append('SOURCE_SYNTAX_WARNINGS')
    if blockers:
        raise OrganizeBlocked(','.join(sorted(set(blockers))))
    slots = _page_slots(pdf)
    pages = [slot[2] for slot in slots]
    raw_rotations = []
    for page in pages:
        value = page.get('/Rotate', 0)
        if type(value) is not int or value % 90:
            raise OrganizeBlocked('INVALID_SOURCE_PAGE_ROTATION')
        raw_rotations.append(value if '/Rotate' in page else None)
    labels = _label_specs(pdf, len(pages))
    identity = list(range(1, len(pages) + 1))
    return {'slots': slots, 'pages': pages, 'rotations': raw_rotations, 'labels': labels,
            'navigation': _local_navigation(pdf, pages, identity)}


def _serialize_edit(pdf: pikepdf.Pdf, state: dict, order: list[int], rotations: list[int]) -> bytes:
    _put_order(state['slots'], state['pages'], order)
    for index, delta in enumerate(rotations):
        if delta:
            state['pages'][index].Rotate = ((state['rotations'][index] or 0) + delta) % 360
    _set_labels(pdf, state['labels'], order)
    buffer = BytesIO()
    pdf.save(buffer, fix_metadata_version=False, normalize_content=False,
             recompress_flate=False, deterministic_id=True)
    changed = buffer.getvalue()
    if len(changed) > MAX_BYTES:
        raise ValueError('Output exceeds the configured 200 MiB limit')
    return changed


def _page_label(doc, index: int) -> str:
    if pdfium_c.FPDF_GetPageLabel(doc, index, None, 0) > MAX_LABEL_TEXT_BYTES:
        raise OrganizeBlocked('PAGE_LABEL_TEXT_LIMIT')
    return doc.get_page_label(index)


def inspect_organize(path: Path, expected: str) -> dict:
    source, data = _read_frozen(path, expected)
    result = {'operation': 'organize-pages', 'source_sha256': expected,
              'signature_check': 'STRUCTURAL_SIGNALS_ONLY_NOT_CRYPTOGRAPHIC',
              'official_compliance': 'NOT_ESTABLISHED', 'pages': [], 'page_count': 0,
              'limits': {'max_pages': MAX_PAGES, 'max_bytes': MAX_BYTES}}
    try:
        with pikepdf.Pdf.open(BytesIO(data), attempt_recovery=False) as pdf:
            result['page_count'] = len(pdf.pages)
            state = _state(pdf, data)
        with closing(pdfium.PdfDocument(data)) as doc:
            if len(doc) != len(state['pages']):
                raise OrganizeBlocked('NATIVE_PAGE_COUNT_DISAGREEMENT')
            for index in range(len(doc)):
                with closing(doc[index]) as page:
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise OrganizeBlocked('INVALID_PAGE_DIMENSIONS')
                    result['pages'].append({'source_page': index + 1,
                        'page_label': _page_label(doc, index), 'rotation_degrees': page.get_rotation(),
                        'width': width, 'height': height, 'bbox': list(page.get_bbox()),
                        'dimension_scope': 'PDFIUM_DISPLAY_SIZE_WITH_SOURCE_ROTATION'})
        result.update(eligibility='ELIGIBLE', blockers=[], navigation=state['navigation'])
    except pikepdf.PasswordError:
        result.update(eligibility='BLOCKED', blockers=['PASSWORD_REQUIRED'])
    except OrganizeBlocked as exc:
        result.update(eligibility='BLOCKED', blockers=exc.code.split(','), pages=[])
    if sha256_file(source) != expected:
        raise ValueError('Input changed during organize preflight')
    return result


def organize_preview(path: Path, expected: str, order: list[int], rotations: list[int], *,
                     page: int = 1, dpi: int = 120, thumbnail: bool = False) -> dict:
    if type(thumbnail) is not bool:
        raise ValueError('Thumbnail must be a boolean')
    source, data = _read_frozen(path, expected)
    with pikepdf.Pdf.open(BytesIO(data), attempt_recovery=False) as pdf:
        state = _state(pdf, data)
        _validate_edit(order, rotations, len(state['pages']))
        changed = _serialize_edit(pdf, state, order, rotations)
    result = page_operation_bytes(changed, page_number=page, render=True, include_text=not thumbnail,
                                  dpi=36 if thumbnail else dpi,
                                  max_pixels=180_000 if thumbnail else 16_000_000)
    if sha256_file(source) != expected:
        raise ValueError('Input changed during organize preview')
    result.update(operation='organize-preview', source_sha256=expected,
                  preview_pdf_sha256=hashlib.sha256(changed).hexdigest(), source_page=order[page - 1],
                  output_position=page, preview_only=True, verification_status='PREVIEW_NOT_VERIFIED',
                  source_integrity={'sha256_before': expected, 'sha256_after': expected, 'unchanged': True})
    return result


def _native_navigation(data: bytes, order: list[int]) -> dict:
    """Read actual PDFium bookmark/link targets without following any action."""
    bookmarks = []
    links = []
    with closing(pdfium.PdfDocument(data)) as doc:
        first = pdfium_c.FPDFBookmark_GetFirstChild(doc, None)
        pending = [(first, ())] if first else []
        seen = set()
        while pending:
            raw, parent_path = pending.pop()
            address = ctypes.cast(raw, ctypes.c_void_p).value
            if address in seen or len(seen) >= MAX_DESTINATIONS or len(parent_path) >= MAX_TREE_DEPTH:
                raise ValueError('PDFium bookmark traversal incomplete; output not published')
            seen.add(address)
            bookmark = pdfium.PdfBookmark(raw, doc, len(parent_path))
            destination = bookmark.get_dest()
            action = pdfium_c.FPDFBookmark_GetAction(raw)
            local = not action or pdfium_c.FPDFAction_GetType(action) == pdfium_c.PDFACTION_GOTO
            target = destination.get_index() if destination and local else None
            if target is not None and not 0 <= target < len(order):
                raise ValueError('PDFium bookmark target outside document')
            # The stable ordinal path preserves parent/sibling relationships.
            path = parent_path + (len(bookmarks),)
            bookmarks.append({'path': path, 'source_target': order[target] if target is not None else None})
            sibling = pdfium_c.FPDFBookmark_GetNextSibling(doc, raw)
            child = pdfium_c.FPDFBookmark_GetFirstChild(doc, raw)
            if sibling:
                pending.append((sibling, parent_path))
            if child:
                pending.append((child, path))
        for index in range(len(doc)):
            with closing(doc[index]) as page:
                start = ctypes.c_int(0)
                raw_link = pdfium_c.FPDF_LINK()
                ordinal = 0
                while pdfium_c.FPDFLink_Enumerate(page, ctypes.byref(start), ctypes.byref(raw_link)):
                    if len(links) >= MAX_DESTINATIONS:
                        raise ValueError('PDFium link traversal incomplete; output not published')
                    raw_dest = pdfium_c.FPDFLink_GetDest(doc, raw_link)
                    action = pdfium_c.FPDFLink_GetAction(raw_link)
                    local = not action or pdfium_c.FPDFAction_GetType(action) == pdfium_c.PDFACTION_GOTO
                    target = pdfium_c.FPDFDest_GetDestPageIndex(doc, raw_dest) if raw_dest and local else -1
                    if target >= len(order):
                        raise ValueError('PDFium link target outside document')
                    links.append((order[index], ordinal, order[target] if target >= 0 else None))
                    ordinal += 1
    links.sort()
    digest = hashlib.sha256(json.dumps({'bookmarks': bookmarks, 'links': links},
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'bookmark_count': len(bookmarks), 'link_count': len(links),
            'source_target_sha256': digest, 'scope': 'PDFIUM_BOOKMARK_AND_LINK_PAGE_TARGETS'}


def _mapped_visual_evidence(before: bytes, after: bytes, order: list[int], rotations: list[int]) -> list[dict]:
    evidence = []
    with closing(pdfium.PdfDocument(before)) as left, closing(pdfium.PdfDocument(after)) as right:
        if len(left) != len(right) or len(left) != len(order):
            raise ValueError('Page count changed')
        for output_index, source_number in enumerate(order):
            delta = rotations[source_number - 1]
            with closing(left[source_number - 1]) as a, closing(right[output_index]) as b:
                source_rotation = a.get_rotation()
                if b.get_rotation() != (source_rotation + delta) % 360 or a.get_bbox() != b.get_bbox():
                    raise ValueError(f'Output page geometry or rotation differs from edit: {output_index + 1}')
                width, height = a.get_size()
                expected_size = (height, width) if delta in (90, 270) else (width, height)
                if b.get_size() != expected_size:
                    raise ValueError(f'Output display dimensions differ from rotation: {output_index + 1}')
                if _page_label(left, source_number - 1) != _page_label(right, output_index):
                    raise ValueError(f'Page label did not follow source page: {output_index + 1}')
                if (not all(math.isfinite(v) and v > 0 for v in (width, height))
                        or math.ceil(width * VERIFY_DPI / 72) * math.ceil(height * VERIFY_DPI / 72) > MAX_PIXELS):
                    raise ValueError('Full-page verification pixel limit; not published')
                # A viewer's extra render rotation is not the same operation
                # as persistent /Rotate (notably for NoRotate annotations and
                # some existing-rotation combinations). On the independently
                # opened source bytes, change only the requested PDFium page
                # rotation, then compare to the actual serialized output.
                a.set_rotation((source_rotation + delta) % 360)
                hashes, sizes = [], []
                for page in (a, b):
                    with closing(page.render(scale=VERIFY_DPI / 72,
                                              draw_annots=True, limit_image_cache=True)) as bitmap:
                        image = bitmap.to_pil().convert('RGB')
                        hashes.append(hashlib.sha256(image.tobytes()).hexdigest())
                        sizes.append(image.size)
                if hashes[0] != hashes[1] or sizes[0] != sizes[1]:
                    raise ValueError(f'Mapped rendered page pixels differ: {output_index + 1}')
                # Text extraction may order glyphs according to display rotation.
                # Reset just the two PDFium page rotations in memory after the
                # real output pixels were checked; no published bytes change.
                a.set_rotation(source_rotation)
                b.set_rotation(source_rotation)
                with closing(a.get_textpage()) as ta, closing(b.get_textpage()) as tb:
                    if max(ta.count_chars(), tb.count_chars()) > 1_000_000:
                        raise ValueError('Full-page text limit; not published')
                    sa, sb = ta.get_text_bounded(errors='strict'), tb.get_text_bounded(errors='strict')
                    if sa != sb or ta.count_chars() != tb.count_chars():
                        raise ValueError(f'Mapped extracted text differs: {output_index + 1}')
                evidence.append({'output_position': output_index + 1, 'source_page': source_number,
                    'rotation_delta': delta, 'source_rotation_degrees': source_rotation,
                    'output_rotation_degrees': (source_rotation + delta) % 360,
                    'dpi': VERIFY_DPI, 'pixel_size': list(sizes[1]),
                    'expected_rotated_pixel_sha256': hashes[0], 'output_pixel_sha256': hashes[1],
                    'expected_pixel_transform': 'SOURCE_PDFIUM_PERSISTENT_ROTATION',
                    'pixels_equal_after_declared_rotation': True,
                    'text_sha256': hashlib.sha256(sa.encode('utf-8')).hexdigest(),
                    'text_equal': True, 'text_comparison': 'OUTPUT_IN_SOURCE_ORIENTATION',
                    'page_label_preserved': True, 'page_geometry_matches_edit': True})
    return evidence


def organize_stage(path: Path, expected: str, stage_path: Path,
                   order: list[int], rotations: list[int]) -> dict:
    source, data = _read_frozen(path, expected)
    target = validate_new_output(stage_path, inputs=(source,), input_roots=(source.parent,))
    with pikepdf.Pdf.open(BytesIO(data), attempt_recovery=False) as pdf:
        state = _state(pdf, data)
        count = len(state['pages'])
        _validate_edit(order, rotations, count, require_change=True)
        identity = list(range(1, count + 1))
        # Label ranges can represent the same per-page values in many ways.
        # Canonicalize only this explicitly edited subtree on both sides.
        _set_labels(pdf, state['labels'], identity)
        before_graph = semantic_fingerprint(pdf)
        changed = _serialize_edit(pdf, state, order, rotations)
    with pikepdf.Pdf.open(BytesIO(changed), attempt_recovery=False) as checked:
        if checked.check_pdf_syntax() or rewrite_guards(checked):
            raise ValueError('Output structure verification failed')
        slots = _page_slots(checked)
        if len(slots) != count:
            raise ValueError('Output page count changed')
        output_pages = [slot[2] for slot in slots]
        after_navigation = _local_navigation(checked, output_pages, order)
        if after_navigation != state['navigation']:
            raise ValueError('Local navigation target changed; output not published')
        actual_labels = _label_specs(checked, count)
        expected_labels = [state['labels'][p - 1] for p in order] if state['labels'] is not None else None
        if actual_labels != expected_labels:
            raise ValueError('Page label specification differs from requested source mapping')
        original_order_pages = [output_pages[order.index(p)] for p in identity]
        # Undo exactly the requested changes, on reopened output objects. No
        # source page/annotation/content objects are copied over the output.
        _put_order(slots, original_order_pages, identity)
        for index, page in enumerate(original_order_pages):
            expected_rotation = ((state['rotations'][index] or 0) + rotations[index]) % 360
            if type(page.get('/Rotate', 0)) is not int or page.get('/Rotate', 0) % 360 != expected_rotation:
                raise ValueError('Output persistent rotation differs from requested edit')
            if rotations[index]:
                if state['rotations'][index] is None:
                    if '/Rotate' in page:
                        del page['/Rotate']
                else:
                    page.Rotate = state['rotations'][index]
        # Reorder actual output label specifications; never overwrite them with
        # source data before comparing their values above.
        _set_labels(checked, actual_labels, [order.index(p) + 1 for p in identity])
        after_graph = semantic_fingerprint(checked)
    if before_graph != after_graph:
        raise ValueError('Non-target semantic graph changed; output not published')
    native_before = _native_navigation(data, identity)
    native_after = _native_navigation(changed, order)
    if native_before != native_after:
        raise ValueError('PDFium navigation targets changed; output not published')
    pages = _mapped_visual_evidence(data, changed, order, rotations)
    if sha256_file(source) != expected:
        raise ValueError('Input changed during organize verification; discard result')
    with target.open('xb') as handle:
        handle.write(changed)
    mapping_keys = ('output_position', 'source_page', 'rotation_delta',
                    'source_rotation_degrees', 'output_rotation_degrees')
    return {'operation': 'organize-pages', 'verification_status': 'VERIFIED_LOCAL_INVARIANTS',
            'source_sha256': expected, 'output_sha256': hashlib.sha256(changed).hexdigest(),
            'output_bytes': len(changed), 'page_count': count, 'order': order, 'rotations': rotations,
            'page_mapping': [{key: p[key] for key in mapping_keys} for p in pages], 'pages': pages,
            'semantic_graph_before': before_graph, 'semantic_graph_after_normalization': after_graph,
            'non_target_semantics_preserved': True,
            'normalization_scope': ['PAGE_TREE_LEAF_ORDER_AND_PARENT', 'DECLARED_ROTATION_DELTAS',
                                    'VALIDATED_SOURCE_ASSOCIATED_PAGE_LABELS'],
            'navigation': {'preserved': True, 'structural': after_navigation, 'pdfium': native_after},
            'input_unchanged': True,
            'engines': {'pikepdf': pikepdf.__version__, 'qpdf': pikepdf.__libqpdf_version__,
                        'pypdfium2': str(pdfium.PYPDFIUM_INFO), 'pdfium': str(pdfium.PDFIUM_INFO)},
            'limits': {'max_bytes': MAX_BYTES, 'max_pages': MAX_PAGES, 'verify_dpi': VERIFY_DPI},
            'proof_scope': 'Declared full permutation/rotation, source-associated labels, native navigation, reversible full semantic graph, all-page rotated pixels and source-oriented text; not all-reader equivalence or official approval',
            'official_compliance': 'NOT_ESTABLISHED'}
