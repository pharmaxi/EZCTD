from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, deque
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ezctd.catalog import RuleCatalog
from ezctd.models import PdfContext
from ezctd.pdf_observer import ExperimentalPdfObserver

XLINK = "http://www.w3.org/1999/xlink"
RULEPACK = ROOT / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json"
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]|^[\\/]{2}")


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": file_hash(path, "sha256"),
                "md5": file_hash(path, "md5"),
                "hidden": any(part.startswith(".") for part in path.relative_to(root).parts),
            }
        )
    return records


def safe_relative_path(raw: str) -> tuple[str | None, str | None]:
    decoded = unquote(raw).replace("\\", "/").strip()
    parsed = urlparse(decoded)
    if parsed.scheme or parsed.netloc or decoded.startswith("/") or WINDOWS_ABSOLUTE.match(decoded):
        return None, "absolute or URI reference"
    pure = PurePosixPath(decoded)
    if not decoded or any(part in {"", ".", ".."} for part in pure.parts):
        return None, "empty or dot-segment reference"
    return pure.as_posix(), None


def resolve_inside(root: Path, relative: str) -> tuple[Path, bool]:
    candidate = (root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        candidate.relative_to(root.resolve())
        return candidate, True
    except ValueError:
        return candidate, False


def load_context_map(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "files" in payload:
        payload = payload["files"]
    if not isinstance(payload, dict):
        raise ValueError("context map must be an object keyed by sequence-relative file path")
    return {str(key).replace("\\", "/"): value for key, value in payload.items()}


def parse_xml_graph(sequence_root: Path, index_xml: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=False, remove_blank_text=False, huge_tree=False)
    queue: deque[Path] = deque([index_xml])
    visited: set[Path] = set()
    documents: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    while queue:
        xml_path = queue.popleft().resolve()
        if xml_path in visited:
            continue
        visited.add(xml_path)
        try:
            relative_xml = xml_path.relative_to(sequence_root.resolve()).as_posix()
        except ValueError:
            errors.append({"kind": "xml-outside-sequence", "path": str(xml_path)})
            continue
        try:
            tree = etree.parse(str(xml_path), parser)
        except Exception as exc:
            errors.append({"kind": "xml-parse", "path": relative_xml, "error": f"{type(exc).__name__}: {exc}"})
            continue

        root = tree.getroot()
        documents.append(
            {
                "path": relative_xml,
                "root_tag": root.tag,
                "doctype": tree.docinfo.doctype or None,
                "encoding": tree.docinfo.encoding,
                "sha256": file_hash(xml_path, "sha256"),
                "md5": file_hash(xml_path, "md5"),
            }
        )

        for node in root.iter():
            raw_href = node.get(f"{{{XLINK}}}href") or node.get("href")
            if raw_href is None:
                continue
            normalized, path_error = safe_relative_path(raw_href)
            reference = {
                "source_xml": relative_xml,
                "element": etree.QName(node).localname,
                "raw_href": raw_href,
                "normalized_href": normalized,
                "operation": node.get("operation"),
                "checksum": node.get("checksum"),
                "checksum_type": node.get("checksum-type") or node.get("checksumType"),
                "title": node.get("title") or node.findtext("title"),
                "path_error": path_error,
                "exists": False,
                "actual_checksum": None,
                "checksum_match": None,
            }
            if normalized is None:
                errors.append({"kind": "unsafe-href", "source_xml": relative_xml, "href": raw_href, "error": path_error})
                references.append(reference)
                continue
            target, inside = resolve_inside(sequence_root, normalized)
            if not inside:
                errors.append({"kind": "href-escapes-sequence", "source_xml": relative_xml, "href": normalized})
                references.append(reference)
                continue
            reference["exists"] = target.is_file()
            if not target.is_file():
                errors.append({"kind": "missing-referenced-file", "source_xml": relative_xml, "href": normalized})
                references.append(reference)
                continue
            checksum_type = (reference["checksum_type"] or "").strip().lower()
            if checksum_type in {"md5", "sha-256", "sha256"}:
                algorithm = "md5" if checksum_type == "md5" else "sha256"
                actual = file_hash(target, algorithm)
                reference["actual_checksum"] = actual
                reference["checksum_match"] = bool(reference["checksum"] and actual.lower() == str(reference["checksum"]).lower())
                if not reference["checksum"]:
                    errors.append({"kind": "missing-checksum", "source_xml": relative_xml, "href": normalized, "checksum_type": checksum_type})
                elif not reference["checksum_match"]:
                    errors.append(
                        {
                            "kind": "checksum-mismatch",
                            "source_xml": relative_xml,
                            "href": normalized,
                            "expected": reference["checksum"],
                            "actual": actual,
                        }
                    )
            elif reference["checksum"] or reference["checksum_type"]:
                errors.append(
                    {
                        "kind": "unsupported-checksum-type",
                        "source_xml": relative_xml,
                        "href": normalized,
                        "checksum_type": reference["checksum_type"],
                    }
                )
            if target.suffix.lower() == ".xml":
                queue.append(target)
            references.append(reference)

    return documents, references, errors


def find_sequence(root: Path) -> tuple[Path | None, Path | None, list[dict[str, Any]]]:
    indexes = sorted(root.rglob("index.xml"))
    errors: list[dict[str, Any]] = []
    if not indexes:
        return None, None, [{"kind": "index-missing", "root": str(root)}]
    if len(indexes) > 1:
        return None, None, [{"kind": "multiple-index-files", "paths": [path.relative_to(root).as_posix() for path in indexes]}]
    index_xml = indexes[0]
    sequence_root = index_xml.parent
    if not re.fullmatch(r"\d{4}", sequence_root.name):
        errors.append({"kind": "sequence-directory-not-four-digits", "path": sequence_root.relative_to(root).as_posix()})
    return sequence_root, index_xml, errors


def verify_index_md5(sequence_root: Path, index_xml: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = [sequence_root / "index-md5.txt", sequence_root / "index-md5"]
    existing = [path for path in candidates if path.is_file()]
    errors: list[dict[str, Any]] = []
    actual = file_hash(index_xml, "md5")
    if not existing:
        return {"present": False, "actual_index_md5": actual}, [{"kind": "index-md5-missing"}]
    if len(existing) > 1:
        errors.append({"kind": "multiple-index-md5-files", "paths": [path.name for path in existing]})
    path = existing[0]
    text = path.read_text(encoding="ascii", errors="replace").strip().split()[0].lower() if path.stat().st_size else ""
    match = text == actual.lower()
    if not match:
        errors.append({"kind": "index-md5-mismatch", "expected_file_value": text, "actual_index_md5": actual})
    return {"present": True, "path": path.name, "recorded": text, "actual_index_md5": actual, "match": match}, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package_root", type=Path)
    parser.add_argument("--context-map", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict-context", action="store_true")
    parser.add_argument("--rulepack", type=Path, default=RULEPACK)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    if not package_root.is_dir():
        raise SystemExit(f"package root not found: {package_root}")
    context_map = load_context_map(args.context_map)
    sequence_root, index_xml, structural_errors = find_sequence(package_root)
    records = inventory(package_root)
    hidden_files = [record["path"] for record in records if record["hidden"]]
    if hidden_files:
        structural_errors.append({"kind": "hidden-files", "paths": hidden_files})

    if sequence_root is None or index_xml is None:
        payload = {
            "schema_version": "0.1.0",
            "status": "INVALID_CANDIDATE",
            "package_root_name": package_root.name,
            "inventory": records,
            "structural_errors": structural_errors,
            "official_validator": {"status": "NOT_RUN", "version": "1.1.0", "observations": 0},
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1

    xml_documents, references, xml_errors = parse_xml_graph(sequence_root, index_xml)
    structural_errors.extend(xml_errors)
    index_md5, md5_errors = verify_index_md5(sequence_root, index_xml)
    structural_errors.extend(md5_errors)

    referenced_files = {reference["normalized_href"] for reference in references if reference["normalized_href"]}
    pdf_paths = sorted(
        sequence_root / Path(*PurePosixPath(relative).parts)
        for relative in referenced_files
        if relative.lower().endswith(".pdf")
    )
    observer = ExperimentalPdfObserver(RuleCatalog.from_json(args.rulepack.resolve()))
    pdf_results = []
    missing_context = []
    finding_counts: Counter[str] = Counter()

    for pdf_path in pdf_paths:
        relative = pdf_path.relative_to(sequence_root).as_posix()
        context = context_map.get(relative)
        if context is None:
            missing_context.append(relative)
            context = {}
        scan = observer.scan(
            PdfContext(
                file_path=pdf_path,
                submission_root=sequence_root,
                node_id=context.get("node_id"),
                document_role=context.get("document_role"),
                language=context.get("language"),
            )
        )
        finding_ids = [finding.rule_id for finding in scan.findings]
        finding_counts.update(finding_ids)
        pdf_results.append(
            {
                "path": relative,
                "context": context,
                "context_status": "MAPPED" if relative not in missing_context else "UNRESOLVED",
                "findings": [finding.to_dict() for finding in scan.findings],
                "diagnostics": scan.diagnostics.to_dict(),
                "engine_status": scan.engine_status,
            }
        )

    if args.strict_context and missing_context:
        structural_errors.append({"kind": "pdf-context-unresolved", "paths": missing_context})

    all_pdf_findings = [finding for result in pdf_results for finding in result["findings"]]
    status = "CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR"
    if structural_errors:
        status = "INVALID_CANDIDATE"
    elif all_pdf_findings:
        status = "CANDIDATE_HAS_EXPERIMENTAL_PDF_FINDINGS"
    elif missing_context:
        status = "CANDIDATE_CONTEXT_INCOMPLETE"

    payload = {
        "schema_version": "0.1.0",
        "status": status,
        "scope": "Read-only package integrity, XML reference/checksum and experimental PDF preflight. No DTD/XSD, lifecycle or official-validator equivalence claim.",
        "package_root_name": package_root.name,
        "sequence_root": sequence_root.relative_to(package_root).as_posix() or ".",
        "index_xml": index_xml.relative_to(sequence_root).as_posix(),
        "inventory": records,
        "index_md5": index_md5,
        "xml_documents": xml_documents,
        "references": references,
        "structural_errors": structural_errors,
        "pdf_count": len(pdf_results),
        "pdf_context_missing": missing_context,
        "finding_counts": dict(sorted(finding_counts.items(), key=lambda item: int(item[0].split(".")[1]))),
        "pdf_results": pdf_results,
        "official_validator": {"status": "NOT_RUN", "version": "1.1.0", "observations": 0},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Candidate China eCTD baseline inspection",
        "",
        f"- Status: **{status}**",
        f"- Sequence root: `{payload['sequence_root']}`",
        f"- Referenced PDF leaves: {len(pdf_results)}",
        f"- Structural errors: {len(structural_errors)}",
        f"- Experimental PDF findings: {len(all_pdf_findings)}",
        f"- Unmapped PDF contexts: {len(missing_context)}",
        "- CDE validator V1.1.0: **NOT_RUN**",
        "",
        "## Structural errors",
        "",
    ]
    if structural_errors:
        lines.extend(f"- `{item['kind']}`: `{json.dumps(item, ensure_ascii=False)}`" for item in structural_errors)
    else:
        lines.append("- None in the implemented package checks.")
    lines += ["", "## PDF findings by file", ""]
    for result in pdf_results:
        finding_ids = ", ".join(finding["rule_id"] for finding in result["findings"]) or "none"
        lines.append(f"- `{result['path']}` — context {result['context_status']}; findings: {finding_ids}")
    lines += [
        "",
        "Passing this inspector means only that the candidate is internally consistent within the implemented checks. The package must still be validated with the official CDE V1.1.0 software and its full original report preserved.",
        "",
    ]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "pdfs": len(pdf_results), "structural_errors": len(structural_errors), "pdf_findings": len(all_pdf_findings)}, ensure_ascii=False))
    return 0 if status == "CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
