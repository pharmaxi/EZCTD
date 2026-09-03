from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

USER_AGENT = "EZCTD-official-source-deep-dive/0.1 (+https://github.com/laojia-a/EZCTD)"
MAX_BYTES = 500 * 1024 * 1024

SOURCES = [
    {
        "source_id": "CDE-ECTD-COLUMN",
        "url": "https://www.cde.org.cn/ectd/index",
        "role": "official_ectd_portal",
        "status": "official_current_portal",
    },
    {
        "source_id": "CDE-CN-V1.1-SPEC-PDF",
        "url": "https://www.cde.org.cn/ectd/guideDownLoads/eCTDJSGFV1.1.pdf?name=eCTD%E6%8A%80%E6%9C%AF%E8%A7%84%E8%8C%83V1.1.0.pdf",
        "role": "effective_cn_ectd_v3_2_2_technical_specification",
        "status": "official_effective",
    },
    {
        "source_id": "CDE-CN-V1.1-SPEC-ATTACHMENTS",
        "url": "https://www.cde.org.cn/ectd/guideDownLoads/eCTDJSGFV1.1FJ.zip?name=eCTD%E6%8A%80%E6%9C%AF%E8%A7%84%E8%8C%83V1.1%E9%99%84%E4%BB%B6%E5%8C%85.zip",
        "role": "effective_cn_ectd_v3_2_2_technical_attachment_package",
        "status": "official_effective",
    },
    {
        "source_id": "CDE-CN-V4-DRAFT-NOTICE",
        "url": "https://www.cde.org.cn/main/news/viewInfoCommon/7898f68946d8e8e44d074657c7112002",
        "role": "cn_ectd_v4_draft_notice",
        "status": "official_draft_notice",
    },
]

V1_1_SECONDARY_MAP = {
    "6.1": ["technical-specification §5 PDF/document integrity context"],
    "6.2": ["technical-specification §3.4 document navigation and cross-document link portability"],
    "6.3": ["technical-specification §3.4 navigation boundaries; no cross-application links"],
    "6.4": ["technical-specification §3.4 navigation behavior; PDF action semantics remain implementation detail"],
    "6.5": ["technical-specification §3.4 usable document navigation"],
    "6.6": ["technical-specification §3.4 valid internal/cross-document destinations"],
    "6.7": ["technical-specification §3.4 deterministic navigation"],
    "6.8": ["technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 navigation recommendations"],
    "6.9": ["technical-specification §3.4 cross-document link portability"],
    "6.10": ["technical-specification §3.4 navigation boundaries; no cross-application links"],
    "6.11": ["technical-specification §3.4 navigation behavior; PDF action semantics remain implementation detail"],
    "6.12": ["technical-specification §3.4 usable document navigation"],
    "6.13": ["technical-specification §3.4 valid internal/cross-document destinations"],
    "6.14": ["technical-specification §3.4 deterministic navigation"],
    "6.15": ["technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 navigation recommendations"],
    "6.16": ["technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 version guidance"],
    "6.17": ["technical-specification §5 PDF restrictions"],
    "6.18": ["technical-specification §5 PDF restrictions and navigation annotations"],
    "6.19": ["technical-specification §5 PDF security restrictions"],
    "6.20": ["technical-specification §5 initial-view recommendations"],
    "6.21": ["technical-specification §5 PDF security restrictions"],
    "6.22": ["technical-specification §5 optimization/Fast Web View recommendations"],
    "6.23": ["technical-specification §5 China-specific requirement: files over five pages need TOC/bookmarks, subject to exceptions"],
    "6.24": ["technical-specification §5 PDF restrictions on dynamic content"],
    "6.25": ["technical-specification §5 searchable text and OCR recommendations"],
    "6.26": ["technical-specification §5 font embedding recommendations"],
}

KEY_TERMS_V1_1 = {
    "pdf_file_format": ["PDF 文件", "PDF文件", "文件格式规范"],
    "five_page_bookmark": ["超过五页", "大于5页", "五页"],
    "cross_document_links": ["跨文档", "超文本链接"],
    "cross_application_links": ["跨申请"],
    "chinese_font": ["宋体"],
    "link_appearance": ["蓝色文字", "蓝色框"],
    "foreign_reference": ["外文参考资料"],
    "electronic_seal": ["电子签章"],
    "md5": ["MD5", "md5"],
}

KEY_TERMS_V4 = {
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
}


@dataclass
class Link:
    source_url: str
    url: str
    text: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


