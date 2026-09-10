from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tools" / "regulatory" / "import_official_assets.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"patch point not found: {label}")
    return text.replace(old, new, 1)


text = TARGET.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''def sniff(path: Path) -> str:
    head = path.read_bytes()[:16]
''',
    '''def sniff(path: Path) -> str:
    # Never read an entire installer/archive merely to inspect its magic bytes.
    with path.open("rb") as handle:
        head = handle.read(16)
''',
    "bounded magic-byte read",
)

text = replace_once(
    text,
    '''    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--copy", action="store_true", help="Copy matched binaries into the outside-Git local evidence store")
''',
    '''    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--copy", action="store_true", help="Copy matched binaries into the outside-Git local evidence store")
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=MAX_FILE_BYTES,
        help="Reject a candidate before hashing or archive inspection when it exceeds this size.",
    )
''',
    "configurable early size limit",
)

old_record_block = '''        path = matches[0]
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
'''
new_record_block = '''        path = matches[0]
        extension = path.suffix.lower()
        extension_ok = extension in set(definition["expected_extensions"])
        size = path.stat().st_size
        source_url = definition.get("source_url")
        url_status = official_url_status(source_url, official_hosts)

        # Size is a pre-read guard. Oversized files are not hashed, sniffed, copied,
        # or handed to an archive parser. This prevents a malformed/manual download
        # from turning evidence intake into an unbounded I/O operation.
        if size > args.max_file_bytes:
            record = {
                **definition,
                "status": "REJECTED_OVERSIZE",
                "source_basename": path.name,
                "size": size,
                "extension": extension,
                "extension_expected": extension_ok,
                "magic": None,
                "mime_guess": mimetypes.guess_type(path.name)[0],
                "sha256": None,
                "sm3": None,
                "source_url_status": url_status,
                "archive": {"status": "NOT_INSPECTED_OVERSIZE", "kind": None, "members": []},
                "local_store_relative_path": None,
                "raw_source_path_committed": False,
            }
            failures.append(
                {
                    "asset_id": definition["asset_id"],
                    "error": f"file exceeds configured limit {args.max_file_bytes} bytes; hashing and archive inspection skipped",
                }
            )
            records.append(record)
            continue

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
        if not extension_ok:
'''
text = replace_once(text, old_record_block, new_record_block, "early oversize rejection")

text = replace_once(
    text,
    '''    counts: dict[str, int] = {}
    for record in records:
''',
    '''    # One exact binary must not silently satisfy several regulatory roles.
    # A combined official package may contain multiple assets, but the package itself
    # should be registered under one package role and its members inventoried separately.
    records_by_sha: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        digest = record.get("sha256")
        if digest:
            records_by_sha.setdefault(str(digest), []).append(record)
    for digest, duplicate_records in records_by_sha.items():
        asset_ids = sorted({str(record["asset_id"]) for record in duplicate_records})
        if len(asset_ids) <= 1:
            continue
        for record in duplicate_records:
            record["status"] = "DUPLICATE_BINARY_REUSED_ACROSS_ROLES"
        failures.append(
            {
                "asset_id": ",".join(asset_ids),
                "error": f"the same SHA-256 {digest} was matched to multiple asset roles; split the intake definition or identify archive members",
            }
        )

    counts: dict[str, int] = {}
    for record in records:
''',
    "duplicate role/hash audit",
)

TARGET.write_text(text, encoding="utf-8", newline="\n")
print("manual official-asset intake hardened")
