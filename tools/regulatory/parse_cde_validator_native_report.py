from __future__ import annotations

"""Parse a CDE eCTD validator native HTML report into a stable semantic summary.

The validator embeds execution timestamps and generated report names in every
HTML report, so byte identity is not an appropriate repeatability criterion.
This parser preserves the raw byte hash while also emitting two normalized
hashes:

* normalized visible text, after removing presentation-only markup and volatile
  execution metadata;
* a typed semantic contract containing the selected validation standard,
  section totals, rule codes, severity, requirements and detail messages.

Only structured summaries should be committed.  The raw native report remains
in the immutable GitHub Actions artifact.
"""

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SEVERITY_BY_FILL = {
    "#3592e2": "提示信息",
    "#fa8c16": "警告",
    "#f25858": "错误",
    "#3bbc86": "通过",
}
RULE_CODE = re.compile(r"^\d+(?:\.\d+){1,3}$")
DETAIL_COUNT = re.compile(r"详情共计\s*(\d+)\s*条")
DATETIME = re.compile(r"20\d{2}[-/]\d{2}[-/]\d{2}\s+\d{2}:\d{2}:\d{2}")
REPORT_NAME = re.compile(r"evReport--[^\s/\\<>]+?\.html", re.I)
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/][^\s<>]+)")


def collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(value: str) -> str:
    value = DATETIME.sub("<EXECUTION_DATETIME>", value)
    value = REPORT_NAME.sub("<REPORT_FILE>", value)
    value = ABSOLUTE_PATH.sub("<ABSOLUTE_PATH>", value)
    return "\n".join(collapse(line) for line in value.splitlines() if collapse(line))


class ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.visible_parts: list[str] = []
        self.tables: list[list[dict[str, Any]]] = []
        self.current_table: list[dict[str, Any]] | None = None
        self.current_row: dict[str, Any] | None = None
        self.current_cell: dict[str, Any] | None = None
        self.current_section: list[str] | None = None
        self.sections: list[str] = []
        self.title_parts: list[str] | None = None
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        if tag in {"style", "script", "svg"}:
            self.skip_depth += 1
        if tag == "title":
            self.title_parts = []
        if tag == "div" and "alert-subTitle" in attrs_map.get("class", "").split():
            self.current_section = []
        if tag == "table":
            self.current_table = []
        elif tag == "tr" and self.current_table is not None:
            self.current_row = {"cells": [], "fills": []}
        elif tag in {"td", "th"} and self.current_row is not None:
            self.current_cell = {"text_parts": [], "fills": [], "tag": tag}
        elif tag == "path" and self.current_row is not None:
            fill = attrs_map.get("fill", "").lower()
            if fill:
                self.current_row["fills"].append(fill)
                if self.current_cell is not None:
                    self.current_cell["fills"].append(fill)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title" and self.title_parts is not None:
            self.title = collapse(" ".join(self.title_parts))
            self.title_parts = None
        if tag == "div" and self.current_section is not None:
            text = collapse(" ".join(self.current_section))
            if text:
                self.sections.append(text)
            self.current_section = None
        if tag in {"td", "th"} and self.current_cell is not None and self.current_row is not None:
            self.current_cell["text"] = collapse(" ".join(self.current_cell.pop("text_parts")))
            self.current_row["cells"].append(self.current_cell)
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None and self.current_table is not None:
            if self.current_row["cells"]:
                self.current_table.append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.current_table is not None:
            self.tables.append(self.current_table)
            self.current_table = None

    def handle_data(self, data: str) -> None:
        if self.title_parts is not None:
            self.title_parts.append(data)
        if self.current_section is not None:
            self.current_section.append(data)
        if self.current_cell is not None:
            self.current_cell["text_parts"].append(data)
        if not self.skip_depth:
            text = collapse(data)
            if text:
                self.visible_parts.append(text)


def first_severity(row: dict[str, Any]) -> str | None:
    for fill in row.get("fills", []):
        if fill in SEVERITY_BY_FILL:
            return SEVERITY_BY_FILL[fill]
    return None


def cell_texts(row: dict[str, Any]) -> list[str]:
    return [cell.get("text", "") for cell in row.get("cells", [])]


def parse_metadata(tables: list[list[dict[str, Any]]]) -> dict[str, str]:
    for table in tables:
        values: dict[str, str] = {}
        for row in table:
            cells = cell_texts(row)
            if len(cells) >= 2 and cells[0] in {
                "申请编号",
                "序列号",
                "相关序列",
                "申请类型",
                "产品类型",
                "验证标准",
                "执行日期/时间",
            }:
                values[cells[0]] = cells[1]
        if "验证标准" in values:
            return values
    return {}