def run(command: list[str], *, timeout: int = 180, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout, check=check)


def digest(path: Path, algorithm: str) -> str | None:
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


def parse_headers(path: Path) -> dict[str, str]:
    headers: dict[str, str] = {}
    current: dict[str, str] = {}
    for raw in path.read_text(encoding="latin-1", errors="replace").splitlines():
        line = raw.strip("\r")
        if line.startswith("HTTP/"):
            current = {}
            headers = current
        elif ":" in line:
            key, value = line.split(":", 1)
            current[key.strip().lower()] = value.strip()
    return headers


def file_kind(path: Path) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(b"MZ"):
        return "pe"
    if data.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        return "html"
    return "unknown"


def filename_from(headers: dict[str, str], url: str, fallback: str) -> str:
    disposition = headers.get("content-disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if match:
        return safe_name(urllib.parse.unquote(match.group(1)))
    match = re.search(r'filename="?([^";]+)', disposition, re.I)
    if match:
        return safe_name(match.group(1).strip())
    query_name = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("name")
    if query_name:
        return safe_name(query_name[0])
    return safe_name(Path(urllib.parse.urlparse(url).path).name or fallback)


def download(url: str, destination_dir: Path, source_id: str) -> tuple[Path, dict[str, Any]]:
    destination_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ezctd-curl-") as td:
        temp = Path(td)
        body = temp / "body"
        headers_path = temp / "headers"
        command = [
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--retry", "4", "--retry-all-errors", "--connect-timeout", "30",
            "--max-time", "300", "--max-filesize", str(MAX_BYTES),
            "-A", USER_AGENT, "-D", str(headers_path), "-o", str(body), url,
        ]
        proc = run(command, timeout=330, check=False)
        headers = parse_headers(headers_path) if headers_path.exists() else {}
        if proc.returncode != 0 or not body.exists():
            raise RuntimeError(f"curl failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-2000:]}")
        size = body.stat().st_size
        if size == 0 or size > MAX_BYTES:
            raise RuntimeError(f"invalid download size: {size}")
        filename = filename_from(headers, url, source_id)
        kind = file_kind(body)
        if "." not in filename:
            filename += {"pdf": ".pdf", "zip": ".zip", "rar": ".rar", "7z": ".7z", "html": ".html", "pe": ".exe"}.get(kind, "")
        output = destination_dir / f"{source_id}--{filename}"
        shutil.copy2(body, output)
        return output, {
            "source_id": source_id,
            "requested_url": url,
            "content_type": headers.get("content-type"),
            "content_disposition": headers.get("content-disposition"),
            "filename": output.name,
            "size": size,
            "kind": kind,
            "sha256": digest(output, "sha256"),
            "sm3": digest(output, "sm3"),
            "downloaded_at_epoch": int(time.time()),
        }


def extract_links(source_url: str, html_text: str) -> list[Link]:
    parser = LinkParser()
    parser.feed(html_text)
    found: dict[str, Link] = {}
    for href, text in parser.links:
        if href:
            url = urllib.parse.urljoin(source_url, html.unescape(href))
            if urllib.parse.urlparse(url).scheme in {"http", "https"}:
                found[url] = Link(source_url, url, text)
    for pattern in [r'https?://[^"\'<> ]+', r'/(?:ectd/guideDownLoads|main/att/download)/[^"\'<> )]+']:
        for match in re.finditer(pattern, html_text, re.I):
            token = html.unescape(match.group(0).rstrip(".,;]"))
            url = urllib.parse.urljoin(source_url, token)
            found.setdefault(url, Link(source_url, url, "embedded-url"))
    return list(found.values())


def pdf_info(path: Path, output_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"status": "NOT_RUN", "pages": None, "text_file": None}
    if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
        record["status"] = "TOOLS_MISSING"
        return record
    info = run(["pdfinfo", str(path)], timeout=90, check=False)
    metadata: dict[str, str] = {}
    for line in info.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    text_path = output_dir / f"{path.stem}.txt"
    text_proc = run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(text_path)], timeout=180, check=False)
    record.update({
        "status": "SUCCESS" if info.returncode == 0 and text_proc.returncode == 0 else "PARTIAL",
        "pages": int(metadata["Pages"]) if metadata.get("Pages", "").isdigit() else None,
        "metadata": metadata,
        "text_file": text_path.name if text_path.exists() else None,
        "pdfinfo_stderr": info.stderr[-1000:],
        "pdftotext_stderr": text_proc.stderr[-1000:],
    })
    return record


