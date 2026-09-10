from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import types
import pytest
from ezctd.cli import main
from ezctd.cde_report import parse_report
from ezctd.safe_io import UnsafeOutputError, validate_new_output, write_new_text


def sample_report(*, details=True) -> bytes:
    rows = []
    for n in range(1, 27):
        status = '#F25858' if n == 12 and details else '#3592E2' if n == 18 else '#3BBC86'
        rows.append(f'<tr><td><svg><path fill="{status}"></path></svg></td><td>6.{n}</td><td>规则{n}</td></tr>')
        if n == 12 and details:
            rows += ['<tr><td></td><td colspan="2">详情共计 1 条</td></tr>',
                     '<tr><td></td><td colspan="2"><div>失效链接</div><ul><li>./clinical/report.pdf</br>页码：[2]，超链接：[10, 20, 30, 40]</li></ul></td></tr>']
    html = '<html><head><script>throw new Error("DO NOT EXECUTE");</script></head><body><table>'
    html += '<tr><th>序列号</th><td>缺失区域性骨架文件！</td></tr>'
    html += f'<tr><td><a href="#section_6">6-PDF分析</a></td><td>0</td><td>0</td><td>{1 if details else 0}</td></tr></table>'
    html += '<div id="section_6">6-PDF分析</div><table>' + ''.join(rows) + '</table></body></html>'
    return html.encode()


@pytest.mark.parametrize('kind', ['same', 'hardlink', 'symlink', 'existing-report'])
def test_cli_rejects_existing_aliases_before_scan(tmp_path, kind):
    src = tmp_path / 'source' / 'input.pdf'; src.parent.mkdir(); src.write_bytes(b'%PDF-test-protected')
    target = tmp_path / 'out.json'
    try:
        if kind == 'same': target = src
        elif kind == 'hardlink': os.link(src, target)
        elif kind == 'symlink': target.symlink_to(src)
        else: target.write_text('EXISTING REPORT')
    except OSError as exc:
        pytest.skip(str(exc))
    before = src.read_bytes(); old = target.read_bytes()
    assert main(['scan-pdf', str(src), '--output', str(target)]) == 2
    assert src.read_bytes() == before and target.read_bytes() == old


def test_reject_input_tree_output(tmp_path):
    src = tmp_path / 'input.pdf'; src.write_bytes(b'protected')
    assert main(['scan-pdf', str(src), '--output', str(tmp_path / 'nested' / 'report.json')]) == 2
    assert not (tmp_path / 'nested').exists()


def test_reject_linked_parent(tmp_path):
    real = tmp_path / 'real'; real.mkdir(); alias = tmp_path / 'alias'
    try: alias.symlink_to(real, target_is_directory=True)
    except OSError as exc: pytest.skip(str(exc))
    with pytest.raises(UnsafeOutputError): write_new_text(alias / 'report.json', '{}')
    assert list(real.iterdir()) == []


def test_publish_complete_new_file_and_reject_second_write(tmp_path):
    output = tmp_path / 'out' / 'report.json'
    write_new_text(output, '{"ok":true}')
    assert json.loads(output.read_text(encoding="utf-8")) == {'ok': True}
    with pytest.raises(UnsafeOutputError): write_new_text(output, 'bad')
    assert len(list(output.parent.iterdir())) == 1


def test_publish_fails_closed_if_hardlinks_unavailable(tmp_path, monkeypatch):
    def fail(*a, **kw): raise OSError('no hardlinks')
    monkeypatch.setattr(os, 'link', fail)
    with pytest.raises(OSError): write_new_text(tmp_path / 'r.json', '{}')
    assert list(tmp_path.iterdir()) == []


def test_report_without_backbone_is_importable():
    p = parse_report(sample_report())
    assert p['parse_state'] == 'PARSED_COUNTS_RECONCILED'
    assert p['section_summary_as_reported']['错误'] == 1
    assert len(p['rules']) == 26 and p['distinct_reported_pdf_paths'] == 1
    assert p['local_pdf_validation_performed'] is False
    assert p['metadata_as_reported']['序列号'] == '缺失区域性骨架文件！'


def test_info_icon_without_details_not_invented_finding():
    rule = parse_report(sample_report())['rules'][17]
    assert rule['report_icon_status'] == '提示信息'
    assert rule['imported_observation_state'] == 'NO_DETAILS_REPORTED'
    assert rule['declared_detail_count'] is None and rule['items'] == []


