from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ITEMS = [
    {
        "id": "NMPA-2026-08",
        "title": "国家药监局关于化学药品和生物制品全面实施药品电子通用技术文档申报的公告（2026年第8号）",
        "patterns": [r"2026年第8号", r"全面实施.*电子通用技术文档"],
        "required_for": ["effective_scope", "transition_date"],
        "binary_expected": False,
    },
    {
        "id": "CDE-2026-04",
        "title": "CDE eCTD V3.2.2相关技术文件通告（2026年第4号）",
        "patterns": [r"2026年第4号", r"发布eCTD V3\.2\.2相关技术文件"],
        "required_for": ["effective_technical_baseline"],
        "binary_expected": False,
    },
    {
        "id": "CDE-MAPPING-TABLE-V1.1",
        "title": "现行申报资料要求与eCTD目录元素、CTD目录层级对应表",
        "patterns": [r"现行申报资料要求.*eCTD目录元素", r"目录层级对应表"],
        "required_for": ["context_resolver", "node_mapping"],
        "binary_expected": True,
    },
    {
        "id": "CDE-TECH-SPEC-V1.1",
        "title": "eCTD技术规范V1.1",
        "patterns": [r"eCTD技术规范\s*V?1\.1"],
        "required_for": ["china_regional_structure", "pdf_semantics_cross_reference"],
        "binary_expected": True,
    },
    {
        "id": "CDE-TECH-ANNEX-V1.1",
        "title": "eCTD技术规范V1.1附件/实用文件包",
        "patterns": [r"技术规范.*附件", r"util", r"dtd", r"xsl", r"schema"],
        "required_for": ["xml_validation", "utility_files", "publisher_prototype"],
        "binary_expected": True,
    },
    {
        "id": "CDE-IMPLEMENTATION-GUIDE-V1.1",
        "title": "eCTD实施指南V1.1",
        "patterns": [r"eCTD实施指南\s*V?1\.1"],
        "required_for": ["submission_practice", "pdf_generation_guidance"],
        "binary_expected": True,
    },
    {
        "id": "CDE-VALIDATION-STANDARD-V1.1",
        "title": "eCTD验证标准V1.1",
        "patterns": [r"eCTD验证标准\s*V?1\.1"],
        "required_for": ["official_rule_catalog", "severity", "exceptions"],
        "binary_expected": True,
    },
    {
        "id": "CDE-VALIDATOR-V1.1.0",
        "title": "CDE eCTD验证软件V1.1.0安装包",
        "patterns": [r"eCTD验证软件", r"V?1\.1\.0", r"validator"],
        "required_for": ["official_black_box"],
        "binary_expected": True,
    },
    {
        "id": "CDE-VALIDATOR-MANUAL-V1.1.0",
        "title": "CDE eCTD验证软件V1.1.0操作手册",
        "patterns": [r"eCTD验证软件.*操作手册", r"验证软件.*用户手册", r"validator.*manual"],
        "required_for": ["official_black_box_protocol", "report_export"],
        "binary_expected": True,
    },
    {
        "id": "ICH-ECTD-3.2.2-SPEC",
        "title": "ICH eCTD v3.2.2 specification",
        "patterns": [r"eCTD.*3\.2\.2", r"electronic common technical document"],
        "required_for": ["international_backbone"],
        "binary_expected": True,
    },
    {
        "id": "ICH-ECTD-3.2.2-UTIL",
        "title": "ICH eCTD v3.2.2 DTD/XSL utility package",
        "patterns": [r"ich-ectd.*dtd", r"ectd-.*xsl", r"DTD", r"stylesheet"],
        "required_for": ["international_xml_validation"],
        "binary_expected": True,
    },
    {
        "id": "CN-CLEAN-BASELINE-SEQUENCE",
        "title": "经CDE V1.1.0验证无阻断问题的最小中国eCTD序列",
        "patterns": [r"sample.*sequence", r"示例.*序列", r"index\.xml", r"cn-regional\.xml"],
        "required_for": ["differential_black_box_cases"],
        "binary_expected": True,
        "requires_manual_proof": True,
    },
    {
        "id": "CDE-OFFICIAL-TRAINING",
        "title": "CDE官方eCTD V1.1培训材料、演示或操作视频",
        "patterns": [r"eCTD.*培训", r"eCTD.*操作视频", r"药审云课堂.*eCTD"],
        "required_for": ["operational_interpretation"],
        "binary_expected": False,
    },
]

OFFICIAL_HOSTS = {"www.cde.org.cn", "cde.org.cn", "www.nmpa.gov.cn", "nmpa.gov.cn", "www.ich.org", "ich.org"}
SECONDARY_HOSTS = {"www.cnpharm.com", "cnpharm.com", "cs.cnpharm.com", "www.pharmadj.com", "pharmadj.com"}


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def text_for(record: dict[str, Any]) -> str:
    values = []
    for key in ("url", "requested_url", "final_url", "source_url", "anchor_text", "file_name", "saved_as", "seed_role", "title", "role"):
        value = record.get(key)
        if value:
            values.append(str(value))
    archive = record.get("archive") or {}
    for member in archive.get("members", []):
        if isinstance(member, dict):
            values.append(str(member.get("name") or member.get("path") or ""))
    return " ".join(values)