def term_hits(text_path: Path | None, terms: dict[str, list[str]]) -> dict[str, Any]:
    if not text_path or not text_path.exists():
        return {key: [] for key in terms}
    pages = text_path.read_text(encoding="utf-8", errors="replace").split("\f")
    result: dict[str, list[dict[str, Any]]] = {}
    for key, variants in terms.items():
        hits: list[dict[str, Any]] = []
        for page_no, page in enumerate(pages, 1):
            compact = " ".join(page.split())
            matched = [term for term in variants if term.lower() in compact.lower()]
            if matched:
                first = min(compact.lower().find(term.lower()) for term in matched)
                hits.append({
                    "pdf_page": page_no,
                    "matched_terms": matched,
                    "context": compact[max(0, first - 90):min(len(compact), first + 220)],
                })
        result[key] = hits[:8]
    return result


def archive_inventory(path: Path, extraction_root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"status": "NOT_ARCHIVE", "members": [], "extracted": []}
    kind = file_kind(path)
    extract_dir = extraction_root / path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "zip":
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                for item in infos:
                    target = (extract_dir / item.filename).resolve()
                    if extract_dir.resolve() not in target.parents and target != extract_dir.resolve():
                        raise RuntimeError(f"unsafe archive path: {item.filename}")
                archive.extractall(extract_dir)
                record["members"] = [{"name": item.filename, "size": item.file_size, "compressed_size": item.compress_size} for item in infos]
        elif kind in {"rar", "7z"}:
            seven = shutil.which("7z") or shutil.which("7zz")
            if not seven:
                record["status"] = "ARCHIVE_TOOL_MISSING"
                return record
            proc = run([seven, "x", "-y", f"-o{extract_dir}", str(path)], timeout=240, check=False)
            if proc.returncode != 0:
                record.update({"status": "EXTRACT_FAILED", "error": (proc.stderr or proc.stdout)[-2000:]})
                return record
        else:
            return record
        record["extracted"] = [
            {
                "relative_path": member.relative_to(extract_dir).as_posix(),
                "size": member.stat().st_size,
                "kind": file_kind(member),
                "sha256": digest(member, "sha256"),
                "sm3": digest(member, "sm3"),
            }
            for member in sorted(p for p in extract_dir.rglob("*") if p.is_file())
        ]
        record["status"] = "EXTRACTED"
    except Exception as exc:
        record.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    return record


def role_for_discovered(link: Link) -> tuple[str, str] | None:
    haystack = f"{link.text} {urllib.parse.unquote(link.url)}".lower()
    if not re.search(r"\.(?:pdf|zip|rar|7z|exe|msi|xlsx|docx)(?:$|\?)|/main/att/download/|/ectd/guidedownloads/", link.url, re.I):
        return None
    if "v4.0" in haystack or "v4" in haystack:
        if "验证标准" in haystack:
            return "CDE-CN-V4-DRAFT-VALIDATION", "cn_ectd_v4_draft_validation_standard"
        if "受控词汇" in haystack:
            return "CDE-CN-V4-DRAFT-CV", "cn_ectd_v4_draft_controlled_vocabulary"
        if "起草说明" in haystack:
            return "CDE-CN-V4-DRAFT-RATIONALE", "cn_ectd_v4_draft_rationale"
        if "反馈表" in haystack:
            return "CDE-CN-V4-DRAFT-FEEDBACK", "cn_ectd_v4_draft_feedback_form"
        return "CDE-CN-V4-DRAFT-GUIDANCE", "cn_ectd_v4_draft_guidance"
    if "验证软件操作手册" in haystack or ("验证软件" in haystack and "手册" in haystack):
        return "CDE-VALIDATOR-MANUAL-CANDIDATE", "validator_manual_candidate"
    if "验证软件" in haystack:
        return "CDE-VALIDATOR-BINARY-CANDIDATE", "validator_binary_candidate"
    if "验证标准" in haystack:
        return "CDE-CN-V1.1-VALIDATION-STANDARD-CANDIDATE", "validation_standard_candidate"
    if "实施指南" in haystack:
        return "CDE-CN-V1.1-IMPLEMENTATION-GUIDE-CANDIDATE", "implementation_guide_candidate"
    return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_manifest(records: list[dict[str, Any]], discovered: list[dict[str, Any]]) -> str:
    lines = [
        "# User-supplied official eCTD sources — deep-dive manifest", "",
        "> Generated from the exact CDE URLs supplied by the project owner. Raw binaries are stored as a GitHub Actions artifact; the repository stores hashes, inventories, locators and analysis.", "",
        "## Direct sources", "", "| Source ID | Status | Kind | Bytes | SHA-256 |", "|---|---|---:|---:|---|",
    ]
    for item in records:
        lines.append(f"| `{item['source_id']}` | {item.get('download_status', 'SUCCESS')} | {item.get('kind','')} | {item.get('size','')} | `{item.get('sha256','')}` |")
    lines += ["", "## Discovered official download candidates", "", "| Source ID | Role | Kind | Bytes | SHA-256 |", "|---|---|---:|---:|---|"]
    for item in discovered:
        lines.append(f"| `{item['source_id']}` | {item.get('role','')} | {item.get('kind','')} | {item.get('size','')} | `{item.get('sha256','')}` |")
    lines += [
        "", "## Interpretation controls", "",
        "- V1.1 technical specification and attachment package are effective-source evidence for the current China eCTD V3.2.2 profile.",
        "- Effective validation standard section 6 remains the primary source for PDF rule identity and severity.",
        "- Technical specification is secondary normative context for detector semantics and applicability; it does not override the validation table.",
        "- The 2026-05-27 China eCTD v4.0 documents are consultation drafts and remain isolated from the effective runtime profile.",
        "- Validator software/manual candidates remain unconfirmed until filename, content and internal metadata support the role.", "",
    ]
    return "\n".join(lines)


