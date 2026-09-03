from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IMPORTER = ROOT / "tools" / "regulatory" / "import_official_assets.py"


def intake_asset(
    asset_id: str,
    *,
    source_url: str | None,
    pattern: str = "*.pdf",
    required: bool = True,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "title": asset_id,
        "required": required,
        "authority": "CDE/NMPA",
        "source_url": source_url,
        "file_globs": [pattern],
        "expected_extensions": [".pdf"],
        "expected_version": "V1.1",
    }


def write_intake(path: Path, assets: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": "0.1.0",
        "intake_id": "manual-import-self-test",
        "policy": {
            "official_hosts": ["www.cde.org.cn", "cde.org.cn", "www.nmpa.gov.cn", "nmpa.gov.cn"],
            "raw_binary_storage": "outside-git",
            "no_execution": True,
            "no_decompilation": True,
        },
        "assets": assets,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_import(
    source: Path,
    intake: Path,
    output: Path,
    *,
    strict: bool = True,
    max_bytes: int = 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(IMPORTER),
        "--source-dir",
        str(source),
        "--intake",
        str(intake),
        "--output",
        str(output),
        "--max-file-bytes",
        str(max_bytes),
    ]
    if strict:
        command.append("--strict")
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def make_pdf(path: Path, *, extra_bytes: int = 0) -> None:
    path.write_bytes(b"%PDF-1.7\n% manual intake fixture\n" + b"x" * extra_bytes)


def main() -> int:
    results: list[dict[str, Any]] = []
    official_url = "https://www.cde.org.cn/main/att/download/0123456789abcdef0123456789abcdef"

    with tempfile.TemporaryDirectory(prefix="ezctd-manual-intake-") as temp_dir:
        temp = Path(temp_dir)

        # Valid, official-provenance PDF.
        valid = temp / "valid"
        valid.mkdir()
        make_pdf(valid / "official-v1.1.pdf")
        valid_intake = temp / "valid-intake.json"
        write_intake(valid_intake, [intake_asset("OFFICIAL-PDF", source_url=official_url)])
        valid_output = temp / "valid-output.json"
        valid_run = run_import(valid, valid_intake, valid_output)
        valid_payload = json.loads(valid_output.read_text(encoding="utf-8"))
        assert valid_run.returncode == 0, valid_run.stderr + valid_run.stdout
        assert valid_payload["failures"] == []
        assert valid_payload["assets"][0]["status"] == "IMPORTED"
        assert valid_payload["assets"][0]["source_url_status"] == "OFFICIAL_HOST"
        assert valid_payload["assets"][0]["magic"] == "pdf"
        assert len(valid_payload["assets"][0]["sha256"]) == 64
        results.append({"case": "official-pdf-imported", "status": "PASS"})

        # Missing required file.
        missing = temp / "missing"
        missing.mkdir()
        missing_intake = temp / "missing-intake.json"
        write_intake(missing_intake, [intake_asset("MISSING-PDF", source_url=official_url)])
        missing_output = temp / "missing-output.json"
        missing_run = run_import(missing, missing_intake, missing_output)
        missing_payload = json.loads(missing_output.read_text(encoding="utf-8"))
        assert missing_run.returncode == 1
        assert missing_payload["assets"][0]["status"] == "MISSING_REQUIRED"
        results.append({"case": "missing-required-rejected", "status": "PASS"})

        # File is present but official provenance has not been recorded.
        unresolved = temp / "unresolved"
        unresolved.mkdir()
        make_pdf(unresolved / "unresolved.pdf")
        unresolved_intake = temp / "unresolved-intake.json"
        write_intake(
            unresolved_intake,
            [intake_asset("UNRESOLVED-PDF", source_url="https://mirror.invalid/unresolved.pdf")],
        )
        unresolved_output = temp / "unresolved-output.json"
        unresolved_run = run_import(unresolved, unresolved_intake, unresolved_output)
        unresolved_payload = json.loads(unresolved_output.read_text(encoding="utf-8"))
        assert unresolved_run.returncode == 1
        assert unresolved_payload["assets"][0]["status"] == "IMPORTED_PROVENANCE_UNRESOLVED"
        assert unresolved_payload["assets"][0]["source_url_status"] == "NON_OFFICIAL_HOST"
        results.append({"case": "provenance-unresolved-rejected-in-strict-mode", "status": "PASS"})

        # Oversize guard must trigger before hashing/sniffing/archive inspection.
        oversized = temp / "oversized"
        oversized.mkdir()
        make_pdf(oversized / "oversized.pdf", extra_bytes=256)
        oversized_intake = temp / "oversized-intake.json"
        write_intake(oversized_intake, [intake_asset("OVERSIZED-PDF", source_url=official_url)])
        oversized_output = temp / "oversized-output.json"
        oversized_run = run_import(oversized, oversized_intake, oversized_output, max_bytes=32)
        oversized_payload = json.loads(oversized_output.read_text(encoding="utf-8"))
        oversized_record = oversized_payload["assets"][0]
        assert oversized_run.returncode == 1
        assert oversized_record["status"] == "REJECTED_OVERSIZE"
        assert oversized_record["sha256"] is None
        assert oversized_record["sm3"] is None
        assert oversized_record["magic"] is None
        assert oversized_record["archive"]["status"] == "NOT_INSPECTED_OVERSIZE"
        results.append({"case": "oversize-rejected-before-read", "status": "PASS"})

        # The same exact binary may not silently satisfy two official roles.
        duplicate = temp / "duplicate"
        duplicate.mkdir()
        make_pdf(duplicate / "combined.pdf")
        duplicate_intake = temp / "duplicate-intake.json"
        write_intake(
            duplicate_intake,
            [
                intake_asset("ROLE-A", source_url=official_url, pattern="combined.pdf"),
                intake_asset("ROLE-B", source_url=official_url, pattern="combined.pdf"),
            ],
        )
        duplicate_output = temp / "duplicate-output.json"
        duplicate_run = run_import(duplicate, duplicate_intake, duplicate_output)
        duplicate_payload = json.loads(duplicate_output.read_text(encoding="utf-8"))
        assert duplicate_run.returncode == 1
        assert {
            record["status"] for record in duplicate_payload["assets"]
        } == {"DUPLICATE_BINARY_REUSED_ACROSS_ROLES"}
        assert any("same SHA-256" in failure["error"] for failure in duplicate_payload["failures"])
        results.append({"case": "duplicate-binary-role-reuse-rejected", "status": "PASS"})

    report = {
        "schema_version": "0.1.0",
        "status": "PASS",
        "tests": results,
        "raw_binaries_committed": False,
    }
    output = ROOT / "build" / "manual-asset-import-contract.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
