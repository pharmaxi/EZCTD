"""Read-only PDFium page inspection, text location and bounded raster preview.

Coordinates are PDF canvas units, lower-left origin, [left,bottom,right,top].
They are not screen pixels and must be transformed by the eventual viewer.
No OCR, external actions, attachments or JavaScript are executed here.
"""
from __future__ import annotations

import base64
from contextlib import closing
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


def page_operation(path: Path, *, page_number: int, query: str | None = None,
                   render: bool = False, dpi: int = 120) -> dict:
    source = selected_path(path)
    if page_number < 1:
        raise ValueError('Physical page number is 1-based')
    if not 36 <= dpi <= 300:
        raise ValueError('DPI must be between 36 and 300')
    if query is not None and (not query or len(query) > 256 or '\x00' in query):
        raise ValueError('Search query must contain 1 to 256 characters, without NUL')
    if source.stat().st_size > MAX_BYTES:
        raise ValueError('PDF exceeds the configured preview input-size limit')
    before = sha256_file(source)
    # Memory input prevents PDFium from following a file-name interpretation.
    with source.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('PDF grew beyond the preview input-size limit')
    with closing(pdfium.PdfDocument(data)) as doc:
        if page_number > len(doc):
            raise ValueError('Physical page number is outside this PDF')
        with closing(doc[page_number - 1]) as page:
            width, height = page.get_size()
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
            if render:
                if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                    raise ValueError('Invalid page dimensions')
                w = math.ceil(width * dpi / 72)
                h = math.ceil(height * dpi / 72)
                if not all(math.isfinite(v) and v > 0 for v in (width, height)) or w * h > MAX_PIXELS:
                    raise ValueError('Rendered page exceeds the pixel limit')
                with closing(page.render(scale=dpi / 72)) as bitmap:
                    image = bitmap.to_pil()
                    buffer = BytesIO()
                    image.save(buffer, format='PNG')
                    result.update({'width_px': image.width, 'height_px': image.height,
                                   'dpi': dpi, 'png_base64': base64.b64encode(buffer.getvalue()).decode('ascii')})
            else:
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
    after = sha256_file(source)
    if after != before:
        raise RuntimeError('Input changed while reading; discard this page result')
    result['input_integrity'] = {'sha256_before': before, 'sha256_after': after, 'unchanged': True}
    return result
