from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAX_BYTES = 500 * 1024 * 1024
USER_AGENT = "EZCTD-official-source-deep-dive/0.2 (+https://github.com/laojia-a/EZCTD)"

V4_TERMS = {
    "hl7_rps": ["HL7", "RPS"],
    "submission_unit": ["submission unit", "submission-unit", "提交单元"],
    "context_of_use": ["context of use", "contextOfUse", "使用情境"],
    "document_reference": ["document reference", "documentReference", "文档引用"],
    "uuid": ["UUID"],
    "controlled_vocabulary": ["受控词汇", "controlled vocabulary"],
    "keyword": ["keyword", "关键词"],
    "reuse": ["reuse", "复用", "重用"],
    "lifecycle": ["生命周期", "life cycle", "lifecycle"],
    "validation": ["验证标准", "validation"],
    "priority_number": ["优先编号", "priority number"],
    "status_code": ["状态码", "status code"],
}

EXPECTED_ROLES = {
    "guidance": "cn_ectd_v4_draft_guidance",
    "controlled_vocabulary": "cn_ectd_v4_draft_controlled_vocabulary",
    "validation_standard": "cn_ectd_v4_draft_validation_standard",
    "rationale": "cn_ectd_v4_draft_rationale",
    "feedback_form": "cn_ectd_v4_draft_feedback_form",
}


def run(command: list[str], *, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout, check=check)


def hash_file(path: Path, algorithm: str) -> str | None:
    try:
        value = hashlib.new(algorithm)
    except ValueError:
        return None
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def safe_name(value: str) -> str:
    value = urllib.parse.unquote(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    return value.strip(" .")[:180] or "download"


def magic_kind(path: Path) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"MZ"):
        return "pe"
    return "unknown"


def classify(text: str, url: str, index: int) -> tuple[str, str, str]:
    haystack = f"{text} {urllib.parse.unquote(url)}"
    if "反馈表" in haystack:
        return "CDE-CN-V4-DRAFT-FEEDBACK", "feedback_form", EXPECTED_ROLES["feedback_form"]
    if "起草说明" in haystack:
        return "CDE-CN-V4-DRAFT-RATIONALE", "rationale", EXPECTED_ROLES["rationale"]
    if "附件1" in haystack or "受控词汇" in haystack:
        return "CDE-CN-V4-DRAFT-CONTROLLED-VOCABULARY", "controlled_vocabulary", EXPECTED_ROLES["controlled_vocabulary"]
    if "附件2" in haystack or "验证标准" in haystack:
        return "CDE-CN-V4-DRAFT-VALIDATION-STANDARD", "validation_standard", EXPECTED_ROLES["validation_standard"]
    if "指导原则" in haystack:
        return "CDE-CN-V4-DRAFT-GUIDANCE", "guidance", EXPECTED_ROLES["guidance"]
    return f"CDE-CN-V4-DRAFT-UNCLASSIFIED-{index:02d}", "unclassified", "cn_ectd_v4_draft_unclassified"


def download(url: str, output: Path, source_id: str, displayed_name: str) -> tuple[Path, dict[str, Any]]:
    output.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(url).path).suffix
    if not suffix:
        suffix = Path(displayed_name).suffix
    filename = safe_name(displayed_name) if displayed_name else safe_name(Path(urllib.parse.urlparse(url).path).name)
    if "." not in filename and suffix:
        filename += suffix
    destination = output / f"{source_id}--{filename}"
    with tempfile.TemporaryDirectory(prefix="ezctd-v4-") as td:
        temp = Path(td) / "body"
        proc = run([
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--retry", "4", "--retry-all-errors", "--connect-timeout", "30",
            "--max-time", "300", "--max-filesize", str(MAX_BYTES),
            "-A", USER_AGENT, "-o", str(temp), url,
        ], timeout=330, check=False)
        if proc.returncode != 0 or not temp.exists():
            raise RuntimeError(f"curl failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-2000:]}")
        size = temp.stat().st_size
        if size == 0 or size > MAX_BYTES:
            raise RuntimeError(f"invalid download size: {size}")
        shutil.copy2(temp, destination)
    return destination, {
        "requested_url": url,
        "filename": destination.name,
        "size": destination.stat().st_size,
        "kind": magic_kind(destination),
        "sha256": hash_file(destination, "sha256"),
        "sm3": hash_file(destination, "sm3"),
        "downloaded_at_epoch": int(time.time()),
    }


