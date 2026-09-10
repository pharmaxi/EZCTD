from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Any

RULE_RE = re.compile(
    r"^\s*((?:[1-5])(?:\.\d+)+)\s+((?:CN-)?eCTD4-\d+|CN-eCTD-\d+)\s+(.*?)\s+(错误|警告|提示信息)\s*$"
)

V11_TO_V4 = {
    "6.1": ["5.1"],
    "6.2": ["5.12"],
    "6.3": ["5.13"],
    "6.4": ["5.14"],
    "6.5": ["5.15"],
    "6.6": ["5.16"],
    "6.7": ["5.17"],
    "6.8": ["5.18"],
    "6.9": ["5.19"],
    "6.10": ["5.20"],
    "6.11": ["5.21"],
    "6.12": ["5.22"],
    "6.13": ["5.23"],
    "6.14": ["5.24"],
    "6.15": ["5.25"],
    "6.16": ["5.3"],
    "6.17": ["5.4"],
    "6.18": ["5.5"],
    "6.19": ["5.6"],
    "6.20": ["5.7"],
    "6.21": ["5.2"],
    "6.22": ["5.8"],
    "6.23": ["5.9", "5.10"],
    "6.24": ["5.11"],
    "6.25": ["5.26"],
    "6.26": ["5.27"],
}

V11_SEVERITY = {
    "6.1": "错误", "6.2": "错误", "6.3": "错误", "6.4": "错误", "6.5": "错误",
    "6.6": "错误", "6.7": "错误", "6.8": "警告", "6.9": "警告", "6.10": "错误",
    "6.11": "错误", "6.12": "错误", "6.13": "错误", "6.14": "错误", "6.15": "警告",
    "6.16": "警告", "6.17": "错误", "6.18": "提示信息", "6.19": "错误", "6.20": "警告",
    "6.21": "错误", "6.22": "提示信息", "6.23": "错误", "6.24": "警告", "6.25": "警告",
    "6.26": "警告",
}

SECTION_NAMES = {
    "1": "基本识别",
    "2": "文件、文件夹",
    "3": "消息",
    "4": "内容完整性",
    "5": "PDF分析",
}

V4_BASELINE_EXEMPTION_RULES = [
    "5.9", "5.12", "5.13", "5.14", "5.15", "5.16", "5.17", "5.18",
    "5.19", "5.20", "5.21", "5.22", "5.23", "5.24", "5.25",
]


def read_single(directory: Path, pattern: str) -> tuple[Path, str]:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected one {pattern}, got {[p.name for p in matches]}")
    return matches[0], matches[0].read_text(encoding="utf-8", errors="replace")


def parse_rules(text: str) -> list[dict[str, Any]]:
    rows = []
    for page_no, page in enumerate(text.split("\f"), 1):
        for line_no, line in enumerate(page.splitlines(), 1):
            match = RULE_RE.match(line)
            if not match:
                continue
            rows.append(
                {
                    "rule_id": match.group(1),
                    "message_code": match.group(2),
                    "title": " ".join(match.group(3).split()),
                    "severity": match.group(4),
                    "pdf_page": page_no,
                    "line": line_no,
                }
            )
    return rows


def code_index(text: str) -> dict[str, list[str]]:
    patterns = {
        "application_type": r"\bcnapt\d+\b",
        "submission_type": r"\bcnrat\d+\b",
        "submissionunit_type": r"\bcnsqt\d+\b",
        "product_type": r"\bcnprt\d+\b",
        "context_of_use": r"\bcn-[0-9a-z-]+\b",
        "contact_type": r"\bcn_contact_type\d+\b",
    }
    return {
        key: sorted(set(re.findall(pattern, text, re.I)), key=lambda value: (len(value), value))
        for key, pattern in patterns.items()
    }


def page_hits(text: str, terms: dict[str, list[str]]) -> dict[str, list[int]]:
    pages = text.split("\f")
    result = {}
    for key, variants in terms.items():
        result[key] = [
            index
            for index, page in enumerate(pages, 1)
            if any(variant.lower() in page.lower() for variant in variants)
        ]
    return result


