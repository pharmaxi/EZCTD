from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys

from .process_runner import run_worker
from .read_scope import ReadScope, selected_path
from .safe_io import sha256_file, validate_new_output, write_new_bytes, write_new_text


def _default_rulepack() -> Path:
    relative = Path('rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json')
    for candidate in (Path.cwd() / relative, Path(__file__).resolve().parents[2] / relative):
        if candidate.is_file():
            return candidate
    bundled = Path(__file__).parent / 'data' / 'cde_ectd_v1_1.json'
    if bundled.is_file():
        return bundled
    raise FileNotFoundError('verified CDE V1.1 rulepack not found; pass --rulepack')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='ezctd', description='Clinical CRO PDF workbench; no complete submission required.')
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan-pdf', help='Read-only PDF observations with per-rule completion status')
    scan.add_argument('pdf', type=Path)
    scan.add_argument('--submission-root', type=Path)
    scan.add_argument('--node-id')
    scan.add_argument('--document-role')
    scan.add_argument('--language')
    batch = sub.add_parser('scan-directory', help='Scan a partial clinical PDF folder without XML backbones')
    batch.add_argument('root', type=Path)
    batch.add_argument('--context-map', type=Path)
    batch.add_argument('--html', type=Path)
    for command in (scan, batch):
        command.add_argument('--reference-root', type=Path, action='append', default=[])
        command.add_argument('--rulepack', type=Path)
        command.add_argument('--timeout', type=float, default=60)
        command.add_argument('--output', type=Path, required=command is batch)
    for name in ('inspect-copy', 'linearize-copy'):
        copy = sub.add_parser(name, help='Inspect guards or produce one verified unsigned PDF copy')
        copy.add_argument('pdf', type=Path)
        copy.add_argument('--output', type=Path, required=name == 'linearize-copy')
        copy.add_argument('--timeout', type=float, default=300)
        if name == 'linearize-copy':
            copy.add_argument('--expected-sha256', required=True)
            copy.add_argument('--approve', action='store_true')
    report = sub.add_parser('import-cde-report', help='Import section 6; never open linked files')
    report.add_argument('report', type=Path)
    report.add_argument('--output', type=Path, required=True)
    for name in ('inspect-page', 'render-page'):
        page = sub.add_parser(name, help='Read page geometry/text or export bounded PNG preview')
        page.add_argument('pdf', type=Path)
        page.add_argument('--page', type=int, default=1)
        page.add_argument('--timeout', type=float, default=60)
        page.add_argument('--output', type=Path, required=name == 'render-page')
        if name == 'inspect-page':
            page.add_argument('--query')
        else:
            page.add_argument('--dpi', type=int, default=120)
    return parser


def _scan_exit(result: dict) -> int:
    rows = result.get('rule_evaluations', [])
    if any(row['status'] == 'FAIL' for row in rows):
        return 1
    return 3 if not rows or any(row['status'] in ('NOT_RUN', 'INDETERMINATE') for row in rows) else 0


def _stdout(text: str) -> None:
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout.buffer.write(text.encode('utf-8'))
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in ('inspect-copy', 'linearize-copy'):
            from .copy_service import inspect_linearization, linearize_copy
            source = selected_path(args.pdf)
            roots = (source.parent,)
            expected = sha256_file(source)
            if args.command == 'linearize-copy':
                if not args.approve:
                    raise ValueError('Explicit --approve is required after reviewing inspect-copy output')
                if args.expected_sha256 != expected:
                    raise ValueError('Input differs from reviewed identity')
                result = linearize_copy(source, args.output, roots=roots, expected=expected, timeout=args.timeout)
            else:
                result = inspect_linearization(source, roots=roots, expected=expected, timeout=args.timeout)
            text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
            if args.command == 'inspect-copy' and args.output:
                write_new_text(args.output, text, inputs=(source,), input_roots=roots)
            else:
                _stdout(text)
            return 0 if result.get('eligibility') != 'BLOCKED' else 3
        if args.command == 'scan-directory':
            from .batch import scan_directory, render_batch_html
            root = selected_path(args.root, directory=True)
            references = tuple(selected_path(p, directory=True) for p in args.reference_root)
            context_file = selected_path(args.context_map) if args.context_map else None
            rulepack = selected_path(args.rulepack or _default_rulepack())
            protected = (rulepack,) + ((context_file,) if context_file else ())
            roots = (root, *references)
            validate_new_output(args.output, inputs=protected, input_roots=roots)
            if args.html:
                validate_new_output(args.html, inputs=protected, input_roots=roots)
                if args.html.absolute() == args.output.absolute():
                    raise ValueError('JSON and HTML must have distinct output paths')
            if context_file and context_file.stat().st_size > 1024 * 1024:
                raise ValueError('Context map exceeds 1 MiB')
            contexts = json.loads(context_file.read_text(encoding='utf-8')) if context_file else {}
            if not isinstance(contexts, dict):
                raise ValueError('Context map must be a JSON object keyed by relative path')
            result = scan_directory(root, rulepack=rulepack, contexts=contexts,
                                    reference_roots=references, timeout=args.timeout)
            write_new_text(args.output, json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                           inputs=protected, input_roots=roots)
            if args.html:
                write_new_text(args.html, render_batch_html(result), inputs=protected, input_roots=roots)
            if any(r['worker_status'] != 'OK' for r in result['files']) or not result['files']:
                return 2
            codes = [_scan_exit(r) for r in result['files']]
            return 1 if 1 in codes else 3 if 3 in codes else 0

        source = selected_path(args.report if args.command == 'import-cde-report' else args.pdf)
        root = selected_path(getattr(args, 'submission_root', None) or source.parent, directory=True)
        references = tuple(selected_path(p, directory=True) for p in getattr(args, 'reference_root', []))
        roots = (root, *references)
        ReadScope((root,)).authorize(source)
        if args.output:
            validate_new_output(args.output, inputs=(source,), input_roots=roots)
        before = sha256_file(source)
        if args.command == 'import-cde-report':
            from .cde_report import load_report
            result = load_report(source)
            code = 0 if result['parse_state'] == 'PARSED_COUNTS_RECONCILED' else 2
        else:
            request = {'operation': args.command, 'path': str(source)}
            if args.command == 'scan-pdf':
                request.update(roots=[str(p) for p in roots],
                               rulepack=str(selected_path(args.rulepack or _default_rulepack())),
                               node_id=args.node_id, document_role=args.document_role, language=args.language)
            else:
                request.update(page=args.page, query=getattr(args, 'query', None), dpi=getattr(args, 'dpi', 120))
            envelope = run_worker(request, timeout=args.timeout)
            if envelope['worker_status'] != 'OK':
                raise RuntimeError(envelope.get('message', envelope['worker_status']))
            result = envelope['result']
            worker_before = result.get('input_integrity', {}).get('sha256_before')
            if worker_before != before:
                raise RuntimeError('Worker input identity differs from the selected source')
            code = _scan_exit(result) if args.command == 'scan-pdf' else 0
        after = sha256_file(source)
        if after != before:
            raise RuntimeError('Input changed during processing; result not published')
        result['input_integrity'] = {'sha256_before': before, 'sha256_after': after, 'unchanged': True}
        if args.command == 'render-page':
            write_new_bytes(args.output, base64.b64decode(result['png_base64'], validate=True),
                            inputs=(source,), input_roots=roots)
        else:
            text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
            if args.output:
                write_new_text(args.output, text, inputs=(source,), input_roots=roots)
            else:
                _stdout(text)
        return code
    except KeyboardInterrupt:
        print('EZCTD cancelled; no further files processed.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'EZCTD stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
