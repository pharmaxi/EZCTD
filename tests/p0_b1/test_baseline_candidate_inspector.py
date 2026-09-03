from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = ROOT / "tools" / "ectd" / "inspect_baseline_candidate.py"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def make_package(root: Path, source_pdf: Path, *, correct_leaf_checksum: bool = True, context: bool = True) -> tuple[Path, Path | None]:
    package = root / "application"
    sequence = package / "0000"
    leaf = sequence / "m5" / "leaf.pdf"
    leaf.parent.mkdir(parents=True)
    shutil.copy2(source_pdf, leaf)
    checksum = md5(leaf) if correct_leaf_checksum else "0" * 32
    index = sequence / "index.xml"
    index.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ectd xmlns:xlink="http://www.w3.org/1999/xlink">'
        f'<leaf xlink:href="m5/leaf.pdf" checksum="{checksum}" checksum-type="md5" operation="new">'
        '<title>Searchable baseline leaf</title>'
        '</leaf>'
        '</ectd>',
        encoding="utf-8",
    )
    (sequence / "index-md5.txt").write_text(md5(index) + "\n", encoding="ascii")
    context_path = None
    if context:
        context_path = root / "context.json"
        context_path.write_text(
            json.dumps(
                {
                    "files": {
                        "m5/leaf.pdf": {
                            "node_id": "5.3.5",
                            "document_role": "study-report",
                            "language": "zh-CN"
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return package, context_path


def run_inspector(package: Path, output: Path, context: Path | None, strict: bool) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(INSPECTOR), str(package), "--output", str(output)]
    if context is not None:
        command.extend(["--context-map", str(context)])
    if strict:
        command.append("--strict-context")
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_baseline_candidate_inspector.py <baseline-smoke-pdf>")
    source_pdf = Path(sys.argv[1]).resolve()
    if not source_pdf.is_file():
        raise SystemExit(f"baseline smoke PDF not found: {source_pdf}")

    results = []
    with tempfile.TemporaryDirectory(prefix="ezctd-baseline-inspector-") as td:
        temp = Path(td)

        valid_root = temp / "valid"
        package, context = make_package(valid_root, source_pdf, correct_leaf_checksum=True, context=True)
        valid_output = valid_root / "result.json"
        valid_run = run_inspector(package, valid_output, context, strict=True)
        valid_payload = json.loads(valid_output.read_text(encoding="utf-8"))
        assert valid_run.returncode == 0, valid_run.stderr + valid_run.stdout
        assert valid_payload["status"] == "CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR"
        assert valid_payload["structural_errors"] == []
        assert valid_payload["pdf_count"] == 1
        assert valid_payload["pdf_results"][0]["findings"] == []
        results.append({"case": "valid-candidate", "status": valid_payload["status"]})

        bad_checksum_root = temp / "bad-checksum"
        package, context = make_package(bad_checksum_root, source_pdf, correct_leaf_checksum=False, context=True)
        bad_checksum_output = bad_checksum_root / "result.json"
        bad_checksum_run = run_inspector(package, bad_checksum_output, context, strict=True)
        bad_checksum_payload = json.loads(bad_checksum_output.read_text(encoding="utf-8"))
        assert bad_checksum_run.returncode == 1
        assert bad_checksum_payload["status"] == "INVALID_CANDIDATE"
        assert any(error["kind"] == "checksum-mismatch" for error in bad_checksum_payload["structural_errors"])
        results.append({"case": "leaf-checksum-mismatch", "status": bad_checksum_payload["status"]})

        no_context_root = temp / "no-context"
        package, _ = make_package(no_context_root, source_pdf, correct_leaf_checksum=True, context=False)
        no_context_output = no_context_root / "result.json"
        no_context_run = run_inspector(package, no_context_output, None, strict=True)
        no_context_payload = json.loads(no_context_output.read_text(encoding="utf-8"))
        assert no_context_run.returncode == 1
        assert no_context_payload["status"] == "INVALID_CANDIDATE"
        assert any(error["kind"] == "pdf-context-unresolved" for error in no_context_payload["structural_errors"])
        results.append({"case": "strict-context-missing", "status": no_context_payload["status"]})

    report = {"schema_version": "0.1.0", "status": "PASS", "tests": results}
    output = ROOT / "build" / "p0-b1-package-inspector-tests.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