def parse_summary(tables: list[list[dict[str, Any]]]) -> dict[str, Any]:
    for table in tables:
        if not table:
            continue
        header = cell_texts(table[0])
        if header[:4] != ["标准章节", "提示信息", "警告", "错误"]:
            continue
        sections = []
        totals: dict[str, int] | None = None
        for row in table[1:]:
            cells = cell_texts(row)
            if len(cells) < 4:
                continue
            try:
                counts = {
                    "提示信息": int(cells[1]),
                    "警告": int(cells[2]),
                    "错误": int(cells[3]),
                }
            except ValueError:
                continue
            if cells[0] == "统计":
                totals = counts
            else:
                sections.append({"section": cells[0], **counts})
        return {"sections": sections, "totals": totals or {}}
    return {"sections": [], "totals": {}}


def parse_rules(tables: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for table in tables:
        for row in table:
            cells = cell_texts(row)
            code_index = next(
                (index for index, value in enumerate(cells) if RULE_CODE.fullmatch(value)),
                None,
            )
            if code_index is not None and code_index + 1 < len(cells):
                current = {
                    "code": cells[code_index],
                    "severity": first_severity(row),
                    "requirement": cells[code_index + 1],
                    "declared_detail_count": 0,
                    "details": [],
                }
                rules.append(current)
                continue
            if current is None:
                continue
            joined = collapse(" ".join(cells))
            match = DETAIL_COUNT.search(joined)
            if match:
                current["declared_detail_count"] = int(match.group(1))
                continue
            # Detail rows normally start with an empty icon cell.  This guard
            # keeps summary and metadata tables from leaking into a rule.
            if cells and cells[0] == "" and len(cells) >= 2:
                detail = collapse(" ".join(cells[1:]))
                if detail and detail != current["requirement"]:
                    current["details"].append(detail)
    for rule in rules:
        rule["details"] = list(dict.fromkeys(rule["details"]))
        rule["observed_detail_rows"] = len(rule["details"])
    return rules


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_payload(report: Path) -> dict[str, Any]:
    raw = report.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    parser = ReportParser()
    parser.feed(text)
    metadata = parse_metadata(parser.tables)
    summary = parse_summary(parser.tables)
    rules = parse_rules(parser.tables)
    normalized_visible = normalize_text("\n".join(parser.visible_parts))
    semantic_contract = {
        "title": parser.title,
        "validator_standard": metadata.get("验证标准"),
        "summary": summary,
        "rules": rules,
    }
    semantic_json = json.dumps(
        semantic_contract,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "schema_version": "0.1.0",
        "source": {
            "file_name": report.name,
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "metadata": metadata,
        "sections": parser.sections,
        "summary": summary,
        "rule_count": len(rules),
        "rules": rules,
        "normalization": {
            "removed_or_replaced": [
                "execution datetime",
                "generated report filename",
                "absolute local paths",
                "HTML markup, scripts, styles and SVG glyph geometry",
                "non-semantic whitespace",
            ],
            "normalized_visible_text_sha256": sha256_text(normalized_visible),
            "semantic_contract_sha256": sha256_text(semantic_json),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    totals = payload["summary"]["totals"]
    lines = [
        "# CDE eCTD 验证器原生报告语义摘要",
        "",
        f"- 原始文件：`{payload['source']['file_name']}`",
        f"- 原始 SHA-256：`{payload['source']['sha256']}`",
        f"- 验证标准：{payload['metadata'].get('验证标准', 'n/a')}",
        f"- 可见规则条目：{payload['rule_count']}",
        f"- 提示信息 / 警告 / 错误：{totals.get('提示信息', 0)} / "
        f"{totals.get('警告', 0)} / {totals.get('错误', 0)}",
        f"- 规范化可见文本摘要：`{payload['normalization']['normalized_visible_text_sha256']}`",
        f"- 结构化语义摘要：`{payload['normalization']['semantic_contract_sha256']}`",
        "",
        "## 分章节统计",
        "",
        "| 章节 | 提示信息 | 警告 | 错误 |",
        "|---|---:|---:|---:|",
    ]
    for row in payload["summary"]["sections"]:
        lines.append(
            f"| {row['section']} | {row['提示信息']} | {row['警告']} | {row['错误']} |"
        )
    lines += [
        "",
        "> 该摘要用于比较同一冻结输入的重复运行。原始 HTML 报告因执行时间等字段不同，不要求逐字节一致；稳定性判断使用规范化可见文本和结构化规则结果。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    payload = build_payload(args.report)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "totals": payload["summary"]["totals"],
                "rule_count": payload["rule_count"],
                "semantic_contract_sha256": payload["normalization"]["semantic_contract_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
