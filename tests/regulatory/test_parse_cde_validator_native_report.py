from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_module() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "tools/regulatory/parse_cde_validator_native_report.py"
    spec = importlib.util.spec_from_file_location("parse_cde_validator_native_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report_html(timestamp: str, report_name: str) -> str:
    return f"""<!doctype html>
<html>
<head><title>eCTD 验证报告</title><style>.x{{color:red}}</style></head>
<body>
<table>
  <tr><th>申请编号</th><td></td></tr>
  <tr><th>序列号</th><td>0001</td></tr>
  <tr><th>验证标准</th><td>中国eCTD验证标准V1.1</td></tr>
  <tr><th>执行日期/时间</th><td>{timestamp}</td></tr>
</table>
<table>
  <tr><th>标准章节</th><th>提示信息</th><th>警告</th><th>错误</th></tr>
  <tr><th>基本识别</th><td>1</td><td>0</td><td>0</td></tr>
  <tr><th>PDF分析</th><td>0</td><td>1</td><td>1</td></tr>
  <tr><th>统计</th><td>1</td><td>1</td><td>1</td></tr>
</table>
<table>
  <tr>
    <td><svg><path fill="#3592E2"></path></svg></td>
    <th>1.1</th><td>显示文件数量。</td>
  </tr>
  <tr><td></td><td>详情共计1条</td></tr>
  <tr><td></td><td>文件数量：0</td></tr>
  <tr>
    <td><svg><path fill="#F25858"></path></svg></td>
    <th>6.1</th><td>PDF文件不得损坏。</td>
  </tr>
  <tr><td></td><td>详情共计1条</td></tr>
  <tr><td></td><td>C:/probe/{report_name} 无法读取</td></tr>
</table>
</body>
</html>"""


def test_semantic_hash_ignores_volatile_execution_fields(tmp_path: Path) -> None:
    module = load_module()
    first = tmp_path / "evReport--0001-20260904.html"
    second = tmp_path / "evReport--0001-20260905.html"
    first.write_text(
        report_html("2026-09-04 02:40:47", first.name),
        encoding="utf-8",
    )
    second.write_text(
        report_html("2026-09-05 09:10:11", second.name),
        encoding="utf-8",
    )

    left = module.build_payload(first)
    right = module.build_payload(second)

    assert left["source"]["sha256"] != right["source"]["sha256"]
    assert (
        left["normalization"]["normalized_visible_text_sha256"]
        == right["normalization"]["normalized_visible_text_sha256"]
    )
    assert (
        left["normalization"]["semantic_contract_sha256"]
        == right["normalization"]["semantic_contract_sha256"]
    )


def test_parser_extracts_totals_rules_severity_and_details(tmp_path: Path) -> None:
    module = load_module()
    report = tmp_path / "report.html"
    report.write_text(
        report_html("2026-09-04 02:40:47", "evReport--0001-20260904.html"),
        encoding="utf-8",
    )

    payload = module.build_payload(report)

    assert payload["metadata"]["验证标准"] == "中国eCTD验证标准V1.1"
    assert payload["summary"]["totals"] == {"提示信息": 1, "警告": 1, "错误": 1}
    assert payload["rule_count"] == 2
    assert payload["rules"][0] == {
        "code": "1.1",
        "severity": "提示信息",
        "requirement": "显示文件数量。",
        "declared_detail_count": 1,
        "details": ["文件数量：0"],
        "observed_detail_rows": 1,
    }
    assert payload["rules"][1]["code"] == "6.1"
    assert payload["rules"][1]["severity"] == "错误"
    assert payload["rules"][1]["declared_detail_count"] == 1
