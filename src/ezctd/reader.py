"""Bounded native navigation and resumable text search. External actions stay inert."""
from __future__ import annotations

from contextlib import closing
import ctypes
from pathlib import Path
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from .pdf_copy import _read_frozen
from .safe_io import sha256_file


MAX_BOOKMARKS = 5000
MAX_BOOKMARK_DEPTH = 32
MAX_PAGE_LABELS = 5000
MAX_NAV_TEXT_CHARS = 1000
MAX_NATIVE_NAV_TEXT_BYTES = 64 * 1024
DEFAULT_SEARCH_PAGES = 200
MAX_SEARCH_PAGES = 2000
MAX_SEARCH_HIT_PAGES = 500
MAX_PAGE_HITS = 500
MAX_TEXT_CHARS = 1_000_000
MAX_SNIPPET_CHARS = 600


def _navigation_text(n_bytes: int, read) -> tuple[str, bool]:
    # PDFium's UTF-16 metadata getters require a complete buffer; slicing after
    # an unbounded native allocation would not enforce a display budget.
    if n_bytes > MAX_NATIVE_NAV_TEXT_BYTES:
        return '(Metadata exceeds the reader display limit)', True
    value = read()
    return value[:MAX_NAV_TEXT_CHARS], len(value) > MAX_NAV_TEXT_CHARS


def navigation(path: Path, expected: str) -> dict:
    source, data = _read_frozen(path, expected)
    items, labels, reasons = [], [], set()
    with closing(pdfium.PdfDocument(data)) as doc:
        # An explicit stack lets us report depth limits and cycles. get_toc()
        # only logs these conditions, which cannot establish complete coverage.
        first = pdfium_c.FPDFBookmark_GetFirstChild(doc, None)
        pending = [(first, 0, None)] if first else []
        seen = set()
        while pending:
            raw, level, parent_id = pending.pop()
            address = ctypes.cast(raw, ctypes.c_void_p).value
            if address in seen:
                reasons.add('BOOKMARK_CYCLE')
                continue
            if len(items) >= MAX_BOOKMARKS:
                reasons.add('BOOKMARK_ITEM_LIMIT')
                break
            seen.add(address)
            bookmark = pdfium.PdfBookmark(raw, doc, level)
            title, title_truncated = _navigation_text(
                pdfium_c.FPDFBookmark_GetTitle(raw, None, 0), bookmark.get_title)
            if title_truncated:
                reasons.add('BOOKMARK_TITLE_LIMIT')
            dest = bookmark.get_dest()
            index = dest.get_index() if dest else None
            physical_page = index + 1 if index is not None and 0 <= index < len(doc) else None
            child = pdfium_c.FPDFBookmark_GetFirstChild(doc, raw)
            sibling = pdfium_c.FPDFBookmark_GetNextSibling(doc, raw)
            item_id = f'bookmark-{len(items) + 1}'
            children_truncated = bool(child) and level + 1 >= MAX_BOOKMARK_DEPTH
            items.append({'id': item_id, 'parent_id': parent_id, 'title': title, 'level': level,
                          'physical_page': physical_page, 'has_children': bool(child),
                          'title_truncated': title_truncated, 'children_truncated': children_truncated,
                          'destination_state': 'INTERNAL_PAGE' if physical_page else 'NO_INTERNAL_PAGE_DESTINATION'})
            if sibling:
                pending.append((sibling, level, parent_id))
            if children_truncated:
                reasons.add('BOOKMARK_DEPTH_LIMIT')
            elif child:
                pending.append((child, level + 1, item_id))
        for index in range(min(len(doc), MAX_PAGE_LABELS)):
            label, clipped = _navigation_text(
                pdfium_c.FPDF_GetPageLabel(doc, index, None, 0), lambda i=index: doc.get_page_label(i))
            labels.append({'physical_page': index + 1, 'page_label': label, 'truncated': clipped})
            if clipped:
                reasons.add('PAGE_LABEL_TEXT_LIMIT')
        if len(labels) < len(doc):
            reasons.add('PAGE_LABEL_COUNT_LIMIT')
        result = {'page_count': len(doc), 'bookmarks': items, 'page_labels': labels,
                  'truncated': bool(reasons), 'limit_reasons': sorted(reasons),
                  'bookmarks_complete': not any(r.startswith('BOOKMARK_') for r in reasons),
                  'page_labels_complete': not any(r.startswith('PAGE_LABEL_') for r in reasons),
                  'navigation_limits': {'max_bookmarks': MAX_BOOKMARKS, 'max_depth': MAX_BOOKMARK_DEPTH,
                                        'max_page_labels': MAX_PAGE_LABELS, 'max_text_chars': MAX_NAV_TEXT_CHARS},
                  'coverage_scope': 'PDFIUM_EXPOSED_NAVIGATION',
                  'navigation_scope': 'PDFium-exposed internal bookmark page targets; external targets are not followed',
                  'source_sha256': expected}
    if sha256_file(source) != expected:
        raise ValueError('Source changed while reading navigation')
    return result


