from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .safe_io import UnsafeOutputError, sha256_file, validate_new_output, write_new_text


def _default_rulepack() -> Path:
    relative = Path('rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json')
    for candidate in (Path.cwd() / relative, Path(__file__).resolve().parents[2] / relative):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError('verified CDE V1.1 rulepack not found; pass --rulepack')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='ezctd', description='Experimental CRO PDF workbench; no whole-submission compliance claim.')
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan-pdf', help='Experimental read-only PDF observation')
    scan.add_argument('pdf', type=Path)
    scan.add_argument('--submission-root', type=Path)
    scan.add_argument('--node-id')
    scan.add_argument('--document-role')
    scan.add_argument('--language')
    scan.add_argument('--rulepack', type=Path)
    scan.add_argument('--output', type=Path)
    report = sub.add_parser('import-cde-report', help='Import section 6; never open linked files')
    report.add_argument('report', type=Path)
    report.add_argument('--output', type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = (args.pdf if args.command == 'scan-pdf' else args.report).resolve(strict=True)
        if not source.is_file():
            raise ValueError('Input must be a regular file')
        root = ((args.submission_root or source.parent).resolve(strict=True)
                if args.command == 'scan-pdf' else source.parent)
        if not root.is_dir() or not source.is_relative_to(root):
            raise ValueError('Input must be inside the selected input root')
        # Check output before importing native PDF dependencies or scanning.
        if args.output:
            validate_new_output(args.output, inputs=(source,), input_roots=(root,))
        before = sha256_file(source)
        if args.command == 'import-cde-report':
            from .cde_report import load_report
            result = load_report(source)
            code = 0 if result['parse_state'] == 'PARSED_COUNTS_RECONCILED' else 2
        else:
            from .catalog import RuleCatalog
            from .models import PdfContext
            from .pdf_observer import ExperimentalPdfObserver
            catalog = RuleCatalog.from_json((args.rulepack or _default_rulepack()).resolve())
            result = ExperimentalPdfObserver(catalog).scan(PdfContext(
                file_path=source, submission_root=root, node_id=args.node_id,
                document_role=args.document_role, language=args.language,
            )).to_dict()
            # Previous per-rule completion accounting remains under review.
            # Never let an empty finding list imply a fully verified clean scan.
            result['completion_assurance'] = 'EXPERIMENTAL_INDETERMINATE'
            result['compliance_conclusion'] = 'NOT_ESTABLISHED'
            result['legacy_rules_evaluated_are_not_coverage_proof'] = True
            code = 1 if any(f['severity'] == '错误' for f in result['findings']) else 3
        after = sha256_file(source)
        if after != before:
            raise RuntimeError('Input changed during processing; result not published')
        result['input_integrity'] = {'sha256_before': before, 'sha256_after': after, 'unchanged': True}
        text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            write_new_text(args.output, text, inputs=(source,), input_roots=(root,))
        else:
            sys.stdout.write(text)
        return code
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'EZCTD stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
