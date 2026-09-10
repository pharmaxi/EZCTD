from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT = Path("docs/research/open-source")
RAW = OUT / "raw"

REPO_QUERIES = [
    "ectd validator",
    "ectd publisher",
    "ectd index.xml generator",
    "electronic common technical document",
    "pdf preflight validator",
    "pdf bookmark hyperlink validator",
]

CODE_QUERIES = [
    '"cn-regional.xml"',
    '"ich-ectd-3-2.dtd"',
    '"index-md5.txt" ectd',
    '"checksum-type" "md5" "xlink:href" ectd',
    '"operation=\"new\"" ectd leaf',
    '"m1/cn" ectd',
]

KNOWN_REPOS = [
    "qpdf/qpdf",
    "pikepdf/pikepdf",
    "py-pdf/pypdf",
    "pypdfium2-team/pypdfium2",
    "MatthiasValvekens/pyHanko",
    "ocrmypdf/OCRmyPDF",
    "tesseract-ocr/tesseract",
    "PaddlePaddle/PaddleOCR",
    "veraPDF/veraPDF-apps",
    "apache/pdfbox",
    "pdfcpu/pdfcpu",
    "pymupdf/PyMuPDF",
    "mozilla/pdf.js",
    "Stirling-Tools/Stirling-PDF",
    "sebsca/ectd-tool",
    "Lewis-Teoh/dotnet-ectd-validator",
    "RegHubAI/Auto-publisher-for-eCTD",
    "SandipKurmi/ectd-pdf-validator",
    "fragkopoulos/ectd-validator",
]

OVERRIDES: dict[str, dict[str, str]] = {
    "qpdf/qpdf": {"category":"PDF structural engine", "recommendation":"ADOPT_CORE", "reason":"Mature low-level structural inspection, repair, rewrite and linearization; not a renderer or CDE rules engine."},
    "pikepdf/pikepdf": {"category":"Python PDF object layer", "recommendation":"ADOPT_CORE", "reason":"Python interface backed by qpdf; suitable for object-level inspection and controlled writing."},
    "py-pdf/pypdf": {"category":"Python high-level PDF API", "recommendation":"ADOPT_AUXILIARY", "reason":"Convenient outlines, destinations and annotations API; cross-check complex or malformed files with qpdf/PDFium."},
    "pypdfium2-team/pypdfium2": {"category":"PDF renderer", "recommendation":"ADOPT_CORE", "reason":"Independent rendering and page probe based on PDFium; isolate native parsing in worker processes."},
    "MatthiasValvekens/pyHanko": {"category":"PDF signature inspection", "recommendation":"ADOPT_INSPECTION_ONLY_INITIAL", "reason":"Useful for signature discovery, validation and incremental-update analysis; official CDE signing remains out of scope."},
    "ocrmypdf/OCRmyPDF": {"category":"OCR PDF pipeline", "recommendation":"ADOPT_OPTIONAL", "reason":"Strong searchable-text-layer pipeline; OCR is high-risk and must stay opt-in with visual verification."},
    "tesseract-ocr/tesseract": {"category":"OCR engine", "recommendation":"ADOPT_OPTIONAL", "reason":"Widely used OCR engine; pin language data and versions, and benchmark Chinese regulatory documents."},
    "PaddlePaddle/PaddleOCR": {"category":"Chinese document OCR", "recommendation":"EVALUATE_PLUGIN", "reason":"Potentially stronger Chinese/layout recognition; heavier runtime and output must not be treated as original content."},
    "veraPDF/veraPDF-apps": {"category":"PDF/A and PDF/UA validator", "recommendation":"ADOPT_INDEPENDENT_QA", "reason":"Useful for genuine PDF/A conformance checks; not a substitute for CDE validation rules."},
    "apache/pdfbox": {"category":"Independent Java PDF parser", "recommendation":"ADOPT_SECONDARY_VALIDATOR", "reason":"Mature independent parser and CLI; useful for differential interpretation and PDF/A-related checks."},
    "pdfcpu/pdfcpu": {"category":"Go PDF processor", "recommendation":"EVALUATE_CROSS_CHECK", "reason":"Broad CLI and validation surface; do not make it the sole compliance engine without corpus evidence."},
    "pymupdf/PyMuPDF": {"category":"High-performance PDF toolkit", "recommendation":"LICENSE_GATED", "reason":"Technically capable, but AGPL/commercial licensing should remain isolated from a future closed distribution."},
    "mozilla/pdf.js": {"category":"Web PDF viewer", "recommendation":"ADOPT_UI", "reason":"Strong viewer and debugger for a Tauri/web UI; backend compliance decisions must not depend on browser rendering alone."},
    "Stirling-Tools/Stirling-PDF": {"category":"PDF workflow UI reference", "recommendation":"REFERENCE_ONLY", "reason":"Useful interaction and job-flow reference; its broad generic PDF scope is not an eCTD compliance model."},
    "sebsca/ectd-tool": {"category":"eCTD XML generator/viewer", "recommendation":"REFERENCE_PROTOTYPE", "reason":"Useful for ICH 3.2 index.xml and EU regional mapping concepts; not validated for current China V1.1 production submissions."},
    "Lewis-Teoh/dotnet-ectd-validator": {"category":"Regional eCTD package validator", "recommendation":"REFERENCE_ARCHITECTURE", "reason":"Useful package security, hierarchy and checksum architecture for Singapore; regional rules cannot be transplanted to China."},
    "RegHubAI/Auto-publisher-for-eCTD": {"category":"FDA PDF compliance prototype", "recommendation":"REFERENCE_TEST_IDEAS", "reason":"Contains DOCX-to-PDF, bookmarks and links ideas; new/small and FDA-specific, not evidence of CDE compliance."},
    "SandipKurmi/ectd-pdf-validator": {"category":"FDA-style PDF validator prototype", "recommendation":"REFERENCE_WITH_CAUTION", "reason":"Rule service shape is instructive, but broad compliance claims and simplified predicates require independent verification."},
    "fragkopoulos/ectd-validator": {"category":"eCTD placeholder", "recommendation":"DO_NOT_USE", "reason":"Repository is effectively a placeholder and supplies no usable validation implementation."},
}