def pdf_record(path: Path, text_dir: Path) -> dict[str, Any]:
    text_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, str] = {}
    info = run(["pdfinfo", str(path)], timeout=90, check=False) if shutil.which("pdfinfo") else None
    if info:
        for line in info.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
    text_path = text_dir / f"{path.stem}.txt"
    text_proc = run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(text_path)], timeout=180, check=False) if shutil.which("pdftotext") else None
    pages = int(metadata["Pages"]) if metadata.get("Pages", "").isdigit() else None
    return {
        "status": "SUCCESS" if info and info.returncode == 0 and text_proc and text_proc.returncode == 0 else "PARTIAL",
        "pages": pages,
        "metadata": metadata,
        "text_file": text_path.name if text_path.exists() else None,
        "pdfinfo_stderr": info.stderr[-1000:] if info else "pdfinfo missing",
        "pdftotext_stderr": text_proc.stderr[-1000:] if text_proc else "pdftotext missing",
    }


def docx_text(path: Path) -> str:
    if not zipfile.is_zipfile(path):
        return ""
    with zipfile.ZipFile(path) as archive:
        try:
            raw = archive.read("word/document.xml")
        except KeyError:
            return ""
    root = ET.fromstring(raw)
    return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))


def term_hits(text: str) -> dict[str, list[dict[str, Any]]]:
    pages = text.split("\f")
    output: dict[str, list[dict[str, Any]]] = {}
    for key, variants in V4_TERMS.items():
        hits: list[dict[str, Any]] = []
        for page_no, page in enumerate(pages, 1):
            compact = " ".join(page.split())
            matched = [term for term in variants if term.lower() in compact.lower()]
            if matched:
                positions = [compact.lower().find(term.lower()) for term in matched]
                first = min(value for value in positions if value >= 0)
                hits.append({
                    "physical_page": page_no,
                    "matched_terms": matched,
                    "context": compact[max(0, first - 100):min(len(compact), first + 260)],
                })
        output[key] = hits[:12]
    return output


def merge_json(path: Path, dynamic_records: list[dict[str, Any]]) -> None:
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    existing = {item.get("source_id"): item for item in payload.get("discovered_sources", [])}
    for item in dynamic_records:
        existing[item["source_id"]] = item
    payload["discovered_sources"] = sorted(existing.values(), key=lambda item: item.get("source_id", ""))
    payload.setdefault("controls", {})["dynamic_discovery"] = "Selenium/Xvfb rendered official CDE pages; exact anchor URLs only"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_readme(records: list[dict[str, Any]]) -> str:
    lines = [
        "# China eCTD v4.0 consultation package", "",
        "> Status: **DRAFT / RESEARCH ONLY**. These files were published for public consultation on 2026-05-27 and are not activated in the effective China eCTD V3.2.2/V1.1 runtime profile.", "",
        "## Official attachments", "", "| Role | File | Pages | SHA-256 |", "|---|---|---:|---|",
    ]
    for item in records:
        lines.append(f"| `{item['role_key']}` | {item['displayed_name']} | {item.get('pdf',{}).get('pages','')} | `{item['sha256']}` |")
    lines += [
        "", "## Isolation contract", "",
        "- Profile ID: `cn-cde-ectd-v4.0-draft-2026-05-27`.",
        "- `runtime_enabled=false`.",
        "- No v4 rule, severity, controlled vocabulary or data model field may alter `cn-cde-ectd-v3.2.2-v1.1-pdf` behavior.",
        "- Neutral infrastructure may be shared: source ledger, archive safety, XML parser, evidence reports, typed identifiers and worker isolation.",
        "- Final China v4.0 documents will require a fresh source freeze and formal draft-to-final delta.",
        "", "## Architectural consequences", "",
        "- Preserve a profile boundary around XML/data models rather than treating v4 as a directory-template update.",
        "- Prepare for UUID-based identifiers, document references/reuse, context-of-use metadata and larger controlled vocabularies, but keep these types dormant in the current runtime.",
        "- Validator message identity and severity must remain versioned by profile and source hash.", "",
    ]
    return "\n".join(lines)


