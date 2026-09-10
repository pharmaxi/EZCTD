"""Native reader navigation and document search. All external actions stay inert."""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import pypdfium2 as pdfium

from .pdf_copy import _read_frozen
from .safe_io import sha256_file


def navigation(path: Path, expected: str) -> dict:
    source, data = _read_frozen(path, expected)
    items = []
    truncated = False
    with closing(pdfium.PdfDocument(data)) as doc:
        for bookmark in doc.get_toc(max_depth=32):
            if len(items) >= 5000:
                truncated = True
                break
            dest = bookmark.get_dest()
            index = dest.get_index() if dest else None
            items.append({'title': bookmark.get_title()[:1000], 'level': bookmark.level,
                          'physical_page': index + 1 if index is not None and 0 <= index < len(doc) else None})
        result = {'page_count': len(doc), 'bookmarks': items, 'truncated': truncated,
                  'navigation_scope': 'Internal bookmark page targets; external targets are not followed',
                  'source_sha256': expected}
    if sha256_file(source) != expected:
        raise ValueError('Source changed while reading navigation')
    return result


def search_document(path: Path, expected: str, query: str) -> dict:
    if not isinstance(query, str) or not 1 <= len(query) <= 256 or '\x00' in query:
        raise ValueError('Search query must contain 1 to 256 characters')
    source, data = _read_frozen(path, expected)
    hits = []
    scanned = 0
    truncated = False
    with closing(pdfium.PdfDocument(data)) as doc:
        for index in range(min(len(doc), 2000)):
            with closing(doc[index]) as page, closing(page.get_textpage()) as text:
                if text.count_chars() > 1_000_000:
                    raise ValueError(f'Page {index + 1} exceeds the text limit; search incomplete')
                with closing(text.search(query)) as search:
                    count = 0
                    while search.get_next() is not None:
                        count += 1
                        if count >= 500:
                            truncated = True
                            break
                if count:
                    hits.append({'physical_page': index + 1, 'page_label': doc.get_page_label(index),
                                 'hit_count': count, 'snippet': text.get_text_bounded(errors='strict')[:600]})
                scanned += 1
                if len(hits) >= 500:
                    truncated = True
                    break
        result = {'query': query, 'pages_scanned': scanned, 'page_count': len(doc),
                  'matches': hits, 'truncated': truncated or scanned < len(doc),
                  'source_sha256': expected, 'search_scope': 'Extractable text; OCR not performed'}
    if sha256_file(source) != expected:
        raise ValueError('Source changed while searching')
    return result