def render_v1_basis(v1_record: dict[str, Any], hits: dict[str, Any]) -> str:
    lines = [
        "# eCTD技术规范V1.1：PDF规则二级依据映射", "",
        "> Status: source-derived secondary basis. The effective `eCTD验证标准V1.1` section 6 remains controlling for rule ID and severity.", "",
        f"- Source SHA-256: `{v1_record.get('sha256')}`",
        f"- Parsed PDF pages: {v1_record.get('pdf', {}).get('pages')}", "",
        "## Confirmed design implications", "",
        "1. The specification delegates general PDF production recommendations to ICH eCTD File Format Specification V1.3 and adds China-specific requirements.",
        "2. Files over five pages generally need a table of contents and bookmarks, subject to stated exceptions.",
        "3. Cross-document links include M1 change/research items to detailed content, M2 summaries to M3–M5 details, CSRs to appendices, and PDF dataset descriptions to XPT files.",
        "4. Cross-application hyperlinks should not be created; package context is therefore required before classifying a target.",
        "5. Chinese narrative text is black; hyperlinks are recommended as blue text or black text with a blue border. This is a production recommendation, not a section-6 rule.",
        "6. Foreign-language reference material is a separate leaf under the same directory element as the Chinese submission material.", "",
        "## Page locators automatically found", "",
    ]
    for key, values in hits.items():
        pages = sorted({entry['pdf_page'] for entry in values})
        lines.append(f"- `{key}`: PDF pages {pages if pages else 'NOT_FOUND'}")
    lines += ["", "## Rule-to-secondary-basis map", "", "| Rule | Secondary basis |", "|---|---|"]
    for rule_id in sorted(V1_1_SECONDARY_MAP, key=lambda x: tuple(map(int, x.split('.')))):
        lines.append(f"| {rule_id} | {'; '.join(V1_1_SECONDARY_MAP[rule_id])} |")
    lines += [
        "", "## Detector consequences", "",
        "- Package-relative path resolution and eCTD node context are required for 6.2–6.15, 6.22 and 6.23.",
        "- Link appearance and Chinese typography belong to a separate production-quality profile unless later elevated by an effective validator rule.",
        "- Cross-document link generation is not a safe default fixer because semantic relationships cannot be proven from the PDF object graph alone.",
        "- Attachment-package members are immutable technical inputs identified by byte hash, not handwritten approximations.", "",
    ]
    return "\n".join(lines)


