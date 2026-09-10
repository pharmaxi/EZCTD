from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TEXT_EXTENSIONS = {".xml", ".xsd", ".dtd", ".xsl", ".xslt", ".txt", ".html", ".htm", ".csv", ".md"}
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z", ".exe", ".msi"}
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_FILES = 10000
MAX_TOTAL_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
XLINK = "http://www.w3.org/1999/xlink"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_text(path: Path) -> str | None:
    if path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > MAX_TEXT_BYTES:
        return None
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return None


def extract_archive(source: Path, destination: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"source": str(source), "status": "NOT_ARCHIVE", "method": None, "files": 0, "bytes": 0, "error": None}
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(source):
            result["method"] = "python-zipfile"
            with zipfile.ZipFile(source) as archive:
                total = sum(item.file_size for item in archive.infolist())
                files = sum(not item.is_dir() for item in archive.infolist())
                if files > MAX_EXTRACTED_FILES or total > MAX_TOTAL_EXTRACTED_BYTES:
                    raise RuntimeError(f"archive safety limit exceeded: files={files}, bytes={total}")
                for item in archive.infolist():
                    candidate = (destination / item.filename).resolve()
                    if destination.resolve() not in candidate.parents and candidate != destination.resolve():
                        raise RuntimeError(f"archive path traversal: {item.filename}")
                archive.extractall(destination)
                result.update({"status": "EXTRACTED", "files": files, "bytes": total})
                return result
        seven_zip = shutil.which("7z") or shutil.which("7zz")
        if seven_zip and source.suffix.lower() in ARCHIVE_EXTENSIONS:
            result["method"] = "7z"
            proc = subprocess.run([seven_zip, "x", "-y", f"-o{destination}", str(source)], capture_output=True, text=True, errors="replace", timeout=180)
            if proc.returncode == 0:
                extracted = [p for p in destination.rglob("*") if p.is_file()]
                total = sum(p.stat().st_size for p in extracted)
                if len(extracted) > MAX_EXTRACTED_FILES or total > MAX_TOTAL_EXTRACTED_BYTES:
                    raise RuntimeError(f"extracted safety limit exceeded: files={len(extracted)}, bytes={total}")
                result.update({"status": "EXTRACTED", "files": len(extracted), "bytes": total})
            else:
                result.update({"status": "FAILED", "error": (proc.stderr or proc.stdout)[-3000:]})
            return result
    except Exception as exc:
        result.update({"status": "FAILED", "error": f"{type(exc).__name__}: {exc}"})
    return result


def xml_record(path: Path, text: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.as_posix(),
        "root_tag": None,
        "doctype": None,
        "namespaces": {},
        "schema_locations": [],
        "href_count": 0,
        "leaf_like_count": 0,
        "operations": [],
        "checksum_types": [],
        "parse_status": "NOT_PARSED",
        "parse_error": None,
    }
    doctype = re.search(r"<!DOCTYPE\s+([^>]+)>", text, re.I | re.S)
    if doctype:
        record["doctype"] = " ".join(doctype.group(1).split())[:2000]
    for prefix, uri in re.findall(r"xmlns(?::([\w.-]+))?=[\"']([^\"']+)[\"']", text):
        record["namespaces"][prefix or "default"] = uri
    record["schema_locations"] = re.findall(r"(?:schemaLocation|noNamespaceSchemaLocation)=[\"']([^\"']+)[\"']", text)
    try:
        parser = ET.XMLParser()
        root = ET.fromstring(text, parser=parser)
        record["root_tag"] = root.tag
        href_count = 0
        leaf_count = 0
        operations: Counter[str] = Counter()
        checksum_types: Counter[str] = Counter()
        for node in root.iter():
            href = node.attrib.get(f"{{{XLINK}}}href") or node.attrib.get("href")
            if href:
                href_count += 1
            if node.tag.lower().endswith("leaf") or href:
                leaf_count += 1
            operation = node.attrib.get("operation")
            if operation:
                operations[operation] += 1
            checksum_type = node.attrib.get("checksum-type") or node.attrib.get("checksumType")
            if checksum_type:
                checksum_types[checksum_type] += 1
        record.update({
            "href_count": href_count,
            "leaf_like_count": leaf_count,
            "operations": dict(operations),
            "checksum_types": dict(checksum_types),
            "parse_status": "PARSED",
        })
    except Exception as exc:
        record.update({"parse_status": "ERROR", "parse_error": f"{type(exc).__name__}: {exc}"})
    return record