def render_delta(payload: dict[str, Any]) -> str:
    totals = payload["validation_standard"]["totals"]
    sections = payload["validation_standard"]["sections"]
    pdf = payload["validation_standard"]["pdf_rules"]
    cv = payload["controlled_vocabulary"]["counts"]
    lines = [
        "# 中国 eCTD V3.2.2/V1.1 → v4.0 征求意见稿：结构化差异研究",
        "",
        "> 结论状态：**研究性差异分析，不是生效规则**。2026-05-27 发布的中国 eCTD v4.0 文件仍为公开征求意见稿；EZCTD 当前运行时规则包继续锁定 V3.2.2/V1.1。",
        "",
        "## 1. 证据基础",
        "",
    ]
    for source in payload["sources"]:
        lines.append(
            f"- `{source['source_id']}`：{source.get('pages') or '-'} 页，"
            f"SHA-256 `{source['sha256']}`。"
        )
    lines += [
        "",
        "## 2. v4.0 草案验证标准的实际规模",
        "",
        f"共识别 **{totals['rules']} 条**机器可定位规则："
        f"错误 {totals['错误']}、警告 {totals['警告']}、提示信息 {totals['提示信息']}。",
        "",
        "| 部分 | 规则数 | 错误 | 警告 | 提示信息 |",
        "|---|---:|---:|---:|---:|",
    ]
    for section_id in sorted(sections):
        item = sections[section_id]
        lines.append(
            f"| {section_id}. {SECTION_NAMES[section_id]} | {item['rules']} | "
            f"{item.get('错误', 0)} | {item.get('警告', 0)} | {item.get('提示信息', 0)} |"
        )
    lines += [
        "",
        "PDF 分析部分由现行 V1.1 的 26 条变为 **27 条**，但不是全面改写："
        "16 条错误和 2 条提示信息数量不变，警告由 8 条增至 9 条。新增量来自“基线类型资料大于 5 页”的独立警告规则。",
        "",
        "## 3. PDF 规则逐条映射",
        "",
        "| V1.1 | v4.0 草案 | v4.0 严重程度 | 变化判断 |",
        "|---|---|---|---|",
    ]
    pdf_by_id = {item["rule_id"]: item for item in pdf}
    for old_id in sorted(V11_TO_V4, key=lambda value: tuple(map(int, value.split(".")))):
        new_ids = V11_TO_V4[old_id]
        severities = "/".join(pdf_by_id[item]["severity"] for item in new_ids)
        if old_id == "6.23":
            change = "一拆二：普通资料仍为错误；基线类型单列为警告"
        elif any(item in V4_BASELINE_EXEMPTION_RULES for item in new_ids):
            change = "规则主体延续；增加基线类型适用性例外"
        elif all(pdf_by_id[item]["severity"] == V11_SEVERITY[old_id] for item in new_ids):
            change = "严重程度延续；编号/顺序调整"
        else:
            change = "严重程度发生变化，需人工复核"
        lines.append(f"| {old_id} | {', '.join(new_ids)} | {severities} | {change} |")
    lines += [
        "",
        "### 关键差异",
        "",
        "1. **基线类型资料被显式建模。** v4.0 草案 5.10 对基线类型中大于 5 页但没有书签的 PDF 给出警告；普通资料仍由 5.9 作为错误处理。",
        "2. **书签和超文本链接规则增加基线例外。** 5.12–5.25 对基线类型、参考文献和外文参考资料不作相应要求。该例外不能回写到现行 V1.1。",
        "3. **规则内容高度继承，但编号重排。** 密码、版本、附件、注释、安全设置、初始视图、Fast Web View 被提前排列；书签和链接规则整体后移。",
        "4. **标题和严重程度必须分开建模。** 5.9 的标题使用“建议添加书签”，但严重程度为错误，解释文字使用强制语气；实现不能依据标题中的“建议”降低严重程度。",
        "5. **v4.0 仍保留独立的 PDF 分析层。** v4.0 的 XML/消息模型变化并没有消除 PDF 质量规则。",
        "",
        "## 4. 受控词汇规模",
        "",
        "| 词汇域 | 唯一代码数 |",
        "|---|---:|",
    ]
    for key, label in [
        ("application_type", "申请类型"),
        ("submission_type", "提交类型"),
        ("submissionunit_type", "提交单元类型"),
        ("product_type", "产品类型"),
        ("context_of_use", "使用情境"),
        ("contact_type", "联系人类型"),
    ]:
        lines.append(f"| {label} | {cv[key]} |")
    lines += [
        "",
        f"合计识别 **{sum(cv.values())} 个**唯一代码。使用情境代码 {cv['context_of_use']} 个，已覆盖模块一、模块二以及 `3.2.R.1–3.2.R.6` 等中国区域节点。",
        "",
        "## 5. 对产品架构的直接影响",
        "",
        "### 可以共用的基础设施",
        "",
        "- 不可变来源登记、哈希与下载证据；",
        "- PDF 只读观察器和渲染复验；",
        "- XML 安全解析、文件图和相对路径处理；",
        "- 受控词汇加载器；",
        "- Finding、Evidence、RulePack、ApplicabilityContext 的通用数据结构。",
        "",
        "### 必须分开的运行时模型",
        "",
        "- V3.2.2 的 `index.xml + cn-regional.xml + leaf/lifecycle operation` 模型；",
        "- v4.0 的 Submission Unit、Context of Use、Document Reference、Keyword、UUID、Priority Number 和文档复用模型；",
        "- 两个版本的验证消息代码、适用性和严重程度；",
        "- V3.2.2→v4.0 的向前兼容转换，不得等同于普通“升级 XML”。",
        "",
        "## 6. 实施决策",
        "",
        "1. 当前产品 profile 继续为 `cn-cde-ectd-v3.2.2-v1.1`。",
        "2. v4.0 草案 profile 固定为 `cn-cde-ectd-v4.0-draft-2026-05-27`，`runtime_enabled=false`。",
        "3. 现阶段只允许研究：解析、差异、数据模型预留和测试语料设计；禁止生成可提交 v4.0 序列或给出官方合规结论。",
        "4. 正式文件发布后，重新做逐字差异、受控词汇差异和验证器黑盒校准；不得直接把征求意见稿改名为正式规则包。",
        "",
        "## 7. 下一轮实验",
        "",
        "- 对 27 条 v4.0 PDF 草案规则建立与现行 26 条的同源 fixture 映射，验证唯一新增维度确为 baseline applicability。",
        "- 对 165 条验证消息建立 section/code/severity 索引，但不接入生产扫描器。",
        "- 为 Submission Unit、Context of Use、Document Reference、Keyword 和 UUID 建立只读解析原型。",
        "- 从官方验证软件 V1.1.0 取得现行 V3.2.2 黑盒结果，先完成当前版本，而不是被 v4.0 研究分散。",
        "",
    ]
    return "\n".join(lines)


