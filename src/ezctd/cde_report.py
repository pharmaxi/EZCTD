"""Read CDE HTML report tables as data, never as an executable web page.

Only report observations are imported. No referenced PDF is opened, no URL is
fetched, no exemption is applied and no PDF rule is claimed locally verified.
Font strings retain commas because commas may be part of font variant names.
"""
from __future__ import annotations
from collections import Counter
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Any

COLORS = {'#3592e2': '提示信息', '#fa8c16': '警告', '#f25858': '错误', '#3bbc86': '通过'}
EXPECTED = {f'6.{n}' for n in range(1, 27)}
MAX_BYTES = 32 * 1024 * 1024


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self.row: dict[str, Any] | None = None
        self.cell: dict[str, Any] | None = None
        self.li: list[str] | None = None
        self.section: str | None = None
        self.ignored: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if self.ignored:
            return
        if tag in {'script', 'style'}:
            self.ignored = tag
            return
        ident = a.get('id') or ''
        if ident.startswith('section_'):
            self.section = ident.removeprefix('section_')
        if tag == 'tr':
            self.row = {'section': self.section, 'cells': []}
            self.cell = None
            self.li = None
        elif tag in {'td', 'th'} and self.row is not None:
            self.cell = {'kind': tag, 'text': [], 'items': [], 'fills': [], 'anchors': []}
            self.row['cells'].append(self.cell)
        elif self.cell is not None:
            if tag == 'li':
                self.li = []
            if tag in {'br', 'div', 'p'}:
                self._text('\n')
            if tag == 'path' and a.get('fill'):
                self.cell['fills'].append(a['fill'].lower())
            if tag == 'a' and a.get('href'):
                self.cell['anchors'].append(a['href'])

    def _text(self, value: str) -> None:
        if self.cell is not None:
            self.cell['text'].append(value)
        if self.li is not None:
            self.li.append(value)

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self._text(data)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag == self.ignored:
                self.ignored = None
            return
        if tag == 'br':  # Some CDE reports contain </br>, not <br>.
            self._text('\n')
        elif tag == 'li' and self.cell is not None and self.li is not None:
            self.cell['items'].append(''.join(self.li).strip())
            self.li = None
        elif tag in {'td', 'th'}:
            self.cell = None
            self.li = None
        elif tag == 'tr' and self.row is not None:
            if len(self.rows) >= 200000:
                raise ValueError('Report table row limit exceeded')
            self.rows.append(self.row)
            self.row = None
            self.cell = None


def _plain(cell: dict[str, Any]) -> str:
    return ' '.join(''.join(cell['text']).split())


def _item(raw: str) -> dict[str, Any]:
    match = re.match(r'\s*(.*?\.pdf)(?=\s*(?:页码|不合规字体|$))', raw, re.I | re.S)
    page = re.search(r'页码[：:]\s*\[([^]]*)\]', raw)
    rect = re.search(r'超链接[：:]\s*\[([^]]*)\]', raw)
    font = re.search(r'不合规字体[：:]\s*\[([^]]*)\]', raw)
    return {
        'raw_text': raw,
        'path_as_reported': match.group(1).strip() if match else None,
        'reported_page_raw': page.group(1) if page else None,
        'reported_rect_raw': rect.group(1) if rect else None,
        'reported_font_list_raw': font.group(1) if font else None,
        'locator_verified_against_pdf': False,
        'local_file_identity': 'UNBOUND',
    }


