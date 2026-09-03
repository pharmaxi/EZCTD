from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

NOTICE_URL = "https://www.cde.org.cn/main/news/viewInfoCommon/7898f68946d8e8e44d074657c7112002"
MAX_BYTES = 500 * 1024 * 1024

EXPECTED_ROLES = {
    "guidance": "cn_ectd_v4_draft_guidance",
    "controlled_vocabulary": "cn_ectd_v4_draft_controlled_vocabulary",
    "validation_standard": "cn_ectd_v4_draft_validation_standard",
    "rationale": "cn_ectd_v4_draft_rationale",
    "feedback_form": "cn_ectd_v4_draft_feedback_form",
}

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


def run(command: list[str], *, timeout: int = 300, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout, check=check)


def digest_bytes(value: bytes, algorithm: str) -> str | None:
    try:
        hasher = hashlib.new(algorithm)
    except ValueError:
        return None
    hasher.update(value)
    return hasher.hexdigest()


def digest_file(path: Path, algorithm: str) -> str | None:
    try:
        hasher = hashlib.new(algorithm)
    except ValueError:
        return None
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def safe_name(value: str) -> str:
    value = urllib.parse.unquote(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    return value.strip(" .")[:180] or "download"


def classify(text: str, url: str, index: int) -> tuple[str, str, str, str]:
    haystack = f"{text} {urllib.parse.unquote(url)}"
    if "反馈表" in haystack:
        return "CDE-CN-V4-DRAFT-FEEDBACK", "feedback_form", EXPECTED_ROLES["feedback_form"], "docx"
    if "起草说明" in haystack:
        return "CDE-CN-V4-DRAFT-RATIONALE", "rationale", EXPECTED_ROLES["rationale"], "pdf"
    if "附件1" in haystack or "受控词汇" in haystack:
        return "CDE-CN-V4-DRAFT-CONTROLLED-VOCABULARY", "controlled_vocabulary", EXPECTED_ROLES["controlled_vocabulary"], "pdf"
    if "附件2" in haystack or "验证标准" in haystack:
        return "CDE-CN-V4-DRAFT-VALIDATION-STANDARD", "validation_standard", EXPECTED_ROLES["validation_standard"], "pdf"
    if "指导原则" in haystack:
        return "CDE-CN-V4-DRAFT-GUIDANCE", "guidance", EXPECTED_ROLES["guidance"], "pdf"
    return f"CDE-CN-V4-DRAFT-UNCLASSIFIED-{index:02d}", "unclassified", "cn_ectd_v4_draft_unclassified", "unknown"


def detect_kind_bytes(data: bytes) -> dict[str, Any]:
    prefix = data[:1024]
    pdf_offset = prefix.find(b"%PDF-")
    if pdf_offset >= 0:
        return {"kind": "pdf", "pdf_header_offset": pdf_offset}
    if data.startswith(b"PK\x03\x04"):
        return {"kind": "zip"}
    stripped = data.lstrip()
    if stripped.startswith((b"<!DOCTYPE html", b"<!doctype html", b"<html", b"<HTML")):
        return {"kind": "html-protection-response"}
    return {"kind": "unknown"}


def validate_payload(data: bytes, expected_kind: str) -> dict[str, Any]:
    result = detect_kind_bytes(data)
    result.update({"expected_kind": expected_kind, "size": len(data), "valid": False, "reason": None})
    if len(data) == 0:
        result["reason"] = "empty response"
        return result
    if len(data) > MAX_BYTES:
        result["reason"] = "response exceeds maximum size"
        return result
    if expected_kind == "pdf":
        result["valid"] = result["kind"] == "pdf"
        result["reason"] = None if result["valid"] else "expected PDF magic within first 1024 bytes"
        return result
    if expected_kind == "docx":
        if result["kind"] != "zip":
            result["reason"] = "expected OOXML ZIP container"
            return result
        try:
            from io import BytesIO
            with zipfile.ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
            required = {"[Content_Types].xml", "word/document.xml"}
            result["docx_required_members"] = sorted(required)
            result["docx_members_present"] = sorted(required & names)
            result["valid"] = required <= names
            result["kind"] = "docx" if result["valid"] else "zip-non-docx"
            result["reason"] = None if result["valid"] else "OOXML container lacks required DOCX members"
        except zipfile.BadZipFile as exc:
            result["reason"] = f"invalid ZIP: {exc}"
        return result
    result["reason"] = "unknown expected content type"
    return result


def build_driver(download_dir: Path) -> webdriver.Chrome:
    options = Options()
    if os.environ.get("EZCTD_BROWSER_HEADLESS", "0") == "1":
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1400")
    options.add_argument("--lang=zh-CN,zh,en-US,en")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "safebrowsing.enabled": True,
        },
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": str(download_dir.resolve())},
    )
    driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en-US','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = window.chrome || {runtime: {}};
            """
        },
    )
    return driver


def settle_page(driver: webdriver.Chrome, url: str) -> None:
    driver.get(url)
    WebDriverWait(driver, 45).until(lambda d: d.execute_script("return document.readyState") == "complete")
    for _ in range(8):
        time.sleep(2)
        body = driver.find_element(By.TAG_NAME, "body").text if driver.find_elements(By.TAG_NAME, "body") else ""
        if "相关附件" in body or "eCTD v4.0指导原则" in body:
            return
    raise RuntimeError("CDE notice page did not render expected content")


def request_session_from_driver(driver: webdriver.Chrome) -> requests.Session:
    session = requests.Session()
    for cookie in driver.get_cookies():
        kwargs: dict[str, Any] = {"path": cookie.get("path", "/")}
        if cookie.get("domain"):
            kwargs["domain"] = cookie["domain"]
        session.cookies.set(cookie["name"], cookie["value"], **kwargs)
    return session


def request_download(
    driver: webdriver.Chrome,
    url: str,
    referer: str,
    expected_kind: str,
    rejected_dir: Path,
    source_id: str,
) -> tuple[bytes | None, dict[str, Any]]:
    user_agent = driver.execute_script("return navigator.userAgent")
    session = request_session_from_driver(driver)
    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
        "Accept": "application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }
    response = session.get(url, headers=headers, timeout=(30, 180), allow_redirects=True)
    data = response.content
    validation = validate_payload(data, expected_kind)
    record = {
        "method": "requests-with-browser-cookies",
        "status_code": response.status_code,
        "final_url": response.url,
        "headers": {key.lower(): value for key, value in response.headers.items()},
        "sha256": digest_bytes(data, "sha256"),
        "sm3": digest_bytes(data, "sm3"),
        **validation,
    }
    if validation["valid"]:
        return data, record
    rejected_dir.mkdir(parents=True, exist_ok=True)
    rejected = rejected_dir / f"{source_id}--request-rejected.bin"
    rejected.write_bytes(data)
    record["rejected_artifact"] = rejected.name
    return None, record


def wait_for_browser_download(download_dir: Path, before: set[Path], timeout_seconds: int = 150) -> list[Path]:
    deadline = time.time() + timeout_seconds
    stable: dict[Path, tuple[int, float]] = {}
    while time.time() < deadline:
        current = {path for path in download_dir.iterdir() if path.is_file()}
        new_files = [path for path in current - before if not path.name.endswith((".crdownload", ".tmp"))]
        complete: list[Path] = []
        for path in new_files:
            size = path.stat().st_size
            previous = stable.get(path)
            if previous and previous[0] == size and time.time() - previous[1] >= 1.5:
                complete.append(path)
            else:
                stable[path] = (size, time.time())
        if complete:
            return complete
        time.sleep(0.5)
    return []


def browser_click_download(
    driver: webdriver.Chrome,
    url: str,
    expected_kind: str,
    download_dir: Path,
    rejected_dir: Path,
    source_id: str,
) -> tuple[bytes | None, dict[str, Any]]:
    settle_page(driver, NOTICE_URL)
    elements = [element for element in driver.find_elements(By.TAG_NAME, "a") if element.get_attribute("href") == url]
    if len(elements) != 1:
        return None, {"method": "browser-click", "valid": False, "reason": f"expected one exact anchor, found {len(elements)}"}
    before = {path for path in download_dir.iterdir() if path.is_file()}
    original_handles = set(driver.window_handles)
    driver.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", elements[0])
    files = wait_for_browser_download(download_dir, before)
    new_handles = set(driver.window_handles) - original_handles
    for handle in new_handles:
        try:
            driver.switch_to.window(handle)
            driver.close()
        except Exception:
            pass
    if driver.window_handles:
        driver.switch_to.window(driver.window_handles[0])
    if not files:
        return None, {"method": "browser-click", "valid": False, "reason": "no completed browser download observed"}
    attempts: list[dict[str, Any]] = []
    for path in files:
        data = path.read_bytes()
        validation = validate_payload(data, expected_kind)
        item = {
            "downloaded_filename": path.name,
            "sha256": digest_bytes(data, "sha256"),
            "sm3": digest_bytes(data, "sm3"),
            **validation,
        }
        attempts.append(item)
        if validation["valid"]:
            return data, {"method": "browser-click", "valid": True, "attempts": attempts}
        rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected = rejected_dir / f"{source_id}--browser-rejected--{safe_name(path.name)}"
        shutil.copy2(path, rejected)
        item["rejected_artifact"] = rejected.name
    return None, {"method": "browser-click", "valid": False, "reason": "downloaded files failed byte validation", "attempts": attempts}


def pdf_analysis(path: Path, text_dir: Path) -> tuple[dict[str, Any], str]:
    text_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, str] = {}
    info = run(["pdfinfo", str(path)], timeout=90, check=False)
    for line in info.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    text_path = text_dir / f"{path.stem}.txt"
    text_proc = run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(text_path)], timeout=240, check=False)
    text = text_path.read_text(encoding="utf-8", errors="replace") if text_path.exists() else ""
    return (
        {
            "status": "SUCCESS" if info.returncode == 0 and text_proc.returncode == 0 else "PARTIAL",
            "pages": int(metadata["Pages"]) if metadata.get("Pages", "").isdigit() else None,
            "metadata": metadata,
            "text_file": text_path.name if text_path.exists() else None,
            "pdfinfo_stderr": info.stderr[-1000:],
            "pdftotext_stderr": text_proc.stderr[-1000:],
        },
        text,
    )


def docx_analysis(path: Path) -> tuple[dict[str, Any], str]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        raw = archive.read("word/document.xml")
    text = re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace"))
    text = " ".join(text.split())
    return {"status": "SUCCESS", "members": len(names), "text_length": len(text), "text_excerpt": text[:4000]}, text


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
                hits.append(
                    {
                        "physical_page": page_no,
                        "matched_terms": matched,
                        "context": compact[max(0, first - 100):min(len(compact), first + 280)],
                    }
                )
        output[key] = hits[:12]
    return output


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_readme(records: list[dict[str, Any]]) -> str:
    lines = [
        "# China eCTD v4.0 consultation package", "",
        "> Status: **DRAFT / RESEARCH ONLY**. Byte-valid official attachments retrieved from the CDE consultation notice dated 2026-05-27. This profile is not active in the effective China eCTD V3.2.2/V1.1 runtime.", "",
        "## Official attachments", "", "| Role | Displayed file | Kind | Pages | Bytes | SHA-256 |", "|---|---|---:|---:|---:|---|",
    ]
    for item in records:
        lines.append(
            f"| `{item['role_key']}` | {item['displayed_name']} | {item['kind']} | {item.get('pdf', {}).get('pages', '')} | {item['size']} | `{item['sha256']}` |"
        )
    lines += [
        "", "## Isolation contract", "",
        "- Profile ID: `cn-cde-ectd-v4.0-draft-2026-05-27`.",
        "- `runtime_enabled=false`.",
        "- No draft rule, severity, controlled vocabulary or data-model field may alter the effective V3.2.2/V1.1 profiles.",
        "- Neutral infrastructure may be shared: evidence ledger, archive safety, XML parsing, typed identifiers, dependency graph and worker isolation.",
        "- Final China v4.0 documents require a fresh byte freeze and a formal draft-to-final delta before activation.", "",
        "## Acquisition assurance", "",
        "Each PDF was accepted only after `%PDF-` was found in the first 1024 bytes. The feedback DOCX was accepted only as an OOXML ZIP containing both `[Content_Types].xml` and `word/document.xml`. HTTP protection pages are retained only as rejected-payload metadata and never registered as official attachments.", "",
    ]
    return "\n".join(lines)


def render_delta(records: list[dict[str, Any]]) -> str:
    lines = [
        "# eCTD v4.0 draft: initial evidence-led delta notes", "",
        "> Research inventory only. The concept locators below are generated from byte-validated official consultation files and do not alter the current V3.2.2 rule pack.", "",
    ]
    for item in records:
        lines += [
            f"## {item['displayed_name']}", "",
            f"- Role: `{item['role_key']}`",
            f"- Kind: `{item['kind']}`",
            f"- SHA-256: `{item['sha256']}`",
            f"- Pages: {item.get('pdf', {}).get('pages', 'n/a')}",
        ]
        found = {key: sorted({hit["physical_page"] for hit in values}) for key, values in item.get("term_hits", {}).items() if values}
        if found:
            lines += [f"- `{key}`: physical pages {pages}" for key, pages in found.items()]
        else:
            lines.append("- No configured concept terms were found in extracted text.")
        lines.append("")
    lines += [
        "## Next analytical gate", "",
        "Extract cardinalities, identifiers, operation semantics, validation message identity/severity and controlled-vocabulary values into typed draft-only models; then compare them with V3.2.2 at the concept level. Keyword hits alone are not an implementation specification.", "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, default=Path("build/official-source-deep-dive/browser-discovery/dynamic-link-discovery.json"))
    parser.add_argument("--build", type=Path, default=Path("build/official-source-deep-dive"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/user-supplied-official-sources"))
    parser.add_argument("--profile", type=Path, default=Path("rulepacks/cn-cde-ectd-v4.0-draft/2026-05-27"))
    args = parser.parse_args()

    acquisition_dir = args.build / "browser-attachment-acquisition"
    downloads_dir = acquisition_dir / "downloads"
    rejected_dir = acquisition_dir / "rejected"
    canonical_dir = args.build / "assets-byte-validated"
    text_dir = args.build / "pdf-text-v4-validated"
    for directory in (acquisition_dir, downloads_dir, rejected_dir, canonical_dir, text_dir, args.evidence, args.profile):
        directory.mkdir(parents=True, exist_ok=True)

    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    candidates = [item for item in discovery.get("download_candidates", []) if item.get("source_id") == "CDE-CN-V4-DRAFT-NOTICE"]
    if len(candidates) != 5:
        raise SystemExit(f"expected five v4 attachment candidates, found {len(candidates)}")

    driver = build_driver(downloads_dir)
    records: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    try:
        driver.get("https://www.cde.org.cn/")
        time.sleep(5)
        settle_page(driver, NOTICE_URL)
        for index, candidate in enumerate(candidates, 1):
            source_id, role_key, role, expected_kind = classify(candidate.get("text", ""), candidate["url"], index)
            request_data, request_record = request_download(
                driver, candidate["url"], NOTICE_URL, expected_kind, rejected_dir, source_id
            )
            acquisition_attempts = [request_record]
            data = request_data
            if data is None:
                browser_data, browser_record = browser_click_download(
                    driver, candidate["url"], expected_kind, downloads_dir, rejected_dir, source_id
                )
                acquisition_attempts.append(browser_record)
                data = browser_data
            if data is None:
                records.append(
                    {
                        "source_id": source_id,
                        "role_key": role_key,
                        "role": role,
                        "requested_url": candidate["url"],
                        "displayed_name": candidate.get("text", ""),
                        "expected_kind": expected_kind,
                        "download_status": "FAILED_BYTE_VALIDATION",
                        "acquisition_attempts": acquisition_attempts,
                    }
                )
                rejected_records.extend(
                    [{"source_id": source_id, "url": candidate["url"], **attempt} for attempt in acquisition_attempts if not attempt.get("valid")]
                )
                continue

            validation = validate_payload(data, expected_kind)
            if not validation["valid"]:
                raise RuntimeError(f"internal validation mismatch for {source_id}: {validation}")
            extension = ".pdf" if expected_kind == "pdf" else ".docx"
            canonical_path = canonical_dir / f"{source_id}{extension}"
            canonical_path.write_bytes(data)
            record: dict[str, Any] = {
                "source_id": source_id,
                "role_key": role_key,
                "role": role,
                "status": "official_draft",
                "source_page": NOTICE_URL,
                "requested_url": candidate["url"],
                "displayed_name": candidate.get("text", ""),
                "download_status": "SUCCESS_BYTE_VALIDATED",
                "acquisition_method": next(attempt["method"] for attempt in acquisition_attempts if attempt.get("valid")),
                "acquisition_attempts": acquisition_attempts,
                "kind": expected_kind,
                "size": len(data),
                "sha256": digest_bytes(data, "sha256"),
                "sm3": digest_bytes(data, "sm3"),
                "canonical_artifact": canonical_path.name,
                "byte_validation": validation,
            }
            if expected_kind == "pdf":
                record["pdf"], extracted_text = pdf_analysis(canonical_path, text_dir)
            else:
                record["docx"], extracted_text = docx_analysis(canonical_path)
            record["term_hits"] = term_hits(extracted_text)
            records.append(record)
            rejected_records.extend(
                [{"source_id": source_id, "url": candidate["url"], **attempt} for attempt in acquisition_attempts if not attempt.get("valid")]
            )
    finally:
        driver.quit()

    roles = {item.get("role_key") for item in records if item.get("download_status") == "SUCCESS_BYTE_VALIDATED"}
    failures = [item for item in records if item.get("download_status") != "SUCCESS_BYTE_VALIDATED"]
    missing_roles = set(EXPECTED_ROLES) - roles

    manifest = {
        "schema_version": "0.3.0",
        "profile_id": "cn-cde-ectd-v4.0-draft-2026-05-27",
        "profile_status": "draft_research_only",
        "published_date": "2026-05-27",
        "notice_url": NOTICE_URL,
        "runtime_enabled": False,
        "must_not_influence": ["cn-cde-ectd-v3.2.2-v1.1-pdf", "cn-cde-ectd-v3.2.2-v1.1-package"],
        "expected_roles": EXPECTED_ROLES,
        "retrieved_roles": sorted(role for role in roles if role),
        "content_acceptance": {
            "pdf": "%PDF- within first 1024 bytes and successful pdfinfo/pdftotext inspection",
            "docx": "OOXML ZIP containing [Content_Types].xml and word/document.xml",
            "http_200_alone_is_success": False,
        },
        "sources": [
            {
                "source_id": item.get("source_id"),
                "role_key": item.get("role_key"),
                "role": item.get("role"),
                "url": item.get("requested_url"),
                "displayed_name": item.get("displayed_name"),
                "sha256": item.get("sha256"),
                "sm3": item.get("sm3"),
                "kind": item.get("kind"),
                "size": item.get("size"),
                "pages": item.get("pdf", {}).get("pages"),
                "download_status": item.get("download_status"),
                "acquisition_method": item.get("acquisition_method"),
            }
            for item in records
        ],
        "implementation_policy": "Evidence and delta research only; no production rule activation.",
    }

    write_json(args.evidence / "V4_OFFICIAL_ATTACHMENTS.json", {"records": records, "failures": failures, "missing_roles": sorted(missing_roles)})
    write_json(
        args.evidence / "V4_REJECTED_HTTP_PAYLOADS.json",
        {
            "schema_version": "0.1.0",
            "interpretation": "Responses rejected because HTTP success did not satisfy expected PDF/DOCX byte identity. Raw rejected bytes remain in the workflow artifact.",
            "records": rejected_records,
        },
    )
    (args.evidence / "V4_DRAFT_DELTA_RESEARCH.md").write_text(render_delta(records), encoding="utf-8")
    write_json(args.profile / "manifest.json", manifest)
    (args.profile / "README.md").write_text(render_readme(records), encoding="utf-8")

    source_deep = args.evidence / "SOURCE_DEEP_DIVE.json"
    if source_deep.exists():
        payload = json.loads(source_deep.read_text(encoding="utf-8"))
        payload["discovered_sources"] = records
        payload.setdefault("controls", {})["v4_byte_validation"] = manifest["content_acceptance"]
        write_json(source_deep, payload)

    summary_path = args.evidence / "SUMMARY.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary.update(
        {
            "discovered_success": len(records) - len(failures),
            "discovered_total": len(records),
            "v4_assets": len(records) - len(failures),
            "v4_expected_roles": len(EXPECTED_ROLES),
            "v4_retrieved_roles": len(roles),
            "v4_failures": len(failures),
            "v4_rejected_http_payloads": len(rejected_records),
            "v4_byte_identity_validated": not failures and not missing_roles,
        }
    )
    write_json(summary_path, summary)
    acquisition_summary = {
        "status": "COMPLETE_BYTE_VALIDATED" if not failures and not missing_roles else "FAILED_OR_INCOMPLETE",
        "records": len(records),
        "valid_records": len(records) - len(failures),
        "missing_roles": sorted(missing_roles),
        "rejected_attempts": len(rejected_records),
        "sources": [{"source_id": item.get("source_id"), "kind": item.get("kind"), "size": item.get("size"), "sha256": item.get("sha256")} for item in records],
    }
    write_json(acquisition_dir / "acquisition-summary.json", acquisition_summary)
    print(json.dumps(acquisition_summary, ensure_ascii=False, indent=2))

    if failures or missing_roles or len(records) != 5:
        return 2
    if any(item.get("kind") == "pdf" and not item.get("pdf", {}).get("pages") for item in records):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