def _match_snippet(text, char_index: int, char_count: int, total_chars: int) -> dict:
    # These are PDFium character indices, never Python offsets into extracted
    # text. Inserted/excluded PDF characters can make those coordinate spaces
    # differ, so a page-prefix slice can miss or misplace the actual match.
    context = max(0, min(120, (MAX_SNIPPET_CHARS - char_count) // 2))
    start = max(0, char_index - context)
    end = min(total_chars, char_index + char_count + context)
    count = min(end - start, MAX_SNIPPET_CHARS)
    state = 'TEXT_RANGE'
    try:
        snippet = text.get_text_range(start, count, errors='strict')
    except UnicodeDecodeError:
        snippet = text.get_text_range(start, count, errors='replace')
        state = 'DECODE_REPLACEMENT'
    return {'char_index': char_index, 'char_count': char_count, 'snippet': snippet,
            'snippet_char_index': start, 'snippet_char_count': count,
            'snippet_coordinate_system': 'PDFIUM_CHARACTER_INDEX', 'snippet_state': state}


def search_document(path: Path, expected: str, query: str, *, start_page: int = 1,
                    page_limit: int = DEFAULT_SEARCH_PAGES) -> dict:
    """Search a bounded page interval, returning the next unvisited page.

    Each call reports only its own interval. A caller may accumulate contiguous
    chunks for the same query and frozen source identity. Starting in the middle
    never claims earlier pages were searched; no-text pages need separate review
    or OCR and are not evidence that visible page content has no match.
    """
    if not isinstance(query, str) or not 1 <= len(query) <= 256 or '\x00' in query:
        raise ValueError('Search query must contain 1 to 256 characters')
    try:
        query.encode('utf-16-le')
    except UnicodeEncodeError as exc:
        raise ValueError('Search query must contain valid Unicode characters') from exc
    if type(start_page) is not int or start_page < 1:
        raise ValueError('Search start page must be a positive physical page number')
    if type(page_limit) is not int or not 1 <= page_limit <= MAX_SEARCH_PAGES:
        raise ValueError(f'Search page limit must be between 1 and {MAX_SEARCH_PAGES}')
    source, data = _read_frozen(path, expected)
    hits, no_text, unsearched, count_limited = [], [], [], []
    scanned = 0
    last_page = start_page - 1
    reasons = set()
    with closing(pdfium.PdfDocument(data)) as doc:
        page_count = len(doc)
        if start_page > page_count:
            raise ValueError('Search start page is outside this PDF')
        requested_end = min(page_count, start_page + page_limit - 1)
        for index in range(start_page - 1, requested_end):
            page_number = index + 1
            last_page = page_number
            try:
                with closing(doc[index]) as page, closing(page.get_textpage()) as text:
                    total_chars = text.count_chars()
                    if total_chars > MAX_TEXT_CHARS:
                        unsearched.append({'physical_page': page_number, 'reason': 'TEXT_CHAR_LIMIT'})
                        reasons.add('TEXT_CHAR_LIMIT')
                        continue
                    if total_chars == 0:
                        no_text.append(page_number)
                        scanned += 1
                        continue
                    count, first_hit, exact = 0, None, True
                    with closing(text.search(query)) as search:
                        while (hit := search.get_next()) is not None:
                            if count == MAX_PAGE_HITS:
                                exact = False
                                count_limited.append(page_number)
                                reasons.add('PAGE_MATCH_LIMIT')
                                break
                            if first_hit is None:
                                first_hit = hit
                            count += 1
                    if count:
                        label, label_clipped = _navigation_text(
                            pdfium_c.FPDF_GetPageLabel(doc, index, None, 0), lambda: doc.get_page_label(index))
                        item = {'physical_page': page_number, 'page_label': label, 'page_label_truncated': label_clipped,
                                'hit_count': count, 'hit_count_exact': exact,
                                'hit_count_lower_bound': count if exact else count + 1}
                        item.update(_match_snippet(text, *first_hit, total_chars))
                        hits.append(item)
                    scanned += 1
            except Exception as exc:
                unsearched.append({'physical_page': page_number, 'reason': 'PAGE_READ_ERROR',
                                   'error_type': type(exc).__name__, 'message': str(exc)[:240]})
                reasons.add('PAGE_READ_ERROR')
            if len(hits) >= MAX_SEARCH_HIT_PAGES and last_page < requested_end:
                reasons.add('MATCH_PAGE_LIMIT')
                break
        next_page = last_page + 1 if last_page < page_count else None
        if last_page == requested_end and next_page is not None:
            reasons.add('PAGE_BATCH_LIMIT')
        if start_page > 1:
            reasons.add('EARLIER_PAGES_NOT_IN_BATCH')
        coverage_complete = start_page == 1 and next_page is None and not unsearched
        results_complete = coverage_complete and not count_limited
        result = {'query': query, 'pages_scanned': scanned, 'page_count': page_count,
                  'matches': hits, 'truncated': not results_complete, 'source_sha256': expected,
                  'start_page': start_page, 'last_page_visited': last_page, 'next_page': next_page,
                  'pages_visited': last_page - start_page + 1, 'page_limit': page_limit,
                  'pages_without_text': no_text, 'unsearched_pages': unsearched,
                  'match_count_truncated_pages': count_limited, 'limit_reasons': sorted(reasons),
                  'batch_complete': last_page == requested_end and not unsearched,
                  'page_coverage_complete': coverage_complete, 'results_complete': results_complete,
                  'search_scope': 'Extractable text; no-text pages may be scanned or blank. OCR not performed'}
    if sha256_file(source) != expected:
        raise ValueError('Source changed while searching')
    return result
