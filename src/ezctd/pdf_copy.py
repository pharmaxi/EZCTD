"""Native-only linearization with strict guards and explicit preservation evidence.

Not a regulatory validator, PDF/A validator or cryptographic signature verifier.
Called only inside a disposable worker. The parent publishes the verified stage.
"""
from __future__ import annotations

from collections import deque
from contextlib import closing
from decimal import Decimal
import hashlib
from io import BytesIO
import json
import math
import re
from pathlib import Path

import pikepdf
import pypdfium2 as pdfium

from .read_scope import selected_path
from .safe_io import sha256_file, validate_new_output

MAX_BYTES = 200 * 1024 * 1024
MAX_OBJECTS = 250_000
MAX_DECODED = 512 * 1024 * 1024
MAX_PAGES = 2000
VERIFY_DPI = 150
MAX_PIXELS = 20_000_000


def _read_frozen(path: Path, expected: str) -> tuple[Path, bytes]:
    source = selected_path(path)
    if not expected or len(expected) != 64:
        raise ValueError('A frozen SHA-256 input identity is required')
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('Input exceeds the configured 200 MiB processing limit')
    with source.open('rb') as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('Input changed or exceeded limit; select and plan again')
    return source, data


def rewrite_guards(pdf: pikepdf.Pdf) -> list[str]:
    """Any structural signature signal blocks rewrite, including empty fields.

The complete indirect-object inventory is checked, not only visible widgets.
No validity/identity/trust claim is made about any signature found.
"""
    reasons: set[str] = set()
    if pdf.is_encrypted:
        reasons.add('ENCRYPTED_OR_PERMISSION_RESTRICTED')
    if not 0 < len(pdf.pages) <= MAX_PAGES:
        reasons.add('PAGE_LIMIT_OR_EMPTY_DOCUMENT')
    if len(pdf.objects) > MAX_OBJECTS:
        return sorted(reasons | {'OBJECT_LIMIT'})
    queue = deque([pdf.Root, *pdf.objects])
    seen: set[tuple[int, int]] = set()
    visited = 0
    while queue:
        obj = queue.popleft()
        visited += 1
        if visited > MAX_OBJECTS * 4:
            reasons.add('OBJECT_TRAVERSAL_LIMIT')
            break
        if not isinstance(obj, pikepdf.Object):
            continue
        if obj.is_indirect:
            if obj.objgen in seen:
                continue
            seen.add(obj.objgen)
        if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)):
            keys = set(obj.keys())
            if (str(obj.get('/FT', '')) == '/Sig' or str(obj.get('/Type', '')) in ('/Sig', '/DocTimeStamp')
                    or keys & {'/ByteRange', '/DocMDP', '/UR3', '/DSS'}):
                reasons.add('SIGNATURE_SIGNAL')
            if '/Perms' in keys:
                reasons.add('DOCUMENT_PERMISSIONS_SIGNAL')
            if keys & {'/AcroForm', '/XFA', '/Collection'} or str(obj.get('/Subtype', '')) == '/Widget':
                reasons.add('INTERACTIVE_FORM_OR_PORTFOLIO_NOT_SUPPORTED')
            if str(obj.get('/S', '')) in ('/JavaScript', '/Launch', '/Rendition', '/Movie', '/Sound', '/GoToE'):
                reasons.add('ACTIVE_CONTENT_NOT_SUPPORTED')
            if keys & {'/JavaScript', '/JS', '/3D', '/RichMediaContent'}:
                reasons.add('ACTIVE_CONTENT_NOT_SUPPORTED')
            if keys & {'/EmbeddedFiles', '/EF', '/AF'} or str(obj.get('/Type', '')) == '/EmbeddedFile':
                reasons.add('ATTACHMENTS_NOT_SUPPORTED_FOR_REWRITE')
            queue.extend(obj.values())
        elif isinstance(obj, pikepdf.Array):
            queue.extend(obj)
    return sorted(reasons)


