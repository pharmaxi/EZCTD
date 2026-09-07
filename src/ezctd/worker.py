"""Disposable native-engine worker. The parent owns all output publication."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def execute(request: dict) -> dict:
    operation = request['operation']
    if operation in ('inspect-page', 'render-page'):
        from .page_tools import page_operation
        return page_operation(Path(request['path']), page_number=request.get('page', 1),
                              query=request.get('query'), render=operation == 'render-page',
                              dpi=request.get('dpi', 120))
    if operation == 'scan-pdf':
        from .catalog import RuleCatalog
        from .models import PdfContext
        from .pdf_observer import ExperimentalPdfObserver
        from .read_scope import ReadScope
        from .safe_io import sha256_file
        scope = ReadScope(tuple(Path(p) for p in request['roots']))
        source = scope.authorize(Path(request['path']))
        if source.stat().st_size > 200 * 1024 * 1024:
            raise ValueError('PDF exceeds the configured 200 MiB input limit')
        before = sha256_file(source)
        context = PdfContext(file_path=source, submission_root=scope.roots[0],
                             node_id=request.get('node_id'),
                             document_role=request.get('document_role'),
                             language=request.get('language'),
                             allowed_read_roots=scope.roots)
        result = ExperimentalPdfObserver(RuleCatalog.from_json(Path(request['rulepack']))).scan(context).to_dict()
        after = sha256_file(source)
        if before != after:
            raise RuntimeError('Input changed during scan; discard the result')
        result['input_integrity'] = {'sha256_before': before, 'sha256_after': after, 'unchanged': True}
        return result
    raise ValueError('Unknown worker operation')


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(65537)
        if len(payload) > 65536:
            raise ValueError('Worker request is too large')
        result = execute(json.loads(payload))
        envelope = {'worker_status': 'OK', 'result': result}
    except Exception as exc:
        envelope = {'worker_status': 'ERROR', 'error_type': type(exc).__name__, 'message': str(exc)}
    sys.stdout.buffer.write((json.dumps(envelope, ensure_ascii=False) + '\n').encode('utf-8'))
    return 0 if envelope['worker_status'] == 'OK' else 2


if __name__ == '__main__':
    raise SystemExit(main())