def classify_inventory(files: list[dict[str, Any]], xml_files: list[dict[str, Any]]) -> dict[str, Any]:
    names = [item["relative_path"].lower() for item in files]
    basenames = [Path(name).name for name in names]
    has_index_xml = "index.xml" in basenames
    regional = [item for item in names if item.endswith("regional.xml") or "cn-regional" in item]
    utility = [item for item in names if Path(item).suffix in {".dtd", ".xsd", ".xsl", ".xslt"}]
    modules = sorted({match.group(1) for name in names for match in [re.search(r"(?:^|/)(m[1-5])(?:/|$)", name)] if match})
    sequence_dirs = sorted({part for name in names for part in Path(name).parts if re.fullmatch(r"\d{4}", part)})
    md5_files = [item for item in names if "md5" in Path(item).name]
    likely_sample = has_index_xml and bool(modules) and bool(sequence_dirs)
    likely_utility = bool(utility)
    return {
        "has_index_xml": has_index_xml,
        "regional_backbones": regional,
        "utility_files": utility,
        "module_directories": modules,
        "sequence_directories": sequence_dirs,
        "md5_files": md5_files,
        "likely_sample_sequence": likely_sample,
        "likely_technical_utility_package": likely_utility,
        "xml_roots": sorted({item.get("root_tag") for item in xml_files if item.get("root_tag")}),
    }