def render_delta(records: list[dict[str, Any]]) -> str:
    lines = [
        "# eCTD v4.0 draft: initial evidence-led delta notes", "",
        "> This is a research inventory, not an implementation specification. It reports concepts found in the official consultation files and intentionally does not rewrite the current V3.2.2 rule pack.", "",
    ]
    for item in records:
        lines += [f"## {item['displayed_name']}", "", f"- Role: `{item['role_key']}`", f"- SHA-256: `{item['sha256']}`", f"- Pages: {item.get('pdf',{}).get('pages','n/a')}"]
        found = {key: sorted({hit['physical_page'] for hit in values}) for key, values in item.get("term_hits", {}).items() if values}
        if found:
            lines += [f"- `{key}`: physical PDF pages {pages}" for key, pages in found.items()]
        else:
            lines.append("- No configured v4 concept terms found or asset is not a PDF.")
        lines.append("")
    lines += [
        "## Current decision", "",
        "Do not start a v4 publisher implementation from these keyword locators. First build a typed model and perform document-by-document extraction of cardinalities, identifiers, operation semantics, validation messages and controlled vocabularies.", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, default=Path("build/official-source-deep-dive/browser-discovery/dynamic-link-discovery.json"))
    parser.add_argument("--assets", type=Path, default=Path("build/official-source-deep-dive/assets"))
    parser.add_argument("--text", type=Path, default=Path("build/official-source-deep-dive/pdf-text"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/user-supplied-official-sources"))
    parser.add_argument("--profile", type=Path, default=Path("rulepacks/cn-cde-ectd-v4.0-draft/2026-05-27"))
    args = parser.parse_args()
    for directory in (args.assets, args.text, args.evidence, args.profile):
        directory.mkdir(parents=True, exist_ok=True)

    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    candidates = [
        item for item in discovery.get("download_candidates", [])
        if item.get("source_id") == "CDE-CN-V4-DRAFT-NOTICE"
    ]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for index, candidate in enumerate(candidates, 1):
        source_id, role_key, role = classify(candidate.get("text", ""), candidate["url"], index)
        try:
            path, record = download(candidate["url"], args.assets, source_id, candidate.get("text", ""))
            record.update({
                "source_id": source_id,
                "role_key": role_key,
                "role": role,
                "status": "official_draft",
                "source_page": candidate.get("source_url"),
                "displayed_name": candidate.get("text", ""),
                "discovery_method": candidate.get("source", "browser-anchor"),
                "download_status": "SUCCESS",
            })
            if record["kind"] == "pdf":
                record["pdf"] = pdf_record(path, args.text)
                text_path = args.text / record["pdf"]["text_file"] if record["pdf"].get("text_file") else None
                text = text_path.read_text(encoding="utf-8", errors="replace") if text_path and text_path.exists() else ""
                record["term_hits"] = term_hits(text)
            elif record["kind"] == "zip" and Path(candidate.get("text", "")).suffix.lower() == ".docx":
                text = docx_text(path)
                record["docx"] = {"text_length": len(text), "text_excerpt": text[:4000]}
                record["term_hits"] = term_hits(text)
            records.append(record)
            seen_roles.add(role_key)
        except Exception as exc:
            failure = {
                "source_id": source_id,
                "role_key": role_key,
                "role": role,
                "requested_url": candidate["url"],
                "displayed_name": candidate.get("text", ""),
                "download_status": "FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            }
            records.append(failure)
            failures.append(failure)

    manifest = {
        "schema_version": "0.2.0",
        "profile_id": "cn-cde-ectd-v4.0-draft-2026-05-27",
        "profile_status": "draft_research_only",
        "published_date": "2026-05-27",
        "notice_url": "https://www.cde.org.cn/main/news/viewInfoCommon/7898f68946d8e8e44d074657c7112002",
        "runtime_enabled": False,
        "must_not_influence": ["cn-cde-ectd-v3.2.2-v1.1-pdf", "cn-cde-ectd-v3.2.2-v1.1-package"],
        "expected_roles": EXPECTED_ROLES,
        "retrieved_roles": sorted(seen_roles),
        "sources": [{
            "source_id": item.get("source_id"),
            "role_key": item.get("role_key"),
            "role": item.get("role"),
            "url": item.get("requested_url"),
            "displayed_name": item.get("displayed_name"),
            "sha256": item.get("sha256"),
            "sm3": item.get("sm3"),
            "kind": item.get("kind"),
            "pages": item.get("pdf", {}).get("pages"),
            "download_status": item.get("download_status"),
        } for item in records],
        "implementation_policy": "Evidence and delta research only; no production rule activation.",
    }
    (args.evidence / "V4_OFFICIAL_ATTACHMENTS.json").write_text(json.dumps({"records": records, "failures": failures}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.evidence / "V4_DRAFT_DELTA_RESEARCH.md").write_text(render_delta(records), encoding="utf-8")
    (args.profile / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.profile / "README.md").write_text(render_readme(records), encoding="utf-8")
    merge_json(args.evidence / "SOURCE_DEEP_DIVE.json", records)

    summary_path = args.evidence / "SUMMARY.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary.update({
        "discovered_success": sum(item.get("download_status") == "SUCCESS" for item in records),
        "discovered_total": len(records),
        "v4_assets": sum(item.get("download_status") == "SUCCESS" for item in records),
        "v4_expected_roles": len(EXPECTED_ROLES),
        "v4_retrieved_roles": len(seen_roles),
        "v4_failures": len(failures),
    })
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    missing = set(EXPECTED_ROLES) - seen_roles
    if failures or missing or len(records) != 5:
        print(json.dumps({"missing_roles": sorted(missing), "records": len(records), "failures": failures}, ensure_ascii=False, indent=2))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
