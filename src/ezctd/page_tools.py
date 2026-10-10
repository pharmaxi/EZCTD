"""Read-only PDFium page inspection, text location and bounded raster preview.

Coordinates are PDF canvas units, lower-left origin, [left,bottom,right,top].
They are not screen pixels and must be transformed by the eventual viewer.
No OCR, external actions, attachments or JavaScript are executed here.
"""
from __future__ import annotations

import base64
from contextlib import closing
import hashlib
from io import BytesIO
import math
from pathlib import Path
import pypdfium2 as pdfium

from .read_scope import selected_path
from .safe_io import sha256_file

MAX_BYTES = 200 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_TEXT_CHARS = 1_000_000
MAX_HITS = 500


def _render_scale(width: float, height: float, dpi: float, max_pixels: int) -> float:
    """Fit the complete page, including its last partial row/column, to the cap.

    PDFium rounds each dimension up. An area-only square-root calculation can
    therefore still exceed the cap, especially on very narrow pages. No minimum
    effective DPI is imposed: the allocation limit wins over requested quality.
    """
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError('Invalid page dimensions')
    requested = dpi / 72

    def fits(scale: float) -> bool:
        w, h = math.ceil(width * scale), math.ceil(height * scale)
        return w > 0 and h > 0 and w * h <= max_pixels

    # Bound individual dimensions before multiplying or converting to integers.
    upper = min(requested, max_pixels / width, max_pixels / height)
    if upper == requested and fits(requested):
        return requested
    lower = 0.0
    for _ in range(64):
        middle = lower + (upper - lower) / 2
        if fits(middle):
            lower = middle
        else:
            upper = middle
    if lower <= 0 or not fits(lower):
        raise ValueError('Page dimensions cannot be rendered within the pixel limit')
    return lower


def _validate_page_request(page_number, dpi, max_pixels, query) -> None:
    if type(page_number) is not int or page_number < 1:
        raise ValueError('Physical page number is 1-based')
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)) or not 36 <= dpi <= 300:
        raise ValueError('DPI must be between 36 and 300')
    if type(max_pixels) is not int or not 1 <= max_pixels <= MAX_PIXELS:
        raise ValueError(f'Pixel limit must be between 1 and {MAX_PIXELS}')
    if query is not None and (not isinstance(query, str) or not query or len(query) > 256 or '\x00' in query):
        raise ValueError('Search query must contain 1 to 256 characters, without NUL')
    if query is not None:
        try:
            query.encode('utf-16-le')
        except UnicodeEncodeError as exc:
            raise ValueError('Search query must contain valid Unicode characters') from exc


def page_operation_bytes(data: bytes, *, page_number: int, query: str | None = None,
                         render: bool = False, dpi: int = 120, include_text: bool = False,
                         max_pixels: int = MAX_PIXELS) -> dict:
    """Inspect or rasterize actual in-memory PDF bytes without creating a file.

    Used by the editing worker for draft previews. This performs bounded reader
    inspection only; it is not the editing operation's publication verification.
    """
    _validate_page_request(page_number, dpi, max_pixels, query)
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError('PDF bytes exceed the configured preview input-size limit')
    before = hashlib.sha256(data).hexdigest()
    with closing(pdfium.PdfDocument(data)) as doc:
        if page_number > len(doc):
            raise ValueError('Physical page number is outside this PDF')
        with closing(doc[page_number - 1]) as page:
            width, height = page.get_size()
            if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                raise ValueError('Invalid page dimensions')
            result = {
                'operation': 'render-page' if render else 'inspect-page',
                'physical_page': page_number, 'page_count': len(doc),
                'page_label': doc.get_page_label(page_number - 1),
                'coordinate_system': 'PDF_CANVAS_LOWER_LEFT_LBRT',
                'bbox': list(page.get_bbox()), 'size': [width, height],
                'rotation_degrees': page.get_rotation(),
                'input_sha256': before,
                'compliance_conclusion': 'NOT_ESTABLISHED',
            }
            if not render or include_text:
                with closing(page.get_textpage()) as textpage:
                    if textpage.count_chars() > MAX_TEXT_CHARS:
                        raise ValueError('Page exceeds the text extraction limit')
                    result['text'] = textpage.get_text_bounded(errors='strict')
                    result['text_state'] = 'TEXT_EXTRACTED' if result['text'].strip() else 'NO_EXTRACTABLE_TEXT'
                    result['search_matches'] = []
                    result['search_truncated'] = False
                    if query is not None:
                        # Search uses PDFium character indices, not Python string offsets.
                        with closing(textpage.search(query)) as search:
                            while (hit := search.get_next()) is not None:
                                if len(result['search_matches']) >= MAX_HITS:
                                    result['search_truncated'] = True
                                    break
                                start, count = hit
                                boxes = [list(textpage.get_charbox(i)) for i in range(start, start + count)]
                                result['search_matches'].append({'char_index': start, 'char_count': count,
                                                                 'rectangles': boxes})
            if render:
                scale = _render_scale(width, height, dpi, max_pixels)
                reduced = scale < dpi / 72
                with closing(page.render(scale=scale, limit_image_cache=True)) as bitmap:
                    if bitmap.width < 1 or bitmap.height < 1 or bitmap.width * bitmap.height > max_pixels:
                        raise ValueError('Rendered page exceeds the pixel limit')
                    image = bitmap.to_pil()
                    buffer = BytesIO()
                    image.save(buffer, format='PNG')
                    converter = bitmap.get_posconv(page)
                    for match in result.get('search_matches', []):
                        converted = []
                        for left, bottom, right, top in match['rectangles']:
                            corners = [converter.to_bitmap(x, y) for x, y in
                                       ((left, bottom), (left, top), (right, bottom), (right, top))]
                            xs, ys = zip(*corners)
                            converted.append([min(xs), min(ys), max(xs), max(ys)])
                        match['rectangles_px'] = converted
                    result.update({'width_px': image.width, 'height_px': image.height,
                                   'requested_dpi': dpi, 'effective_dpi': scale * 72, 'dpi': scale * 72,
                                   'resolution_reduced': reduced,
                                   'resolution_state': 'REDUCED_TO_PIXEL_LIMIT' if reduced else 'REQUESTED_RESOLUTION',
                                   'render_limits': {'max_pixels': max_pixels, 'full_page': True},
                                   'png_base64': base64.b64encode(buffer.getvalue()).decode('ascii')})
    result['input_integrity'] = {'sha256_before': before, 'sha256_after': before, 'unchanged': True}
    return result


def page_operation(path: Path, *, page_number: int, query: str | None = None,
                   render: bool = False, dpi: int = 120, include_text: bool = False,
                   max_pixels: int = MAX_PIXELS) -> dict:
    source = selected_path(path)
    _validate_page_request(page_number, dpi, max_pixels, query)
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('PDF exceeds the configured preview input-size limit')
    before = sha256_file(source)
    # Memory input prevents PDFium from following a file-name interpretation.
    with source.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('PDF grew beyond the preview input-size limit')
    if hashlib.sha256(data).hexdigest() != before:
        raise RuntimeError('Input changed while reading; discard this page result')
    result = page_operation_bytes(data, page_number=page_number, query=query, render=render,
                                  dpi=dpi, include_text=include_text, max_pixels=max_pixels)
    after = sha256_file(source)
    if after != before:
        raise RuntimeError('Input changed while reading; discard this page result')
    result['input_integrity'] = {'sha256_before': before, 'sha256_after': after, 'unchanged': True}
    return result
