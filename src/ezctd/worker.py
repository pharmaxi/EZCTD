"""Disposable native-engine worker. The parent owns all output publication."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def execute(request: dict) -> dict:
    operation = request['operation']
    if operation in ('inspect-organize', 'organize-preview', 'organize-stage'):
        from .pdf_organize import inspect_organize, organize_preview, organize_stage
        source, expected = Path(request['path']), request['expected_sha256']
        if operation == 'inspect-organize':
            return inspect_organize(source, expected)
        if operation == 'organize-preview':
            return organize_preview(source, expected, request['order'], request['rotations'],
                                    page=request.get('page', 1), dpi=request.get('dpi', 120),
                                    thumbnail=request.get('thumbnail', False))
        return organize_stage(source, expected, Path(request['stage_path']),
                              request['order'], request['rotations'])
    if operation in ('navigation', 'search-document'):
        from .reader import navigation, search_document
        if operation == 'navigation':
            return navigation(Path(request['path']), request['expected_sha256'])
        return search_document(Path(request['path']), request['expected_sha256'], request['query'],
                               start_page=request.get('start_page', 1),
                               page_limit=request.get('page_limit', 200))
    if operation in ('inspect-copy', 'linearize-stage'):
        from .pdf_copy import inspect_copy, linearize_stage
        if operation == 'inspect-copy':
            return inspect_copy(Path(request['path']), request['expected_sha256'])
        return linearize_stage(Path(request['path']), request['expected_sha256'], Path(request['stage_path']))
    if operation in ('inspect-page', 'render-page', 'view-page', 'thumbnail'):
        from .page_tools import page_operation
        return page_operation(Path(request['path']), page_number=request.get('page', 1),
                              query=request.get('query'), render=operation in ('render-page', 'view-page', 'thumbnail'),
                              include_text=operation == 'view-page',
                              dpi=36 if operation == 'thumbnail' else request.get('dpi', 120),
                              max_pixels=180_000 if operation == 'thumbnail' else 16_000_000)
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
