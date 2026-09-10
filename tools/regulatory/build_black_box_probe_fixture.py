from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def inventory(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": digest,
            }
        )
    return records


def inventory_digest(records: list[dict[str, Any]]) -> str:
    canonical = "\n".join(
        f"{item['path']}\t{item['size']}\t{item['sha256']}" for item in records
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        type=Path,
        default=Path(
            "rulepacks/cn-cde-ectd/v1.1/black-box-cases/"
            "cn-v11-probe-000-invalid-empty-root.json"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    definition = read_json(args.case)
    case_id = str(definition["case_id"])
    case_root = args.output / case_id
    input_root = case_root / "input"
    if case_root.exists():
        shutil.rmtree(case_root)
    input_root.mkdir(parents=True, exist_ok=True)

    records = inventory(input_root)
    digest = inventory_digest(records)
    expected = definition["input"]
    if records:
        raise RuntimeError("empty-root probe contains files")
    if expected["file_count"] != 0:
        raise RuntimeError("case definition does not specify an empty input")
    if digest != expected["inventory_digest"]:
        raise RuntimeError(
            f"empty inventory digest mismatch: expected={expected['inventory_digest']} actual={digest}"
        )

    manifest = {
        "schema_version": "0.1.0",
        "case_id": case_id,
        "profile": definition["profile"],
        "input_directory": str(input_root.resolve()),
        "file_count": len(records),
        "files": records,
        "inventory_digest": digest,
        "data_classification": definition["data_classification"],
        "definition_path": args.case.as_posix(),
        "validation_invoked": False,
        "native_result_present": False,
        "official_black_box_observation_eligible": False,
    }
    write_json(case_root / "input-manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
