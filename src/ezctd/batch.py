"""Partial CRO directory scanning; XML backbones are never prerequisites.

No directory links are followed. Each PDF uses a disposable process. Discovery,
worker failure, incomplete rule coverage and changed inputs remain explicit.
"""
from __future__ import annotations

from collections import Counter
import html
import os
from pathlib import Path
import stat
from typing import Any

from .process_runner import run_worker
from .read_scope import ReadScope, selected_path
from .safe_io import sha256_file

MAX_FILES = 10000
MAX_INPUT_BYTES = 200 * 1024 * 1024


def discover_pdfs(root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    root = selected_path(root, directory=True)
    files: list[Path] = []
    notices: list[dict[str, str]] = []
    todo = [root]
    scope = ReadScope((root,))
    while todo:
        directory = todo.pop()
        # Recheck each directory before enumeration; do not resolve away links.
        selected_path(directory, directory=True)
        try:
            with os.scandir(directory) as entries:
                rows = sorted(entries, key=lambda e: e.name)
        except OSError as exc:
            notices.append({'path': directory.relative_to(root).as_posix(),
                            'status': 'DIRECTORY_UNREADABLE', 'reason': type(exc).__name__})
            continue
        for entry in rows:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    notices.append({'path': relative, 'status': 'LINK_NOT_FOLLOWED'})
                elif stat.S_ISDIR(info.st_mode):
                    todo.append(path)
                elif stat.S_ISREG(info.st_mode) and path.suffix.lower() == '.pdf':
                    scope.authorize(path)
                    files.append(path)
                    if len(files) > MAX_FILES:
                        raise ValueError('Directory exceeds the configured 10000 PDF limit')
                else:
                    notices.append({'path': relative, 'status': 'NON_PDF_NOT_SCANNED'})
            except OSError as exc:
                notices.append({'path': relative, 'status': 'ENTRY_UNREADABLE', 'reason': type(exc).__name__})
    return sorted(files, key=lambda p: p.relative_to(root).as_posix()), notices


def _not_run(reason: str) -> list[dict[str, str]]:
    return [{'rule_id': f'6.{n}', 'status': 'NOT_RUN', 'reason': reason,
             'official_calibration': 'NOT_ESTABLISHED'} for n in range(1, 27)]


def scan_directory(root: Path, *, rulepack: Path, contexts: dict[str, dict[str, str]] | None = None,
                   reference_roots: tuple[Path, ...] = (), timeout: float = 60) -> dict[str, Any]:
    root = selected_path(root, directory=True)
    rulepack = selected_path(rulepack)
    scope = ReadScope((root, *reference_roots))
    files, notices = discover_pdfs(root)
    contexts = contexts or {}
    known = {p.relative_to(root).as_posix() for p in files}
    for key, value in contexts.items():
        if key not in known or not isinstance(value, dict):
            raise ValueError('Context map must use exact discovered relative PDF paths')
        if set(value) - {'node_id', 'document_role', 'language'} or any(not isinstance(v, str) for v in value.values()):
            raise ValueError('Unsupported context map field or non-text value')
    # Build identities before starting any worker, and recheck at batch end.
    before: dict[str, str] = {}
    identity_errors: dict[str, str] = {}
    for path in files:
        name = path.relative_to(root).as_posix()
        try:
            scope.authorize(path)
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise ValueError('Configured 200 MiB processing limit; not a regulatory conclusion')
            before[name] = sha256_file(path)
        except (OSError, ValueError) as exc:
            identity_errors[name] = f'{type(exc).__name__}: {exc}'
    results = []
    for path in files:
        name = path.relative_to(root).as_posix()
        row: dict[str, Any] = {'file': name, 'context': contexts.get(name, {}),
                               'input_sha256': before.get(name), 'findings': [],
                               'compliance_conclusion': 'NOT_ESTABLISHED'}
        try:
            if name in identity_errors:
                raise ValueError(identity_errors[name])
            scope.authorize(path)
            if sha256_file(path) != before[name]:
                raise RuntimeError('Input changed after batch inventory')
            envelope = run_worker({'operation': 'scan-pdf', 'path': str(path),
                                   'roots': [str(p) for p in scope.roots], 'rulepack': str(rulepack),
                                   **contexts.get(name, {})}, timeout=timeout)
            row['worker_status'] = envelope['worker_status']
            if envelope['worker_status'] == 'OK':
                row.update(envelope['result'])
                row['file'] = name
                row['worker_status'] = 'OK'
                if row.get('input_integrity', {}).get('sha256_before') != before[name]:
                    raise RuntimeError('Worker read a different input from the batch inventory')
            else:
                row['message'] = envelope.get('message', envelope['worker_status'])
                row['rule_evaluations'] = _not_run(row['message'])
        except (OSError, ValueError, RuntimeError) as exc:
            row.update(worker_status='INPUT_OR_WORKER_ERROR', message=f'{type(exc).__name__}: {exc}',
                       rule_evaluations=_not_run(str(exc)), findings=[])
        results.append(row)
    changes = []
    for row, path in zip(results, files, strict=True):
        name = row['file']
        try:
            scope.authorize(path)
            after = sha256_file(path) if name in before else None
        except (OSError, ValueError):
            after = None
        unchanged = name in before and before[name] == after
        row['batch_input_integrity'] = {'sha256_before': before.get(name), 'sha256_after': after,
                                        'unchanged': unchanged}
        if name in before and not unchanged:
            changes.append(name)
            row['worker_status'] = 'INPUT_CHANGED_RESULT_INVALID'
            row['rule_evaluations'] = _not_run('Input changed; previous observations are not current')
    return {
        'schema_version': '0.2.1', 'dataset_completeness': 'PARTIAL_CRO',
        'backbone_required': False, 'official_validation_performed': False,
        'compliance_conclusion': 'NOT_ESTABLISHED',
        'scope_note': 'Read authorization is not proof of whole-submission completeness.',
        'input_root': str(root), 'reference_roots': [str(p) for p in scope.roots[1:]],
        'pdf_count': len(files), 'discovery_notices': notices, 'files': results,
        'worker_totals': dict(Counter(r['worker_status'] for r in results)),
        'rule_status_totals': dict(Counter(e['status'] for r in results for e in r['rule_evaluations'])),
        'input_integrity': {'checked': len(before), 'unchanged': len(before) - len(changes),
                            'changed_paths': changes, 'identity_errors': identity_errors},
        'scan_status': 'NO_PDF_INPUT' if not files else 'COMPLETED_WITH_EXPLICIT_LIMITATIONS',
    }


def render_batch_html(result: dict) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    labels = {'PASS': '本地条件满足', 'FAIL': '发现问题', 'NOT_APPLICABLE': '不适用',
              'INDETERMINATE': '无法判定', 'NOT_RUN': '未运行'}
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
             '<title>EZCTD 临床 PDF 批量检查</title>',
             '<style>body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 24px}'
             'table{border-collapse:collapse;width:100%}th,td{border:1px solid;padding:8px;text-align:left}'
             'pre{white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600}'
             'section{margin:24px 0}td{vertical-align:top}</style>',
             '<h1>临床 PDF 批量检查</h1><p>部分临床资料 · 无需完整 eCTD · 不代表官方验证通过</p>',
             f'<p>PDF：{result["pdf_count"]}；输入哈希未变：{result["input_integrity"]["unchanged"]} / '
             f'{result["input_integrity"]["checked"]}。</p>',
             '<p>“本地条件满足”只指该项有限检查。未判定项目不得视为通过；原始官方报告与本次检查分开保存。</p>']
    if result['discovery_notices']:
        parts += ['<details><summary>发现范围与跳过项</summary><pre>', esc(result['discovery_notices']), '</pre></details>']
    for row in result['files']:
        parts += ['<section><h2>', esc(row['file']), '</h2><p>任务状态：', esc(row['worker_status']),
                  '</p><p>SHA-256：', esc(row.get('input_sha256')), '</p>']
        if row.get('message'):
            parts += ['<p>', esc(row['message']), '</p>']
        for finding in row.get('findings', []):
            parts += ['<details><summary>', esc(finding['rule_id']), ' · ', esc(finding['title']),
                      ' · ', esc(labels.get(finding.get('local_evaluation_status'), '候选问题')),
                      '</summary><p>', esc(finding['message']), '</p><pre>',
                      esc(finding.get('evidence', [])), '</pre></details>']
        parts += ['<details><summary>逐规则执行状态（26 条）</summary><table><tr><th>规则</th><th>状态</th><th>原因</th></tr>']
        for evaluation in row['rule_evaluations']:
            parts += ['<tr><td>', esc(evaluation['rule_id']), '</td><td>',
                      esc(labels[evaluation['status']]), '</td><td>', esc(evaluation['reason']), '</td></tr>']
        parts += ['</table></details></section>']
    return ''.join(parts) + '</html>'