def semantic_fingerprint(pdf: pikepdf.Pdf) -> str:
    """Canonical reachable graph: object numbers and lossless compression excluded.

All catalog/trailer semantics except xref bookkeeping and file-ID are included.
Every stream payload is hashed. Undecodable image codecs retain raw bytes plus
filter dictionaries, rather than silently omitting stream evidence.
"""
    ids: dict[tuple[int, int], int] = {}
    queue: list = []
    decoded = 0
    visits = 0

    def encode(obj, *, expand: bool = False, depth: int = 0):
        nonlocal visits, decoded
        visits += 1
        if visits > MAX_OBJECTS * 8 or depth > 96:
            raise ValueError('Semantic graph traversal limit')
        if isinstance(obj, pikepdf.Object) and obj.is_indirect and not expand:
            key = obj.objgen
            if key not in ids:
                if len(ids) >= MAX_OBJECTS:
                    raise ValueError('Semantic object limit')
                ids[key] = len(queue)
                queue.append(obj)
            return {'ref': ids[key]}
        if obj is None or isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float, Decimal)):
            number = Decimal(str(obj))
            if not number.is_finite():
                raise ValueError('Nonfinite PDF number')
            return {'number': str(number.normalize())}
        if isinstance(obj, pikepdf.Stream):
            omitted = {'/Length'}
            try:
                data = obj.read_bytes()
                omitted |= {'/Filter', '/DecodeParms'}
                mode = 'generalized-decoded'
            except pikepdf.PdfError:
                data = obj.read_raw_bytes()
                mode = 'raw-filter-preserved'
            decoded += len(data)
            if decoded > MAX_DECODED:
                raise ValueError('Decoded stream total limit')
            return {'stream': hashlib.sha256(data).hexdigest(), 'mode': mode,
                    'dict': {key: encode(obj[key], depth=depth + 1)
                             for key in sorted(obj.keys()) if key not in omitted}}
        if isinstance(obj, pikepdf.Dictionary):
            return {key: encode(obj[key], depth=depth + 1) for key in sorted(obj.keys())}
        if isinstance(obj, pikepdf.Array):
            return [encode(value, depth=depth + 1) for value in obj]
        if isinstance(obj, pikepdf.Name):
            return {'name': str(obj)}
        if isinstance(obj, pikepdf.String):
            return {'string_hex': bytes(obj).hex()}
        raise ValueError(f'Unsupported semantic object: {type(obj).__name__}')

    omitted = {'/Size', '/ID', '/Prev', '/XRefStm', '/Type', '/W', '/Index', '/Length', '/Filter', '/DecodeParms'}
    roots = {key: encode(pdf.trailer[key]) for key in sorted(pdf.trailer.keys()) if key not in omitted}
    objects = []
    index = 0
    while index < len(queue):
        objects.append(encode(queue[index], expand=True))
        index += 1
    canonical = json.dumps({'roots': roots, 'objects': objects}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def inspect_copy(path: Path, expected: str) -> dict:
    source, data = _read_frozen(path, expected)
    try:
        with pikepdf.Pdf.open(BytesIO(data), attempt_recovery=False) as pdf:
            blockers = rewrite_guards(pdf)
            if re.search(rb'/ByteRange\b|/DocMDP\b|/FT\s*/Sig\b', data):
                blockers.append('SIGNATURE_OR_PRIOR_REVISION_BYTE_SIGNAL')
            syntax = pdf.check_pdf_syntax()
            if syntax:
                blockers.append('SOURCE_SYNTAX_WARNINGS')
            linearized = bool(pdf.is_linearized and pdf.check_linearization())
            result = {'source_sha256': expected, 'page_count': len(pdf.pages),
                      'linearized': linearized, 'blockers': sorted(set(blockers)),
                      'signature_check': 'STRUCTURAL_SIGNALS_ONLY_NOT_CRYPTOGRAPHIC',
                      'operation': 'linearize', 'official_compliance': 'NOT_ESTABLISHED'}
            result['eligibility'] = 'BLOCKED' if blockers else 'NO_CHANGE_NEEDED' if linearized else 'ELIGIBLE'
    except pikepdf.PasswordError:
        result = {'source_sha256': expected, 'eligibility': 'BLOCKED',
                  'blockers': ['PASSWORD_REQUIRED'], 'operation': 'linearize'}
    if sha256_file(source) != expected:
        raise ValueError('Input changed during preflight')
    return result


def _visual_evidence(before: bytes, after: bytes) -> list[dict]:
    evidence = []
    with closing(pdfium.PdfDocument(before)) as left, closing(pdfium.PdfDocument(after)) as right:
        if len(left) != len(right):
            raise ValueError('Page count changed')
        for index in range(len(left)):
            with closing(left[index]) as a, closing(right[index]) as b:
                geometry_a = (a.get_size(), a.get_bbox(), a.get_rotation(), left.get_page_label(index))
                geometry_b = (b.get_size(), b.get_bbox(), b.get_rotation(), right.get_page_label(index))
                if geometry_a != geometry_b:
                    raise ValueError(f'Page geometry or label changed: {index + 1}')
                width, height = a.get_size()
                if (not all(math.isfinite(v) and v > 0 for v in (width, height))
                        or math.ceil(width * VERIFY_DPI / 72) * math.ceil(height * VERIFY_DPI / 72) > MAX_PIXELS):
                    raise ValueError('Full-page verification pixel limit; not published')
                with closing(a.get_textpage()) as ta, closing(b.get_textpage()) as tb:
                    if max(ta.count_chars(), tb.count_chars()) > 1_000_000:
                        raise ValueError('Full-page text limit; not published')
                    sa = ta.get_text_bounded(errors='strict')
                    sb = tb.get_text_bounded(errors='strict')
                    if sa != sb or ta.count_chars() != tb.count_chars():
                        raise ValueError(f'Extracted text changed: {index + 1}')
                hashes = []
                sizes = []
                for page in (a, b):
                    with closing(page.render(scale=VERIFY_DPI / 72, draw_annots=True)) as bitmap:
                        image = bitmap.to_pil().convert('RGB')
                        sizes.append(image.size)
                        hashes.append(hashlib.sha256(image.tobytes()).hexdigest())
                if hashes[0] != hashes[1] or sizes[0] != sizes[1]:
                    raise ValueError(f'Rendered page pixels changed: {index + 1}')
                evidence.append({'physical_page': index + 1, 'dpi': VERIFY_DPI,
                                 'pixel_size': list(sizes[0]), 'pixel_sha256_before': hashes[0],
                                 'pixel_sha256_after': hashes[1], 'pixels_equal': True,
                                 'text_sha256': hashlib.sha256(sa.encode('utf-8')).hexdigest(),
                                 'text_equal': True, 'geometry_equal': True})
    return evidence


def linearize_stage(path: Path, expected: str, stage_path: Path) -> dict:
    source, data = _read_frozen(path, expected)
    target = validate_new_output(stage_path, inputs=(source,), input_roots=(source.parent,))
    with pikepdf.Pdf.open(BytesIO(data), attempt_recovery=False) as pdf:
        blockers = rewrite_guards(pdf)
        if re.search(rb'/ByteRange\b|/DocMDP\b|/FT\s*/Sig\b', data):
            blockers.append('SIGNATURE_OR_PRIOR_REVISION_BYTE_SIGNAL')
        if blockers:
            raise ValueError('Rewrite blocked: ' + ', '.join(blockers))
        if pdf.check_pdf_syntax():
            raise ValueError('Source syntax warnings require separate review')
        if pdf.is_linearized and pdf.check_linearization():
            raise ValueError('No change needed; already linearized')
        before_graph = semantic_fingerprint(pdf)
        out = BytesIO()
        pdf.save(out, linearize=True, fix_metadata_version=False, normalize_content=False,
                 recompress_flate=False, deterministic_id=True)
        changed = out.getvalue()
    if len(changed) > MAX_BYTES:
        raise ValueError('Output exceeds the configured 200 MiB limit')
    with pikepdf.Pdf.open(BytesIO(changed), attempt_recovery=False) as checked:
        if checked.check_pdf_syntax() or not checked.is_linearized or not checked.check_linearization():
            raise ValueError('Output structure or linearization verification failed')
        after_graph = semantic_fingerprint(checked)
    if before_graph != after_graph:
        raise ValueError('Reachable semantic graph changed; output not published')
    pages = _visual_evidence(data, changed)
    if sha256_file(source) != expected:
        raise ValueError('Input changed during verification; discard result')
    # Only a private, parent-designated stage is written; final paths are never accepted here.
    with target.open('xb') as handle:
        handle.write(changed)
    return {'operation': 'linearize', 'verification_status': 'VERIFIED_LOCAL_INVARIANTS',
            'source_sha256': expected, 'output_sha256': hashlib.sha256(changed).hexdigest(),
            'output_bytes': len(changed), 'semantic_graph_before': before_graph,
            'semantic_graph_after': after_graph, 'page_count': len(pages), 'pages': pages,
            'linearization_valid': True, 'input_unchanged': True,
            'engines': {'pikepdf': pikepdf.__version__, 'qpdf': pikepdf.__libqpdf_version__,
                        'pypdfium2': str(pdfium.PYPDFIUM_INFO), 'pdfium': str(pdfium.PDFIUM_INFO)},
            'limits': {'max_bytes': MAX_BYTES, 'max_pages': MAX_PAGES, 'verify_dpi': VERIFY_DPI},
            'proof_scope': 'Reachable semantic graph, streams, geometry, labels, extracted text and all-page pixels at fixed DPI; not all-reader equivalence or official approval',
            'official_compliance': 'NOT_ESTABLISHED'}
