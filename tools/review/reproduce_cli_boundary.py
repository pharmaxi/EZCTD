"""Historical CLI safety probe, NOT a full PDF scanner test.

Only temporary synthetic files are written. Parser dependencies are stubbed to
isolate the real CLI output boundary. The expected Git blob prevents applying
this historical result to a different or repaired CLI. No real PDF is opened.

Run from repository root:
  python tools/review/reproduce_cli_boundary.py --output build/review-cli.json
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types

EXPECTED_BLOB = "83cfc668889675be12b2b090a6b62422d8657626"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def load_cli(source: Path):
    raw = source.read_bytes()
    if git_blob_sha(raw) != EXPECTED_BLOB:
        raise ValueError("CLI differs from the reviewed Git blob; historical probe not applicable")
    pkg = types.ModuleType("audit_subject")
    pkg.__path__ = []
    sys.modules["audit_subject"] = pkg
    catalog = types.ModuleType("audit_subject.catalog")
    catalog.RuleCatalog = type("RuleCatalog", (), {"from_json": staticmethod(lambda path: object())})
    models = types.ModuleType("audit_subject.models")
    models.PdfContext = lambda **values: types.SimpleNamespace(**values)
    observer = types.ModuleType("audit_subject.pdf_observer")

    class ExperimentalPdfObserver:
        def __init__(self, catalog):
            pass

        def scan(self, context):
            return types.SimpleNamespace(to_dict=lambda: {"findings": [], "audit_stub": True})

    observer.ExperimentalPdfObserver = ExperimentalPdfObserver
    for short, module in [("catalog", catalog), ("models", models), ("pdf_observer", observer)]:
        sys.modules["audit_subject." + short] = module
    spec = importlib.util.spec_from_file_location("audit_subject.cli", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "src/ezctd/cli.py")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite an existing audit report")
    module = load_cli(args.source)
    rows = []
    with tempfile.TemporaryDirectory(prefix="ezctd-audit-") as td:
        root = Path(td)
        for case in ("same_path", "hardlink_alias", "symlink_alias"):
            folder = root / case
            folder.mkdir()
            original = folder / "synthetic.pdf"
            original.write_bytes(b"%PDF-1.7\n% Synthetic boundary test only; parser is stubbed.\n%%EOF\n")
            output = original if case == "same_path" else folder / "report.json"
            try:
                if case == "hardlink_alias":
                    os.link(original, output)
                elif case == "symlink_alias":
                    output.symlink_to(original)
            except OSError as exc:
                rows.append({"case": case, "status": "NOT_RUN", "reason": type(exc).__name__})
                continue
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            code = module.main(["scan-pdf", str(original), "--rulepack", str(folder / "stub.json"), "--output", str(output)])
            after = hashlib.sha256(original.read_bytes()).hexdigest()
            rows.append({"case": case, "exit_code": code, "input_sha256_before": before, "input_sha256_after": after, "input_changed": before != after, "starts_with_pdf": original.read_bytes().startswith(b"%PDF-"), "status": "DEFECT_REPRODUCED" if before != after else "NOT_REPRODUCED"})
    payload = {"reviewed_commit": "8d2bf4457c6423c02dcddf4cb92f3bd6e72b294a", "source_blob_sha1": EXPECTED_BLOB, "source_identity_verified": True, "test_level": "CLI_UNIT_ISOLATION_WITH_STUBBED_PARSER", "full_scanner_executed": False, "all_inputs_synthetic_temporary": True, "cases": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
