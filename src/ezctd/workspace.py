"""Single-user local workspace, frozen file identities and explicit job state.

All business context is user-supplied. Path similarity never establishes report
identity or regulatory applicability. No native PDF engine is imported here.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import threading
import time
import uuid
from typing import Any

from .batch import discover_pdfs
from .cde_report import parse_report
from .copy_service import inspect_linearization, linearize_copy
from .process_runner import run_worker
from .read_scope import ReadScope, selected_path
from .safe_io import sha256_file, validate_new_output, write_new_text


@dataclass
class Document:
    id: str
    path: Path
    relative: str
    size: int
    sha256: str | None = None
    context: dict = field(default_factory=dict)
    scan: dict | None = None


class Workspace:
    def __init__(self, root: Path, output: Path, rulepack: Path):
        self.root = selected_path(root, directory=True)
        self.scope = ReadScope((self.root,))
        self.rulepack = selected_path(rulepack)
        self.output = output.absolute()
        # Probe is validation only. Nothing is written until roots are separated.
        validate_new_output(self.output / ('.boundary-' + uuid.uuid4().hex),
                            inputs=(self.rulepack,), input_roots=(self.root,))
        if self.root.is_relative_to(self.output):
            raise ValueError('Workspace must be separate from input, not an ancestor of it')
        self.output.mkdir(parents=True, exist_ok=True)
        self.output = selected_path(self.output, directory=True)
        files, self.notices = discover_pdfs(self.root)
        self.docs = {str(index): Document(str(index), path, path.relative_to(self.root).as_posix(),
                                         path.stat().st_size) for index, path in enumerate(files, 1)}
        self.jobs: dict[str, dict] = {}
        self.events: dict[str, threading.Event] = {}
        self.plans: dict[str, dict] = {}
        self.report: dict | None = None
        self.report_bindings: dict[str, list] = {}
        self.lock = threading.RLock()
        self.native_slots = threading.BoundedSemaphore(2)
        self.closed = False

    def _document(self, ident: str) -> Document:
        if not isinstance(ident, str) or ident not in self.docs:
            raise ValueError('Unknown document ID; filesystem paths are not accepted')
        return self.docs[ident]

    def _freeze(self, doc: Document) -> str:
        self.scope.authorize(doc.path)
        if doc.path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError('Configured 200 MiB per-file processing limit')
        current = sha256_file(doc.path)
        with self.lock:
            if doc.sha256 is not None and current != doc.sha256:
                doc.scan = None
                raise ValueError('SOURCE_CHANGED: close and reopen workspace to accept the new source version')
            doc.sha256 = current
        return current

    def session(self) -> dict:
        with self.lock:
            return {'version': '0.3.0.dev0', 'root_name': self.root.name, 'output_root': str(self.output),
                    'dataset_completeness': 'PARTIAL_CRO', 'official_compliance': 'NOT_ESTABLISHED',
                    'files': [{'id': d.id, 'relative_path': d.relative, 'size': d.size,
                               'sha256': d.sha256, 'context': d.context,
                               'report_count': len(self.report_bindings.get(d.id, [])),
                               'scanned': d.scan is not None} for d in self.docs.values()],
                    'notices': self.notices, 'report': None if self.report is None else
                    {'metadata': self.report['metadata_as_reported'], 'parse_state': self.report['parse_state'],
                     'sha256': self.report['source_sha256'], 'bindings': self.report.get('binding_summary')}}

    def _native(self, request: dict, *, timeout=60, cancel_event=None) -> dict:
        with self.native_slots:
            envelope = run_worker(request, timeout=timeout, cancel_event=cancel_event)
        if envelope['worker_status'] != 'OK':
            raise RuntimeError(envelope.get('message', envelope['worker_status']))
        return envelope['result']

    def document_action(self, ident: str, action: str, **params) -> dict:
        doc = self._document(ident)
        expected = self._freeze(doc)
        if action not in ('view-page', 'navigation', 'search-document'):
            raise ValueError('Unsupported reader action')
        request = {'operation': action, 'path': str(doc.path), 'expected_sha256': expected, **params}
        result = self._native(request, timeout=120)
        actual = result.get('source_sha256', result.get('input_sha256'))
        if actual != expected or self._freeze(doc) != expected:
            raise ValueError('Reader result identity mismatch')
        return result

    def details(self, ident: str) -> dict:
        doc = self._document(ident)
        # Never return stale cached scan or old report as a current check.
        self._freeze(doc)
        with self.lock:
            return deepcopy({'scan': doc.scan, 'report_items': self.report_bindings.get(ident, []),
                             'context': doc.context, 'input_sha256': doc.sha256})

    def set_context(self, ident: str, context: dict) -> None:
        doc = self._document(ident)
        if (not isinstance(context, dict) or set(context) - {'node_id', 'document_role', 'language'}
                or any(not isinstance(v, str) or len(v) > 100 for v in context.values())):
            raise ValueError('Invalid explicitly supplied document context')
        with self.lock:
            if any(job['status'] in ('RUNNING', 'QUEUED', 'FINALIZING') for job in self.jobs.values()):
                raise ValueError('Wait for or cancel the active task before changing context')
            doc.context = dict(context)
            doc.scan = None
            self.plans.clear()

    @staticmethod
    def _report_path(raw) -> str | None:
        if not isinstance(raw, str) or any(ord(c) < 32 for c in raw):
            return None
        value = raw.replace('\\', '/')
        while value.startswith('./'):
            value = value[2:]
        if not value or value.startswith('/') or ':' in value or '..' in value.split('/'):
            return None
        return value

    def import_report(self, raw: bytes) -> dict:
        report = parse_report(raw)
        candidates = {d.relative: d.id for d in self.docs.values()}
        bindings: dict[str, list] = {}
        unmatched = []
        for rule in report['rules']:
            for item in rule['items']:
                path = self._report_path(item.get('path_as_reported'))
                observation = {**item, 'rule_id': rule['rule_id'],
                               'report_icon_status': rule['report_icon_status'],
                               'requirement_as_reported': rule['requirement_as_reported'],
                               'binding_status': 'EXACT_RELATIVE_PATH_CANDIDATE_ONLY',
                               'historical_pdf_byte_identity': 'NOT_ESTABLISHED'}
                if path in candidates:
                    bindings.setdefault(candidates[path], []).append(observation)
                else:
                    unmatched.append({'path_as_reported': item.get('path_as_reported'),
                                      'rule_id': rule['rule_id'], 'state': 'NOT_PROVIDED_OR_UNMAPPED'})
        report['binding_summary'] = {'matched_documents': len(bindings),
                                     'matched_observations': sum(map(len, bindings.values())),
                                     'unmatched_observations': len(unmatched),
                                     'historical_pdf_byte_identity': 'NOT_ESTABLISHED'}
        # Retain imported observations without executing or trusting any HTML.
        with self.lock:
            self.report, self.report_bindings = report, bindings
        return {'parse_state': report['parse_state'], 'binding_summary': report['binding_summary'],
                'unmatched': unmatched, 'metadata': report['metadata_as_reported']}

    def start(self, kind: str, ids=None, *, plan_id=None, confirmed=False) -> str:
        if kind not in ('scan', 'plan', 'apply'):
            raise ValueError('Unknown task')
        with self.lock:
            if self.closed or len(self.jobs) >= 100:
                raise ValueError('Workspace is closed or session task limit reached')
            if any(j['status'] in ('RUNNING', 'QUEUED', 'FINALIZING') for j in self.jobs.values()):
                raise ValueError('A batch task is already active; finish or cancel it first')
            if kind == 'apply':
                if confirmed is not True or plan_id not in self.plans or self.plans[plan_id]['used']:
                    raise ValueError('An unused completed plan and explicit confirmation are required')
                entries = deepcopy(self.plans[plan_id]['entries'])
                self.plans[plan_id]['used'] = True
                ids = [entry['id'] for entry in entries if entry.get('eligibility') == 'ELIGIBLE']
                if not ids:
                    raise ValueError('No eligible changes in this plan')
            else:
                entries = None
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 10000
                    or len(ids) != len(set(ids))):
                raise ValueError('Choose unique document IDs')
            for ident in ids:
                self._document(ident)
            ident = uuid.uuid4().hex
            self.events[ident] = threading.Event()
            self.jobs[ident] = {'id': ident, 'kind': kind, 'status': 'QUEUED', 'done': 0,
                                'total': len(ids), 'current': '', 'results': [],
                                'output_relative_root': f'copies/{ident}' if kind == 'apply' else None,
                                'created_unix': time.time(), 'official_compliance': 'NOT_ESTABLISHED'}
            threading.Thread(target=self._run, args=(ident, ids, entries), daemon=True).start()
            return ident

    def _run(self, job_id: str, ids: list[str], plan_entries: list | None) -> None:
        event = self.events[job_id]
        with self.lock:
            job = self.jobs[job_id]
            job['status'] = 'RUNNING'
        plan_by_id = {row['id']: row for row in plan_entries or []}
        try:
            for ident in ids:
                if event.is_set():
                    break
                doc = self._document(ident)
                with self.lock:
                    job['current'] = doc.relative
                row = {'id': ident, 'relative_path': doc.relative}
                try:
                    expected = self._freeze(doc)
                    if job['kind'] == 'scan':
                        result = self._native({'operation': 'scan-pdf', 'path': str(doc.path),
                                               'roots': [str(self.root)], 'rulepack': str(self.rulepack),
                                               **doc.context}, cancel_event=event)
                        if result.get('input_integrity', {}).get('sha256_before') != expected:
                            raise ValueError('Scan identity mismatch')
                        self._freeze(doc)
                        with self.lock:
                            doc.scan = result
                        row.update(status='SCANNED', result=result)
                    elif job['kind'] == 'plan':
                        with self.native_slots:
                            result = inspect_linearization(doc.path, roots=(self.root,), expected=expected,
                                                          cancel_event=event)
                        row.update(status='PLANNED', **result)
                    else:
                        if expected != plan_by_id[ident]['source_sha256']:
                            raise ValueError('Plan input changed; no rewrite performed')
                        output = self.output / 'copies' / job_id / doc.relative
                        with self.native_slots:
                            result = linearize_copy(doc.path, output, roots=(self.root,), expected=expected,
                                                    cancel_event=event)
                        row.update(status='VERIFIED_COPY', output_relative=output.relative_to(self.output).as_posix(),
                                   proof=result)
                except Exception as exc:
                    row.update(status='CANCELLED' if event.is_set() else 'ERROR',
                               message=f'{type(exc).__name__}: {exc}')
                with self.lock:
                    job['results'].append(row)
                    job['done'] += 1
            integrity = []
            for ident in ids:
                doc = self._document(ident)
                if doc.sha256 is None:
                    integrity.append({'id': ident, 'state': 'IDENTITY_NOT_ESTABLISHED'})
                    continue
                try:
                    observed = sha256_file(self.scope.authorize(doc.path))
                except (OSError, ValueError):
                    observed = None
                integrity.append({'id': ident, 'sha256_expected': doc.sha256,
                                  'sha256_at_completion': observed, 'unchanged': observed == doc.sha256})
            with self.lock:
                failed = any(r['status'] == 'ERROR' for r in job['results']) or any(
                    row.get('unchanged') is False for row in integrity)
                final_status = 'CANCELLED' if event.is_set() else 'COMPLETED_WITH_ERRORS' if failed else 'COMPLETED'
                job['status'] = 'FINALIZING'
                job['current'] = ''
                job['remaining'] = job['total'] - job['done']
                job['input_integrity'] = integrity
                snapshot = deepcopy(job)
                snapshot['status'] = final_status
            write_new_text(self.output / 'jobs' / f'{job_id}.json',
                           json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', input_roots=(self.root,))
            with self.lock:
                job['status'] = final_status
                if job['kind'] == 'plan' and not event.is_set() and not failed:
                    self.plans[job_id] = {'used': False, 'entries': deepcopy(job['results'])}
        except Exception as exc:
            with self.lock:
                job['status'] = 'ERROR'
                job['message'] = f'{type(exc).__name__}: {exc}'

    def job(self, ident: str, *, include_results: bool = True) -> dict:
        with self.lock:
            if not isinstance(ident, str) or ident not in self.jobs:
                raise ValueError('Unknown session job')
            job = self.jobs[ident]
            return deepcopy(job if include_results else {k: v for k, v in job.items() if k != 'results'})

    def cancel(self, ident: str) -> None:
        with self.lock:
            if ident not in self.events:
                raise ValueError('Unknown session job')
            self.events[ident].set()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            for event in self.events.values():
                event.set()