def render_v4(v4_records: list[dict[str, Any]]) -> str:
    lines = [
        "# China eCTD v4.0 consultation package — isolated research register", "",
        "> Status: **DRAFT / RESEARCH ONLY**. Published for consultation on 2026-05-27. It must not affect the effective China eCTD V3.2.2/V1.1 validator profile.", "",
        "## Retrieved attachments", "", "| Source ID | Role | Kind | Pages | SHA-256 |", "|---|---|---:|---:|---|",
    ]
    for item in v4_records:
        lines.append(f"| `{item['source_id']}` | {item.get('role','')} | {item.get('kind','')} | {item.get('pdf',{}).get('pages','')} | `{item.get('sha256','')}` |")
    lines += [
        "", "## Product architecture decision", "",
        "- Use a separate profile namespace: `cn-cde-ectd-v4.0-draft/2026-05-27`.",
        "- Do not translate v4.0 validation messages into current 6.1–6.26 detector behavior.",
        "- Reuse only neutral infrastructure: source ledger, XML parser, package graph, controlled-vocabulary loader, evidence reports and worker isolation.",
        "- Keep models extensible for UUIDs, document reuse/reference, context-of-use and controlled keywords without changing current V3.2.2 output.",
        "- Perform a new formal delta when final China v4.0 implementation documents are published.", "",
        "## Automatically located v4 concepts", "",
    ]
    for item in v4_records:
        lines += [f"### {item['source_id']}", ""]
        found = {key: sorted({hit['pdf_page'] for hit in values}) for key, values in item.get('term_hits', {}).items() if values}
        if found:
            lines += [f"- `{key}`: PDF pages {pages}" for key, pages in found.items()]
        else:
            lines.append("- No configured v4 terms were located or the asset was not a parseable PDF.")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=Path("build/official-source-deep-dive"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/user-supplied-official-sources"))
    parser.add_argument("--v4-profile", type=Path, default=Path("rulepacks/cn-cde-ectd-v4.0-draft/2026-05-27"))
    args = parser.parse_args()
    asset_dir, text_dir, extract_dir = args.build / "assets", args.build / "pdf-text", args.build / "extracted"
    for directory in (asset_dir, text_dir, extract_dir, args.evidence, args.v4_profile):
        directory.mkdir(parents=True, exist_ok=True)

    direct_records: list[dict[str, Any]] = []
    links: list[Link] = []
    failures: list[dict[str, Any]] = []
    for source in SOURCES:
        try:
            path, record = download(source['url'], asset_dir, source['source_id'])
            record.update({"role": source['role'], "status": source['status'], "download_status": "SUCCESS"})
            if record['kind'] == 'pdf':
                record['pdf'] = pdf_info(path, text_dir)
                text_path = text_dir / record['pdf']['text_file'] if record['pdf'].get('text_file') else None
                record['term_hits'] = term_hits(text_path, KEY_TERMS_V1_1)
            elif record['kind'] in {'zip', 'rar', '7z'}:
                record['archive'] = archive_inventory(path, extract_dir)
            elif record['kind'] == 'html':
                links.extend(extract_links(source['url'], path.read_text(encoding='utf-8', errors='replace')))
            direct_records.append(record)
        except Exception as exc:
            item = {**source, "download_status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}
            direct_records.append(item)
            failures.append(item)

    unique = {link.url: link for link in links}
    discovered_records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for link in sorted(unique.values(), key=lambda x: x.url):
        classification = role_for_discovered(link)
        if not classification or any(item.get('requested_url') == link.url for item in direct_records):
            continue
        base_id, role = classification
        counts[base_id] = counts.get(base_id, 0) + 1
        source_id = base_id if counts[base_id] == 1 else f"{base_id}-{counts[base_id]:02d}"
        try:
            path, record = download(link.url, asset_dir, source_id)
            record.update({
                "role": role,
                "status": "official_draft" if "V4-DRAFT" in source_id else "role_unconfirmed_candidate",
                "anchor_text": link.text,
                "source_page": link.source_url,
                "download_status": "SUCCESS",
            })
            if record['kind'] == 'pdf':
                record['pdf'] = pdf_info(path, text_dir)
                text_path = text_dir / record['pdf']['text_file'] if record['pdf'].get('text_file') else None
                record['term_hits'] = term_hits(text_path, KEY_TERMS_V4 if 'V4-DRAFT' in source_id else KEY_TERMS_V1_1)
            elif record['kind'] in {'zip', 'rar', '7z'}:
                record['archive'] = archive_inventory(path, extract_dir)
            discovered_records.append(record)
        except Exception as exc:
            discovered_records.append({
                "source_id": source_id, "role": role, "requested_url": link.url,
                "anchor_text": link.text, "source_page": link.source_url,
                "download_status": "FAILED", "error": f"{type(exc).__name__}: {exc}",
            })

    v1 = next((item for item in direct_records if item.get('source_id') == 'CDE-CN-V1.1-SPEC-PDF'), {})
    package = next((item for item in direct_records if item.get('source_id') == 'CDE-CN-V1.1-SPEC-ATTACHMENTS'), {})
    v4 = [item for item in discovered_records if 'V4-DRAFT' in item.get('source_id', '')]
    package_inventory = {
        "schema_version": "0.1.0", "source_id": package.get('source_id'),
        "source_url": package.get('requested_url'), "source_sha256": package.get('sha256'),
        "source_sm3": package.get('sm3'), "status": package.get('archive', {}).get('status'),
        "members": package.get('archive', {}).get('extracted', []),
        "archive_listing": package.get('archive', {}).get('members', []),
        "interpretation": "Immutable official technical input; inventory does not mean every member is required in every sequence.",
    }
    v4_manifest = {
        "schema_version": "0.1.0", "profile_id": "cn-cde-ectd-v4.0-draft-2026-05-27",
        "profile_status": "draft_research_only", "published_date": "2026-05-27",
        "notice_url": SOURCES[3]['url'], "runtime_enabled": False,
        "must_not_influence": ["cn-cde-ectd-v3.2.2-v1.1-pdf"],
        "sources": [{
            "source_id": item.get('source_id'), "role": item.get('role'), "url": item.get('requested_url'),
            "sha256": item.get('sha256'), "sm3": item.get('sm3'), "kind": item.get('kind'),
            "pages": item.get('pdf', {}).get('pages'), "download_status": item.get('download_status'),
        } for item in v4],
        "implementation_policy": "Evidence and delta research only; no compliance claims and no production rule activation.",
    }
    ledger = {
        "schema_version": "0.1.0", "generated_at_epoch": int(time.time()),
        "generator": "tools/regulatory/deep_dive_official_sources.py",
        "direct_sources": direct_records, "discovered_sources": discovered_records, "failures": failures,
        "controls": {
            "raw_binary_storage": "GitHub Actions artifact only",
            "effective_profile": "China eCTD V3.2.2 technical files V1.1, effective 2026-03-01",
            "draft_profile": "China eCTD v4.0 consultation package dated 2026-05-27",
            "role_confirmation": "Validator candidates remain unconfirmed unless content and internal metadata support the role.",
        },
    }
    write_json(args.evidence / 'SOURCE_DEEP_DIVE.json', ledger)
    (args.evidence / 'SOURCE_DEEP_DIVE.md').write_text(render_manifest(direct_records, discovered_records), encoding='utf-8')
    write_json(args.evidence / 'V1_1_SECONDARY_BASIS_MAP.json', {
        "schema_version": "0.1.0", "source_id": v1.get('source_id'), "source_sha256": v1.get('sha256'),
        "term_hits": v1.get('term_hits', {}), "rule_map": V1_1_SECONDARY_MAP,
        "status": "SECONDARY_NORMATIVE_CONTEXT",
    })
    (args.evidence / 'V1_1_SECONDARY_BASIS_MAP.md').write_text(render_v1_basis(v1, v1.get('term_hits', {})), encoding='utf-8')
    write_json(args.evidence / 'V1_1_ATTACHMENT_PACKAGE_INVENTORY.json', package_inventory)
    write_json(args.v4_profile / 'manifest.json', v4_manifest)
    (args.v4_profile / 'README.md').write_text(render_v4(v4), encoding='utf-8')
    summary = {
        "direct_success": sum(item.get('download_status') == 'SUCCESS' for item in direct_records),
        "direct_total": len(direct_records),
        "discovered_success": sum(item.get('download_status') == 'SUCCESS' for item in discovered_records),
        "discovered_total": len(discovered_records),
        "v4_assets": len(v4), "v1_pdf_sha256": v1.get('sha256'),
        "v1_attachment_sha256": package.get('sha256'),
        "attachment_members": len(package_inventory['members']),
        "failures": len(failures) + sum(item.get('download_status') == 'FAILED' for item in discovered_records),
    }
    write_json(args.evidence / 'SUMMARY.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    required = {item.get('source_id'): item for item in direct_records}
    if any(required.get(key, {}).get('download_status') != 'SUCCESS' for key in ['CDE-CN-V1.1-SPEC-PDF', 'CDE-CN-V1.1-SPEC-ATTACHMENTS', 'CDE-CN-V4-DRAFT-NOTICE']):
        return 2
    if v1.get('kind') != 'pdf' or not v1.get('sha256'):
        return 3
    if package.get('kind') not in {'zip', 'rar', '7z'} or package.get('archive', {}).get('status') != 'EXTRACTED':
        return 4
    if len(v4) < 4:
        return 5
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