def render_adr() -> str:
    return """# ADR-0002：现行 V3.2.2 与中国 eCTD v4.0 征求意见稿严格隔离

- Status: Accepted
- Date: 2026-09-04

## Context

中国现行 eCTD V3.2.2 相关技术文件 V1.1 已生效；CDE 于 2026-05-27 发布中国 eCTD v4.0 指导原则、受控词汇和验证标准的公开征求意见稿。二者共享 PDF、文件和验证基础设施，但消息模型、生命周期表达、受控词汇和适用性并不相同。

## Decision

1. `cn-cde-ectd-v3.2.2-v1.1` 是当前唯一可进入实现和官方校准的中国运行时 profile。
2. `cn-cde-ectd-v4.0-draft-2026-05-27` 只作为研究 profile，必须标记 `runtime_enabled=false`。
3. 不允许 v4.0 草案规则、baseline 例外或消息代码回流到现行 6.1–6.26 规则。
4. 共用的只限于中性基础设施：来源证据、哈希、XML 安全解析、PDF 观察器、文件图、Finding/Evidence 数据模型。
5. v4.0 的 Submission Unit、Context of Use、Document Reference、Keyword、UUID 和复用关系采用独立模型。
6. 最终版发布后必须重新获取原始文件、固定哈希、逐条差异并完成官方验证器校准，不能将草案直接升格。

## Consequences

- 短期增加 profile 隔离和版本路由代码，但避免草案污染现行结果。
- v4.0 研究可提前验证数据模型，不影响 P0 的现行验证器目标。
- 所有界面和报告必须同时显示地区、标准版本、文件状态和生效状态。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--text-dir",
        type=Path,
        default=Path("build/official-source-deep-dive/pdf-text-v4-validated"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("rulepacks/cn-cde-ectd-v4.0-draft/2026-05-27/manifest.json"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("evidence/regulatory/snapshots/user-supplied-official-sources"),
    )
    parser.add_argument(
        "--delta",
        type=Path,
        default=Path("docs/validation/V1_1_TO_V4_DRAFT_DELTA.md"),
    )
    parser.add_argument(
        "--adr",
        type=Path,
        default=Path("docs/decisions/0002-isolate-cn-ectd-v4-draft-profile.md"),
    )
    args = parser.parse_args()

    validation_path, validation_text = read_single(args.text_dir, "*VALIDATION-STANDARD.txt")
    cv_path, cv_text = read_single(args.text_dir, "*CONTROLLED-VOCABULARY.txt")
    guidance_path, guidance_text = read_single(args.text_dir, "*GUIDANCE.txt")
    rationale_path, rationale_text = read_single(args.text_dir, "*RATIONALE.txt")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    rules = parse_rules(validation_text)
    if len(rules) != 165:
        raise RuntimeError(f"expected 165 rule rows, got {len(rules)}")
    total_severity = collections.Counter(item["severity"] for item in rules)
    if dict(total_severity) != {"提示信息": 6, "错误": 145, "警告": 14}:
        raise RuntimeError(f"unexpected severity counts: {total_severity}")

    sections: dict[str, dict[str, int]] = {}
    for section_id in SECTION_NAMES:
        subset = [item for item in rules if item["rule_id"].split(".")[0] == section_id]
        counter = collections.Counter(item["severity"] for item in subset)
        sections[section_id] = {"rules": len(subset), **dict(counter)}
    expected_sections = {"1": 3, "2": 18, "3": 106, "4": 11, "5": 27}
    if {key: value["rules"] for key, value in sections.items()} != expected_sections:
        raise RuntimeError(f"unexpected section counts: {sections}")

    pdf_rules = [item for item in rules if item["rule_id"].startswith("5.")]
    if [item["rule_id"] for item in pdf_rules] != [f"5.{i}" for i in range(1, 28)]:
        raise RuntimeError("PDF rule sequence is not 5.1–5.27")
    pdf_counter = collections.Counter(item["severity"] for item in pdf_rules)
    if dict(pdf_counter) != {"错误": 16, "警告": 9, "提示信息": 2}:
        raise RuntimeError(f"unexpected PDF severity counts: {pdf_counter}")

    codes = code_index(cv_text)
    expected_cv = {
        "application_type": 4,
        "submission_type": 9,
        "submissionunit_type": 26,
        "product_type": 2,
        "context_of_use": 63,
        "contact_type": 3,
    }
    counts = {key: len(value) for key, value in codes.items()}
    if counts != expected_cv:
        raise RuntimeError(f"unexpected CV counts: {counts}")

    source_index = {item["source_id"]: item for item in sources}
    semantic_sources = [
        {
            "source_id": key,
            "sha256": source_index[key]["sha256"],
            "pages": source_index[key].get("pages"),
            "size": source_index[key].get("size"),
        }
        for key in [
            "CDE-CN-V4-DRAFT-GUIDANCE",
            "CDE-CN-V4-DRAFT-CONTROLLED-VOCABULARY",
            "CDE-CN-V4-DRAFT-VALIDATION-STANDARD",
            "CDE-CN-V4-DRAFT-RATIONALE",
        ]
    ]

    payload = {
        "schema_version": "0.1.0",
        "status": "DRAFT_RESEARCH_ONLY",
        "profile_id": manifest["profile_id"],
        "runtime_enabled": False,
        "sources": semantic_sources,
        "validation_standard": {
            "text_artifact": validation_path.name,
            "totals": {"rules": len(rules), **dict(total_severity)},
            "sections": sections,
            "rules": rules,
            "pdf_rules": pdf_rules,
            "v11_to_v4_pdf_rule_map": V11_TO_V4,
            "baseline_applicability_rules": V4_BASELINE_EXEMPTION_RULES,
            "key_finding": "V1.1 rule 6.23 is split into v4 draft 5.9 error for ordinary material and 5.10 warning for baseline material.",
        },
        "controlled_vocabulary": {
            "text_artifact": cv_path.name,
            "counts": counts,
            "total_unique_codes": sum(counts.values()),
            "codes": codes,
        },
        "guidance": {
            "text_artifact": guidance_path.name,
            "page_hits": page_hits(
                guidance_text,
                {
                    "submission_unit": ["提交单元", "Submission Unit"],
                    "context_of_use": ["使用情境", "Context of Use"],
                    "document_reference": ["文档引用", "Document Reference"],
                    "uuid": ["UUID"],
                    "priority_number": ["优先级编号", "Priority Number"],
                    "reuse": ["复用", "重用"],
                    "forward_compatibility": ["向前兼容"],
                    "electronic_seal": ["电子签章"],
                },
            ),
        },
        "rationale": {
            "text_artifact": rationale_path.name,
            "page_hits": page_hits(
                rationale_text,
                {
                    "ich_version_1_6": ["1.6", "2024 年 5 月 21 日"],
                    "work_started": ["2025 年 12 月"],
                    "first_draft": ["2026 年 3 月"],
                    "fifteen_chapters": ["15 个章节"],
                    "five_validation_parts": ["五个部分"],
                },
            ),
        },
        "decision": "Keep v4 draft isolated from the effective V3.2.2/V1.1 runtime profile.",
    }

    args.evidence.mkdir(parents=True, exist_ok=True)
    args.delta.parent.mkdir(parents=True, exist_ok=True)
    args.adr.parent.mkdir(parents=True, exist_ok=True)
    (args.evidence / "V4_DRAFT_SEMANTIC_ANALYSIS.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.delta.write_text(render_delta(payload), encoding="utf-8")
    args.adr.write_text(render_adr(), encoding="utf-8")
    print(
        json.dumps(
            {
                "rules": len(rules),
                "severity": dict(total_severity),
                "sections": sections,
                "pdf_rules": len(pdf_rules),
                "pdf_severity": dict(pdf_counter),
                "controlled_vocabulary": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