def inspect_tree(root: Path, source_id: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    xml_files: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        item = {
            "relative_path": relative,
            "size": path.stat().st_size,
            "sha256": sha256(path),
            "extension": path.suffix.lower(),
        }
        files.append(item)
        text = safe_text(path)
        if text is not None and path.suffix.lower() in {".xml", ".xsd", ".xsl", ".xslt"}:
            xml_files.append(xml_record(Path(relative), text))
    return {
        "source_id": source_id,
        "file_count": len(files),
        "total_bytes": sum(item["size"] for item in files),
        "files": files,
        "xml_files": xml_files,
        "classification": classify_inventory(files, xml_files),
    }


def baseline_markdown(payload: dict[str, Any]) -> str:
    observed = payload["observed"]
    observed_regional = sorted({path for package in observed for path in package["classification"]["regional_backbones"]})
    observed_utilities = sorted({path for package in observed for path in package["classification"]["utility_files"]})
    sample_candidates = [package for package in observed if package["classification"]["likely_sample_sequence"]]
    lines = [
        "# Minimal China eCTD baseline sequence — evidence-constrained specification",
        "",
        "> Status: **NOT YET OFFICIAL-VALIDATOR-CLEAN**. This document separates official facts, package observations and implementation hypotheses. It must not be presented as a certified China sequence template.",
        "",
        "## Target",
        "",
        "Create the smallest reproducible China eCTD V3.2.2 sequence that passes CDE eCTD validation software V1.1.0 before any PDF mutation is introduced.",
        "",
        "## Officially controlled facts already fixed",
        "",
        "- China effective baseline: CDE eCTD V3.2.2 related technical files V1.1, effective 2026-03-01.",
        "- PDF rules: validation standard V1.1 section 6, rules 6.1–6.26.",
        "- The official validator target is V1.1.0. A baseline is not accepted merely because XML is well-formed or an ICH DTD validates.",
        "- ICH eCTD 3.2.2 supplies the international backbone; China regional Module 1 requirements and CDE validation behavior remain controlling.",
        "",
        "## Observed technical-package evidence",
        "",
        f"- Packages/trees analyzed: {len(observed)}",
        f"- Candidate complete sample sequences: {len(sample_candidates)}",
        f"- Observed regional backbone files: {len(observed_regional)}",
        f"- Observed DTD/XSD/XSL files: {len(observed_utilities)}",
        "",
    ]
    if observed_regional:
        lines += ["### Regional backbone candidates", ""] + [f"- `{item}`" for item in observed_regional[:100]] + [""]
    else:
        lines += ["### Regional backbone candidates", "", "No `cn-regional.xml` or other regional backbone was observed in the automatically retrieved asset set.", ""]
    if observed_utilities:
        lines += ["### Utility files observed", ""] + [f"- `{item}`" for item in observed_utilities[:150]] + [""]
    else:
        lines += ["### Utility files observed", "", "No DTD/XSD/XSL utility package was observed in the automatically retrieved asset set.", ""]
    lines += [
        "## Candidate directory model — hypothesis only until validated",
        "",
        "```text",
        "<application-root>/",
        "└─ 0000/",
        "   ├─ index.xml",
        "   ├─ index-md5.txt",
        "   ├─ m1/",
        "   │  └─ <China regional subtree and regional backbone>",
        "   ├─ m2/ ... m5/ as required by the chosen minimal submission context",
        "   └─ util/",
        "      ├─ dtd-or-schema/",
        "      └─ style/",
        "```",
        "",
        "The exact application-root naming, China Module 1 path, regional XML filename, metadata fields and utility filenames must be populated from the effective official package—not from this schematic.",
        "",
        "## Baseline construction gates",
        "",
        "1. Freeze official utility package files byte-for-byte and record hashes.",
        "2. Select one minimal allowed submission context; list every required China regional metadata field.",
        "3. Generate backbone XML from typed metadata and validate with the shipped DTD/XSD without network resolution.",
        "4. Include one searchable, linearized, bookmarked PDF leaf that passes all applicable 6.1–6.26 rules.",
        "5. Compute leaf MD5 over final bytes, serialize XML once, then compute the required index MD5 over those final XML bytes.",
        "6. Run CDE V1.1.0 and preserve the full report. Iterate until the package is clean without suppressing messages.",
        "7. Freeze the clean package as a read-only baseline, record a complete SHA-256 inventory and never mutate it in place.",
        "8. Run a negative control by changing one byte without updating checksums; confirm package validation catches it.",
        "",
        "## Current blockers",
        "",
        "- No official-validator-clean China baseline has been demonstrated.",
        "- China regional XML metadata requirements remain unresolved unless observed in an official package extracted by this analysis.",
        "- Official V1.1.0 report output format and stable message identifiers are not yet captured.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, default=Path("build/regulatory-source-snapshot/assets"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/ectd-package-analysis"))
    parser.add_argument("--build", type=Path, default=Path("build/ectd-package-analysis"))
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.build.mkdir(parents=True, exist_ok=True)

    observed: list[dict[str, Any]] = []
    extraction_records: list[dict[str, Any]] = []
    assets = sorted(p for p in args.assets.rglob("*") if p.is_file()) if args.assets.exists() else []
    with tempfile.TemporaryDirectory(prefix="ezctd-package-analysis-") as td:
        temp = Path(td)
        for index, asset in enumerate(assets, 1):
            source_id = f"asset-{index:03d}-{sha256(asset)[:16]}"
            destination = temp / source_id
            extraction = extract_archive(asset, destination)
            extraction["source_sha256"] = sha256(asset)
            extraction["source_name"] = asset.name
            extraction_records.append(extraction)
            if extraction["status"] == "EXTRACTED":
                observed.append(inspect_tree(destination, source_id))
            elif asset.suffix.lower() in TEXT_EXTENSIONS:
                single = temp / f"single-{source_id}"
                single.mkdir()
                shutil.copy2(asset, single / asset.name)
                observed.append(inspect_tree(single, source_id))

    payload = {
        "schema_version": "0.1.0",
        "generator": "tools/regulatory/analyze_ectd_packages.py",
        "status": "OBSERVATIONAL_ONLY",
        "safety_scope": "Static archive and XML inspection. No executable was launched and no proprietary program was decompiled.",
        "assets_directory_exists": args.assets.exists(),
        "assets_count": len(assets),
        "extractions": extraction_records,
        "observed": observed,
        "summary": {
            "assets": len(assets),
            "successfully_extracted": sum(item["status"] == "EXTRACTED" for item in extraction_records),
            "trees_analyzed": len(observed),
            "sample_sequence_candidates": sum(item["classification"]["likely_sample_sequence"] for item in observed),
            "packages_with_utility_files": sum(item["classification"]["likely_technical_utility_package"] for item in observed),
            "regional_backbones_observed": sum(len(item["classification"]["regional_backbones"]) for item in observed),
        },
    }
    (args.evidence / "analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.evidence / "MINIMAL_CN_ECTD_BASELINE_SPEC.md").write_text(baseline_markdown(payload), encoding="utf-8")
    (args.evidence / "README.md").write_text(
        "# eCTD technical package analysis\n\nStatic analysis of automatically retrieved CDE/ICH assets. Results are observational and do not certify any package. See `MINIMAL_CN_ECTD_BASELINE_SPEC.md`.\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
