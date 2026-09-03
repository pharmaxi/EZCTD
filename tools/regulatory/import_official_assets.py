from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MAX_FILE_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20000


def hash_file(path: Path, algorithm: str) -> str | None:
    try:
        digest = hashlib.new(algorithm)
    except ValueError:
        return None
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sniff(path: Path) -> str:
    head = path.read_bytes()[:16]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"MZ"):
        return "pe"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"
    return "unknown"


def archive_inventory(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "NOT_ARCHIVE", "kind": None, "members": []}
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ARCHIVE_MEMBERS:
                    raise RuntimeError(f"archive has {len(infos)} members")
                members = []
                for info in infos:
                    normalized = Path(info.filename.replace("\\", "/"))
                    if normalized.is_absolute() or ".." in normalized.parts:
                        raise RuntimeError(f"unsafe archive path: {info.filename}")
                    members.append(
                        {
                            "path": info.filename,
                            "size": info.file_size,
                            "compressed_size": info.compress_size,
                            "is_directory": info.is_dir(),
                        }
                    )
                return {"status": "LISTED", "kind": "zip", "members": members}
        seven_zip = shutil.which("7z") or shutil.which("7zz")
        if seven_zip and path.suffix.lower() in {".rar", ".7z", ".exe", ".msi"}:
            process = subprocess.run(
                [seven_zip, "l", "-slt", str(path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
            )
            if process.returncode != 0:
                return {"status": "LIST_FAILED", "kind": "7z-supported", "members": [], "error": (process.stderr or process.stdout)[-3000:]}
            members = []
            current: dict[str, str] = {}
            for line in process.stdout.splitlines() + [""]:
                if not line.strip():
                    if current.get("Path") and current.get("Path") not in {str(path), path.name}:
                        candidate = Path(current["Path"].replace("\\", "/"))
                        if candidate.is_absolute() or ".." in candidate.parts:
                            raise RuntimeError(f"unsafe archive path: {current['Path']}")
                        members.append(
                            {
                                "path": current["Path"],
                                "size": int(current.get("Size", "0") or 0),
                                "is_directory": current.get("Folder") == "+",
                            }
                        )
                    current = {}
                    continue
                if " = " in line:
                    key, value = line.split(" = ", 1)
                    current[key.strip()] = value.strip()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise RuntimeError(f"archive has {len(members)} members")
            return {"status": "LISTED", "kind": "7z-supported", "members": members}
    except Exception as exc:
        result.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    return result


def match_asset(source_dir: Path, definition: dict[str, Any]) -> list[Path]:
    matches: set[Path] = set()
    for pattern in definition["file_globs"]:
        for path in source_dir.rglob(pattern):
            if path.is_file() and not path.is_symlink():
                matches.add(path.resolve())
    return sorted(matches)


def official_url_status(url: str | None, official_hosts: set[str]) -> str:
    if not url:
        return "UNRECORDED"
    host = urlparse(url).netloc.lower()
    return "OFFICIAL_HOST" if host in official_hosts else "NON_OFFICIAL_HOST"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True, help="Directory populated by a manual browser download")
    parser.add_argument("--intake", type=Path, default=Path("evidence/regulatory/manual-asset-intake.template.json"))
    parser.add_argument("--output", type=Path, default=Path("evidence/regulatory/manual-import/manifest.json"))
    parser.add_argument("--local-store", type=Path, default=Path.home() / ".ezctd" / "regulatory-assets")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--copy", action="store_true", help="Copy matched binaries into the outside-Git local evidence store")
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"source directory not found: {source_dir}")
    intake = json.loads(args.intake.read_text(encoding="utf-8"))
    official_hosts = set(intake["policy"]["official_hosts"])
    records = []
    failures = []

    for definition in intake["assets"]:
        matches = match_asset(source_dir, definition)
        if not matches:
            status = "MISSING_REQUIRED" if definition["required"] else "MISSING_OPTIONAL"
            record = {**definition, "status": status, "matches": []}
            records.append(record)
            if definition["required"]:
                failures.append({"asset_id": definition["asset_id"], "error": "no matching file"})
            continue
        if len(matches) > 1:
            record = {**definition, "status": "AMBIGUOUS_MULTIPLE_MATCHES", "matches": [path.name for path in matches]}
            records.append(record)
            failures.append({"asset_id": definition["asset_id"], "error": f"multiple matches: {[path.name for path in matches]}"})
            continue

        path = matches[0]
        extension = path.suffix.lower()
        extension_ok = extension in set(definition["expected_extensions"])
        size = path.stat().st_size
        source_url = definition.get("source_url")
        url_status = official_url_status(source_url, official_hosts)
        record = {
            **definition,
            "status": "IMPORTED",
            "source_basename": path.name,
            "size": size,
            "extension": extension,
            "extension_expected": extension_ok,
            "magic": sniff(path),
            "mime_guess": mimetypes.guess_type(path.name)[0],
            "sha256": hash_file(path, "sha256"),
            "sm3": hash_file(path, "sm3"),
            "source_url_status": url_status,
            "archive": archive_inventory(path),
            "local_store_relative_path": None,
            "raw_source_path_committed": False,
        }
        if size > MAX_FILE_BYTES:
            record["status"] = "REJECTED_OVERSIZE"
            failures.append({"asset_id": definition["asset_id"], "error": f"file exceeds {MAX_FILE_BYTES} bytes"})
        if not extension_ok:
            record["status"] = "REJECTED_EXTENSION_MISMATCH"
            failures.append({"asset_id": definition["asset_id"], "error": f"unexpected extension {extension}"})
        if definition["authority"] in {"CDE/NMPA", "ICH"} and url_status != "OFFICIAL_HOST":
            record["status"] = "IMPORTED_PROVENANCE_UNRESOLVED"
            failures.append({"asset_id": definition["asset_id"], "error": "official source URL not recorded or not on an approved official host"})

        if args.copy and record["status"] in {"IMPORTED", "IMPORTED_PROVENANCE_UNRESOLVED"}:
            destination_dir = args.local_store.expanduser().resolve() / definition["asset_id"] / record["sha256"]
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / path.name
            if destination.exists() and hash_file(destination, "sha256") != record["sha256"]:
                raise RuntimeError(f"local evidence collision: {destination}")
            if not destination.exists():
                shutil.copy2(path, destination)
            record["local_store_relative_path"] = f"{definition['asset_id']}/{record['sha256']}/{path.name}"

        records.append(record)

    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    payload = {
        "schema_version": "0.1.0",
        "intake_id": intake["intake_id"],
        "source_directory_recorded": False,
        "local_store_root": "~/.ezctd/regulatory-assets",
        "policy": intake["policy"],
        "counts": counts,
        "failures": failures,
        "assets": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown = args.output.with_suffix(".md")
    lines = [
        "# Manual regulatory asset import",
        "",
        "> Raw files remain outside Git. This manifest records role, provenance status, hashes, type and archive members. `IMPORTED_PROVENANCE_UNRESOLVED` is not equivalent to an official asset.",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines += ["", "## Assets", "", "| ID | Status | File | SHA-256 | URL provenance |", "|---|---|---|---|---|"]
    for record in records:
        lines.append(
            f"| `{record['asset_id']}` | `{record['status']}` | {record.get('source_basename', '—')} | "
            f"`{record.get('sha256', '—')}` | {record.get('source_url_status', '—')} |"
        )
    lines += ["", "## Failures", ""]
    if failures:
        lines.extend(f"- `{item['asset_id']}`: {item['error']}" for item in failures)
    else:
        lines.append("- None.")
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"counts": counts, "failures": len(failures)}, ensure_ascii=False))
    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