def api(path: str) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "EZCTD-open-source-inventory/0.1", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{API}{path}", headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429} and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return {"_error": f"HTTP {exc.code}", "_body": exc.read().decode("utf-8", errors="replace")[:2000]}
        except Exception as exc:
            if attempt == 3:
                return {"_error": type(exc).__name__, "_body": str(exc)}
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def search_repositories(query: str) -> dict:
    return api("/search/repositories?" + urllib.parse.urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": 20}))


def search_code(query: str) -> dict:
    return api("/search/code?" + urllib.parse.urlencode({"q": query, "per_page": 20}))


def decode_readme(payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("encoding") != "base64" or not payload.get("content"):
        return None
    try:
        return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def repo_record(full_name: str) -> dict[str, Any]:
    meta = api(f"/repos/{full_name}")
    if not isinstance(meta, dict) or meta.get("_error") or not meta.get("full_name"):
        return {"full_name": full_name, "status": "FETCH_FAILED", "error": meta}
    license_payload = api(f"/repos/{full_name}/license")
    readme_payload = api(f"/repos/{full_name}/readme")
    readme = decode_readme(readme_payload)
    override = OVERRIDES.get(full_name, {})
    pushed = meta.get("pushed_at")
    age_days = None
    if pushed:
        try:
            age_days = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
        except ValueError:
            pass
    license_spdx = None
    if isinstance(license_payload, dict):
        license_spdx = (license_payload.get("license") or {}).get("spdx_id")
    readme_signals = {}
    if readme:
        lowered = readme.lower()
        for signal in ["index.xml", "cn-regional.xml", "checksum", "md5", "lifecycle", "validator", "publisher", "bookmark", "hyperlink"]:
            readme_signals[signal] = signal in lowered
    return {
        "full_name": full_name,
        "status": "FETCHED",
        "html_url": meta.get("html_url"),
        "description": meta.get("description"),
        "default_branch": meta.get("default_branch"),
        "archived": meta.get("archived"),
        "fork": meta.get("fork"),
        "size_kb": meta.get("size"),
        "stars": meta.get("stargazers_count"),
        "forks": meta.get("forks_count"),
        "open_issues": meta.get("open_issues_count"),
        "created_at": meta.get("created_at"),
        "pushed_at": pushed,
        "age_days_since_push": age_days,
        "primary_language": meta.get("language"),
        "license_spdx": license_spdx,
        "topics": meta.get("topics", []),
        "category": override.get("category", "Unclassified search result"),
        "recommendation": override.get("recommendation", "REVIEW_REQUIRED"),
        "assessment_reason": override.get("reason", "Discovered by search; code and licensing require manual review."),
        "authority_status": "NON_AUTHORITATIVE_IMPLEMENTATION_REFERENCE",
        "readme_signals": readme_signals,
        "readme_excerpt": re.sub(r"\s+", " ", readme or "")[:1200] or None,
    }


def markdown(payload: dict[str, Any]) -> str:
    records = payload["repositories"]
    lines = [
        "# Open-source PDF/eCTD reference inventory",
        "",
        "> Generated from GitHub API metadata and code/repository search. Every repository is a non-authoritative implementation reference; CDE effective technical files remain controlling.",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "## Decision summary",
        "",
        "| Repository | Category | License | Last push | Recommendation | Assessment |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        if record.get("status") != "FETCHED":
            lines.append(f"| `{record['full_name']}` | fetch failed | — | — | REVIEW | Metadata fetch failed |")
            continue
        reason = record["assessment_reason"].replace("|", "\\|")
        lines.append(
            f"| [`{record['full_name']}`]({record['html_url']}) | {record['category']} | {record['license_spdx'] or 'NOASSERTION'} | "
            f"{record['pushed_at'] or 'unknown'} | `{record['recommendation']}` | {reason} |"
        )
    lines += [
        "",
        "## Reuse rules",
        "",
        "1. Official CDE/NMPA effective files control regulatory semantics and severity.",
        "2. GitHub projects may supply parsers, test ideas, data models or UI patterns; none is accepted as proof of CDE compatibility.",
        "3. AGPL/commercial dual-license components remain isolated behind adapters unless the distribution model explicitly accepts those obligations.",
        "4. Regional eCTD validators demonstrate architecture only; Singapore, FDA, EU and China rules are not interchangeable.",
        "5. Any copied code must retain its license and notices; behavioral ideas should be independently implemented and tested against official sources.",
        "",
        "## Search coverage",
        "",
        f"- Repository queries: {len(payload['searches']['repository'])}",
        f"- Code queries: {len(payload['searches']['code'])}",
        f"- Unique repositories inventoried: {len(records)}",
        f"- Search errors: {payload['summary']['search_errors']}",
        "",
        "Raw API-normalized search results are stored in `raw/search-results.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    repository_searches = []
    code_searches = []
    candidates = set(KNOWN_REPOS)
    errors = 0

    for query in REPO_QUERIES:
        result = search_repositories(query)
        if result.get("_error"):
            errors += 1
        items = []
        for item in result.get("items", []) if isinstance(result, dict) else []:
            full_name = item.get("full_name")
            if full_name:
                candidates.add(full_name)
                items.append({"full_name": full_name, "url": item.get("html_url"), "description": item.get("description"), "score": item.get("score")})
        repository_searches.append({"query": query, "total_count": result.get("total_count") if isinstance(result, dict) else None, "items": items, "error": result.get("_error") if isinstance(result, dict) else "invalid"})

    for query in CODE_QUERIES:
        result = search_code(query)
        if result.get("_error"):
            errors += 1
        items = []
        for item in result.get("items", []) if isinstance(result, dict) else []:
            repo = (item.get("repository") or {}).get("full_name")
            if repo:
                candidates.add(repo)
                items.append({"repository": repo, "path": item.get("path"), "url": item.get("html_url"), "score": item.get("score")})
        code_searches.append({"query": query, "total_count": result.get("total_count") if isinstance(result, dict) else None, "items": items, "error": result.get("_error") if isinstance(result, dict) else "invalid"})

    # Bound the dynamic tail so results remain reviewable and rate limits predictable.
    ordered = list(KNOWN_REPOS) + sorted(candidates - set(KNOWN_REPOS))[:35]
    records = [repo_record(repo) for repo in ordered]
    payload = {
        "schema_version": "0.1.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generator": "tools/research/inventory_open_source_ectd.py",
        "authority_policy": "NON_AUTHORITATIVE_IMPLEMENTATION_REFERENCE",
        "searches": {"repository": repository_searches, "code": code_searches},
        "repositories": records,
        "summary": {
            "known_seed_repositories": len(KNOWN_REPOS),
            "repositories_inventoried": len(records),
            "fetched": sum(r.get("status") == "FETCHED" for r in records),
            "search_errors": errors,
        },
    }
    (RAW / "search-results.json").write_text(json.dumps(payload["searches"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "inventory.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "OPEN_SOURCE_ECTD_REFERENCE_REPOS.md").write_text(markdown(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0 if payload["summary"]["fetched"] >= len(KNOWN_REPOS) - 2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
