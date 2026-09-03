from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .catalog import RuleCatalog
from .models import PdfContext
from .pdf_observer import ExperimentalPdfObserver


def _default_rulepack() -> Path:
    candidates = [
        Path.cwd() / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json",
        Path(__file__).resolve().parents[2] / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("verified CDE V1.1 rulepack not found; pass --rulepack")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ezctd",
        description="Experimental read-only CDE PDF rule observer. It does not claim equivalence to the CDE validator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan-pdf", help="Read a PDF and emit evidence-backed experimental findings")
    scan.add_argument("pdf", type=Path)
    scan.add_argument("--submission-root", type=Path)
    scan.add_argument("--node-id")
    scan.add_argument("--document-role")
    scan.add_argument("--language")
    scan.add_argument("--rulepack", type=Path)
    scan.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "scan-pdf":
        raise AssertionError(args.command)
    pdf_path = args.pdf.resolve()
    if not pdf_path.is_file():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 2
    submission_root = (args.submission_root or pdf_path.parent).resolve()
    catalog = RuleCatalog.from_json((args.rulepack or _default_rulepack()).resolve())
    observer = ExperimentalPdfObserver(catalog)
    result = observer.scan(
        PdfContext(
            file_path=pdf_path,
            submission_root=submission_root,
            node_id=args.node_id,
            document_role=args.document_role,
            language=args.language,
        )
    ).to_dict()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 1 if any(finding["severity"] == "错误" for finding in result["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