def test_broken_br_tag_preserves_coordinates_and_path():
    item = parse_report(sample_report())['rules'][11]['items'][0]
    assert item['path_as_reported'] == './clinical/report.pdf'
    assert item['reported_page_raw'] == '2'
    assert item['reported_rect_raw'] == '10, 20, 30, 40'
    assert item['locator_verified_against_pdf'] is False


@pytest.mark.parametrize('change,expected', [
    (lambda b: b.replace(b'<td>6.1</td>', b'<td>6.2</td>'), 'PDF_RULE_SET_MISSING_DUPLICATE_OR_UNKNOWN'),
    (lambda b: b.replace('详情共计 1 条'.encode(), '详情共计 3 条'.encode()), '6.12:DECLARED_DETAIL_VS_ITEM_COUNT_MISMATCH'),
    (lambda b: b.replace(b'#F25858', b'#abcdef'), '6.12:UNKNOWN_STATUS_ICON'),
    (lambda b: b.replace(b'./clinical/report.pdf', b'./clinical/report.xyz'), '6.12:UNPARSED_DETAIL_LOCATOR'),
    (lambda b: b.replace(b'href="#section_6"', b'href="#section_7"'), 'PDF_SUMMARY_MISSING'),
])
def test_report_incomplete_not_success(change, expected):
    p = parse_report(change(sample_report()))
    assert p['parse_state'] == 'IMPORT_INCOMPLETE'
    assert expected in p['parse_issues']


def test_fonts_raw_commas_not_split_into_fake_fonts():
    b = sample_report().replace('页码：[2]，超链接：[10, 20, 30, 40]'.encode(), '不合规字体：[Arial,Bold, Times New Roman,Bold]'.encode())
    assert parse_report(b)['rules'][11]['items'][0]['reported_font_list_raw'] == 'Arial,Bold, Times New Roman,Bold'


def test_empty_document_incomplete():
    assert parse_report(b'<html></html>')['parse_state'] == 'IMPORT_INCOMPLETE'


def test_invalid_encoding_rejected():
    with pytest.raises(UnicodeDecodeError): parse_report(b'\xff\xfe')


def test_external_targets_remain_inert_text():
    b = sample_report().replace(b'./clinical/report.pdf', b'file:///not-authorized/report.pdf')
    result = parse_report(b)
    assert result['rules'][11]['items'][0]['path_as_reported'] == 'file:///not-authorized/report.pdf'
    assert result['rules'][11]['items'][0]['local_file_identity'] == 'UNBOUND'


def test_import_cli_preserves_input_and_uses_no_pdf_dependencies(tmp_path):
    source_dir = tmp_path / 'source'; source_dir.mkdir(); source = source_dir / 'report.html'
    source.write_bytes(sample_report()); before = source.read_bytes(); out = tmp_path / 'out.json'
    assert main(['import-cde-report', str(source), '--output', str(out)]) == 0
    assert source.read_bytes() == before
    p = json.loads(out.read_text(encoding="utf-8")); assert p['input_integrity']['unchanged'] is True
    assert p['detail_totals_reconciled'] == {'提示信息': 0, '警告': 0, '错误': 1}


def test_unqualified_clean_scan_not_success_code(tmp_path, pdf_factory):
    # Actual native worker: missing submission context is not a clean result.
    source = pdf_factory(tmp_path / 'input' / 'sample.pdf')
    out = tmp_path / 'out.json'
    assert main(['scan-pdf', str(source), '--output', str(out)]) == 3
    result = json.loads(out.read_text(encoding='utf-8'))
    assert result['compliance_conclusion'] == 'NOT_ESTABLISHED'
    assert any(row['status'] == 'INDETERMINATE' for row in result['rule_evaluations'])


def test_missing_input_explicit_error(tmp_path):
    assert main(['scan-pdf', str(tmp_path / 'missing.pdf')]) == 2


def test_existing_source_tree_report_untouched(tmp_path):
    source = tmp_path / 'report.html'; source.write_bytes(sample_report()); before = source.read_bytes()
    assert main(['import-cde-report', str(source), '--output', str(source)]) == 2
    assert source.read_bytes() == before