def parse_report(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_BYTES:
        raise ValueError('Report exceeds 32 MiB import limit')
    parser = _Tables()
    parser.feed(raw.decode('utf-8-sig', errors='strict'))
    parser.close()
    metadata: dict[str, str] = {}
    summary: dict[str, int] | None = None
    rules: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in parser.rows:
        cells = row['cells']
        if len(cells) == 2 and cells[0]['kind'] == 'th':
            metadata[_plain(cells[0])] = _plain(cells[1])
        if len(cells) == 4 and '#section_6' in cells[0]['anchors']:
            values = [_plain(c) for c in cells[1:]]
            if all(v.isdigit() for v in values):
                summary = dict(zip(('提示信息', '警告', '错误'), map(int, values)))
        if row['section'] != '6':
            continue
        if len(cells) == 3 and re.fullmatch(r'6\.\d+', _plain(cells[1])):
            status = next((COLORS[c] for c in cells[0]['fills'] if c in COLORS), 'UNKNOWN')
            current = {
                'rule_id': _plain(cells[1]), 'requirement_as_reported': _plain(cells[2]),
                'report_icon_status': status, 'declared_detail_count': None,
                'detail_blocks': [], 'items': [], 'local_evaluation': 'NOT_RUN',
            }
            rules.append(current)
        elif current is not None and cells:
            detail = _plain(cells[-1])
            count = re.fullmatch(r'详情共计\s*(\d+)\s*条', detail)
            if count:
                current['declared_detail_count'] = int(count.group(1))
            elif detail:
                current['detail_blocks'].append(detail)
                current['items'].extend(_item(x) for x in cells[-1]['items'])
    issues: list[str] = []
    ids = [r['rule_id'] for r in rules]
    if set(ids) != EXPECTED or len(ids) != 26:
        issues.append('PDF_RULE_SET_MISSING_DUPLICATE_OR_UNKNOWN')
    totals: Counter[str] = Counter()
    all_paths: set[str] = set()
    for r in rules:
        count = r['declared_detail_count']
        observed = len(r['items'])
        if count is not None and count != observed:
            issues.append(f"{r['rule_id']}:DECLARED_DETAIL_VS_ITEM_COUNT_MISMATCH")
        if count is None and r['detail_blocks']:
            issues.append(f"{r['rule_id']}:DETAILS_WITHOUT_DECLARED_COUNT")
        if r['report_icon_status'] == 'UNKNOWN':
            issues.append(f"{r['rule_id']}:UNKNOWN_STATUS_ICON")
        if any(x['path_as_reported'] is None for x in r['items']):
            issues.append(f"{r['rule_id']}:UNPARSED_DETAIL_LOCATOR")
        # Preserve icon status separately: info icon without detail is NOT a finding.
        r['imported_observation_state'] = (
            'DETAILS_REPORTED' if (count or observed) else
            'REPORT_PASS' if r['report_icon_status'] == '通过' else 'NO_DETAILS_REPORTED'
        )
        paths = {x['path_as_reported'] for x in r['items'] if x['path_as_reported'] is not None}
        r['unique_reported_paths'] = len(paths)
        all_paths.update(paths)
        if count:
            totals[r['report_icon_status']] += count
    reconciled = {key: totals.get(key, 0) for key in ('提示信息', '警告', '错误')}
    if summary is None:
        issues.append('PDF_SUMMARY_MISSING')
    elif summary != reconciled:
        issues.append('PDF_SUMMARY_VS_DETAILS_MISMATCH')
    return {
        'schema_version': '0.1.0', 'source_kind': 'USER_SUPPLIED_CDE_HTML_REPORT',
        'source_sha256': hashlib.sha256(raw).hexdigest(), 'source_bytes': len(raw),
        'source_authenticity_independently_verified': False,
        'validator_binary_identity': 'NOT_PROVIDED', 'metadata_as_reported': metadata,
        'section': '6-PDF分析', 'section_summary_as_reported': summary,
        'detail_totals_reconciled': reconciled, 'distinct_reported_pdf_paths': len(all_paths),
        'parse_state': 'PARSED_COUNTS_RECONCILED' if not issues else 'IMPORT_INCOMPLETE',
        'parse_issues': issues, 'rules': rules,
        'local_pdf_validation_performed': False, 'pdf_files_modified': 0,
        'scope_note': 'Imported report observations only; no whole-submission or current-PDF compliance conclusion.',
    }


def load_report(path: Path) -> dict[str, Any]:
    with path.open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    return parse_report(raw)