def provenance(url: str | None) -> str:
    if not url:
        return "unknown"
    host = urlparse(url).netloc.lower()
    if host in OFFICIAL_HOSTS:
        return "official"
    if host in SECONDARY_HOSTS:
        return "secondary_mirror"
    return "other"


def matches(item: dict[str, Any], record: dict[str, Any]) -> bool:
    haystack = text_for(record)
    return all(any(re.search(pattern, haystack, re.I) for record_text in [haystack]) for pattern in item["patterns"][:1]) or any(
        re.search(pattern, haystack, re.I) for pattern in item["patterns"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, default=Path("evidence/regulatory/snapshots/cde-2026-v1.1/manifest.json"))
    parser.add_argument("--validator-inspection", type=Path, default=Path("evidence/regulatory/snapshots/cde-validator-v1.1.0/inspection.json"))
    parser.add_argument("--package-analysis", type=Path, default=Path("evidence/regulatory/snapshots/ectd-package-analysis/analysis.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/regulatory/P0_REGULATORY_EVIDENCE_COMPLETENESS.json"))
    args = parser.parse_args()

    source = load(args.source_manifest)
    validator = load(args.validator_inspection)
    packages = load(args.package_analysis)
    records = []
    for group in (source.get("pages", []), source.get("links", []), source.get("assets", []), source.get("seeds", []), source.get("secondary_mirrors", [])):
        records.extend(group)

    output_items = []
    for item in ITEMS:
        matched = [record for record in records if matches(item, record)]
        page_candidates = [record for record in matched if not record.get("download_status")]
        binaries = [record for record in matched if record.get("download_status") == "SUCCESS"]
        official_matches = [record for record in matched if provenance(record.get("final_url") or record.get("url") or record.get("requested_url")) == "official"]
        secondary_binaries = [record for record in binaries if provenance(record.get("final_url") or record.get("requested_url")) == "secondary_mirror"]
        status = "NOT_DISCOVERED"
        if binaries and official_matches:
            status = "OFFICIAL_BINARY_HASHED"
        elif secondary_binaries:
            status = "SECONDARY_MIRROR_BINARY_HASHED"
        elif official_matches or page_candidates:
            status = "PAGE_OR_LINK_CONFIRMED_BINARY_UNRESOLVED" if item["binary_expected"] else "PAGE_CONFIRMED"
        elif binaries:
            status = "NON_OFFICIAL_BINARY_CANDIDATE"

        if item["id"] == "CDE-VALIDATOR-V1.1.0" and validator:
            if validator.get("status") == "CANDIDATE_FOUND":
                status = "STATIC_CANDIDATE_FOUND_NEEDS_PROVENANCE_CONFIRMATION"
        if item["id"] == "CN-CLEAN-BASELINE-SEQUENCE":
            candidate_count = (packages.get("summary") or {}).get("sample_sequence_candidates", 0)
            status = "CANDIDATE_PACKAGE_OBSERVED_NOT_CDE_CLEAN" if candidate_count else "NOT_DISCOVERED"

        output_items.append({
            **item,
            "status": status,
            "page_or_link_candidates": len(page_candidates),
            "binary_candidates": len(binaries),
            "official_candidates": len(official_matches),
            "matched_records": [
                {
                    "url": record.get("final_url") or record.get("url") or record.get("requested_url"),
                    "anchor_or_role": record.get("anchor_text") or record.get("role") or record.get("seed_role"),
                    "saved_as": record.get("saved_as"),
                    "sha256": record.get("sha256"),
                    "download_status": record.get("download_status"),
                    "provenance": provenance(record.get("final_url") or record.get("url") or record.get("requested_url")),
                }
                for record in matched[:30]
            ],
        })

    counts: dict[str, int] = {}
    for item in output_items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    payload = {
        "schema_version": "0.1.0",
        "generated_by": "tools/regulatory/build_evidence_completeness.py",
        "policy": "No item is complete merely because a page title or secondary mirror was found. Official binary hashes and, where applicable, official-validator observations are separate gates.",
        "inputs": {
            "source_manifest_present": bool(source),
            "validator_inspection_present": bool(validator),
            "package_analysis_present": bool(packages),
        },
        "counts": counts,
        "items": output_items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# P0 regulatory evidence completeness ledger",
        "",
        "> A discovered page, a downloaded binary, parsed content, and an official black-box observation are different evidence states. This ledger does not collapse them into a single percentage.",
        "",
        "## Status counts",
        "",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines += [
        "",
        "## Asset ledger",
        "",
        "| ID | Required asset | Status | Binary candidates | Official candidates | Used for |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in output_items:
        lines.append(
            f"| `{item['id']}` | {item['title']} | `{item['status']}` | {item['binary_candidates']} | {item['official_candidates']} | {', '.join(item['required_for'])} |"
        )
    lines += [
        "",
        "## Exit interpretation",
        "",
        "P0-B0-A can pass with structured official rule excerpts and synthetic tests. P0-B0-B cannot pass until the V1.1.0 software/manual are hashed, a baseline sequence is proven clean by that software, and case reports are preserved. A secondary mirror can support continuity but never replaces official provenance where an official binary is required.",
        "",
    ]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
