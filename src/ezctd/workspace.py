"""Single-user local workspace, frozen file identities and explicit job state.

All business context is user-supplied. Path similarity never establishes report
identity or regulatory applicability. No native PDF engine is imported here.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time
import uuid

import ezctd
from .batch import discover_pdfs
from .cde_report import parse_report
from .copy_service import inspect_linearization, linearize_copy, organize_copy
from .editor import EditorConflict, EditorStore
from .process_runner import run_worker
from .read_cache import ReadCache
from .read_scope import ReadScope, selected_path
from .safe_io import sha256_file, validate_new_output, write_new_text

ACTIVE_JOB_STATES = ('QUEUED', 'RUNNING', 'FINALIZING')
RETRYABLE_ROW_STATES = ('ERROR', 'CANCELLED', 'NOT_STARTED')


@dataclass
class Document:
    id: str
    path: Path
    relative: str
    size: int
    sha256: str | None = None
    context: dict = field(default_factory=dict)
    scan: dict | None = None
    invalidation_generation: int = 0


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
        self.read_cache = ReadCache()
        self.editors = EditorStore()
        self.editor_outputs: dict[str, dict] = {}
        self.editor_threads: dict[str, threading.Thread] = {}
        self.close_event = threading.Event()
        self.output_scope = ReadScope((self.output,))
        self.closed = False

    def _document(self, ident: str) -> Document:
        if not isinstance(ident, str) or ident not in self.docs:
            raise ValueError('Unknown document ID; filesystem paths are not accepted')
        return self.docs[ident]

    def _invalidate_document_locked(self, doc: Document) -> None:
        doc.invalidation_generation += 1
        doc.scan = None
        self.read_cache.invalidate_document(doc.id)
        self.editors.invalidate(doc.id)
        for job_id, job in self.jobs.items():
            if (job['kind'] == 'organize' and job['status'] in ACTIVE_JOB_STATES
                    and doc.id in job['requested_ids']):
                job['cancellation_reason'] = 'SOURCE_CHANGED'
                self.events[job_id].set()
        for plan_id, plan in self.plans.items():
            retained = [entry for entry in plan['entries'] if entry['id'] != doc.id]
            if len(retained) != len(plan['entries']):
                plan['entries'] = retained
                invalidated = self.jobs[plan_id].setdefault('invalidated_plan_ids', [])
                if doc.id not in invalidated:
                    invalidated.append(doc.id)

    def _freeze(self, doc: Document) -> str:
        try:
            self.scope.authorize(doc.path)
            if doc.path.stat().st_size > 200 * 1024 * 1024:
                raise ValueError('Configured 200 MiB per-file processing limit')
            current = sha256_file(doc.path)
        except (OSError, ValueError):
            with self.lock:
                self._invalidate_document_locked(doc)
            raise
        with self.lock:
            if doc.sha256 is not None and current != doc.sha256:
                self._invalidate_document_locked(doc)
                raise ValueError('SOURCE_CHANGED: close and reopen workspace to accept the new source version')
            doc.sha256 = current
        return current

    def session(self) -> dict:
        with self.lock:
            return {'version': ezctd.__version__, 'root_name': self.root.name, 'output_root': str(self.output),
                    'dataset_completeness': 'PARTIAL_CRO', 'official_compliance': 'NOT_ESTABLISHED',
                    'files': [{'id': d.id, 'relative_path': d.relative, 'size': d.size,
                               'sha256': d.sha256, 'context': d.context,
                               'report_count': len(self.report_bindings.get(d.id, [])),
                               'scanned': d.scan is not None,
                               'scan_summary': None if d.scan is None else {
                                   status: sum(row.get('status') == status
                                               for row in d.scan.get('rule_evaluations', []))
                                   for status in ('FAIL', 'INDETERMINATE', 'NOT_RUN',
                                                  'PASS', 'NOT_APPLICABLE')}}
                              for d in self.docs.values()],
                    'notices': self.notices, 'report': None if self.report is None else
                    {'metadata': self.report['metadata_as_reported'], 'parse_state': self.report['parse_state'],
                     'sha256': self.report['source_sha256'], 'bindings': self.report.get('binding_summary')},
                    **self.job_history()}

    @contextmanager
    def _native_slot(self, cancel_event=None):
        # A cancelled batch need not wait behind two reader workers to observe
        # cancellation. This semaphore bounds native processes, not OS memory.
        while not self.native_slots.acquire(timeout=0.1):
            if self.closed:
                raise RuntimeError('Workspace is closed')
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Cancelled while waiting for a native worker')
        try:
            if self.closed:
                raise RuntimeError('Workspace is closed')
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Cancelled before native worker launch')
            yield
        finally:
            self.native_slots.release()

    def _native(self, request: dict, *, timeout=60, cancel_event=None) -> dict:
        with self._native_slot(cancel_event):
            envelope = run_worker(request, timeout=timeout, cancel_event=cancel_event)
        if envelope['worker_status'] != 'OK':
            raise RuntimeError(envelope.get('message', envelope['worker_status']))
        return envelope['result']

    def document_action(self, ident: str, action: str, **params) -> dict:
        doc = self._document(ident)
        if action not in ('view-page', 'navigation', 'search-document', 'thumbnail'):
            raise ValueError('Unsupported reader action')
        if set(params) & {'operation', 'path', 'expected_sha256'}:
            raise ValueError('Reader identity and scope cannot be supplied as parameters')
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
        # Never use size/mtime as a substitute for current byte identity, even
        # for a cached PNG. Authorization also runs on every cache hit.
        expected = self._freeze(doc)
        key = (ident, expected, action, json.dumps(params, sort_keys=True, allow_nan=False,
                                                  separators=(',', ':')))
        result = self.read_cache.get(key)
        cache_hit = result is not None
        if not cache_hit:
            request = {'operation': action, 'path': str(doc.path), 'expected_sha256': expected, **params}
            result = self._native(request, timeout=120)
        # Cache decoding can take time, just like native work. Both paths must
        # recheck source identity and closure at the return boundary. Always
        # run _freeze before comparing envelope hashes, so a mismatched worker
        # result cannot short-circuit known-source invalidation.
        current = self._freeze(doc)
        actual = result.get('source_sha256', result.get('input_sha256'))
        if actual != expected or current != expected:
            raise ValueError('Reader result identity mismatch')
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            if not cache_hit:
                self.read_cache.put(key, result)
        return result

    def details(self, ident: str) -> dict:
        doc = self._document(ident)
        # Never return stale cached scan or old report as a current check.
        self._freeze(doc)
        with self.lock:
            return deepcopy({'scan': doc.scan, 'report_items': self.report_bindings.get(ident, []),
                             'context': doc.context, 'input_sha256': doc.sha256})

    def editor_open(self, ident: str) -> dict:
        doc = self._document(ident)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            existing = self.editors.by_document.get(ident)
            generation = doc.invalidation_generation
            if generation:
                raise ValueError('SOURCE_CHANGED: close and reopen workspace to accept the new source version')
        if existing is not None:
            return self.editor_state(existing)
        expected = self._freeze(doc)
        inspected = self._native({'operation': 'inspect-organize', 'path': str(doc.path),
                                  'expected_sha256': expected}, timeout=120, cancel_event=self.close_event)
        current = self._freeze(doc)
        if inspected.get('source_sha256') != expected or current != expected:
            raise ValueError('Editor inspection identity mismatch')
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            if doc.invalidation_generation != generation:
                raise ValueError('SOURCE_CHANGED: source was invalidated during editor inspection')
            draft = self.editors.open(ident, inspected)
            if draft.invalidated:
                raise ValueError('SOURCE_CHANGED: close and reopen workspace')
            return draft.state()

    def _editor_snapshot(self, draft_id: str, revision=None, *, exact_revision=False) -> tuple[Document, dict]:
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            draft = self.editors.get(draft_id, revision) if exact_revision else self.editors.get(draft_id)
            doc = self._document(draft.document_id)
        expected = self._freeze(doc)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            draft = self.editors.get(draft_id, revision) if exact_revision else self.editors.get(draft_id)
            if draft.invalidated or draft.source_sha256 != expected:
                raise ValueError('SOURCE_CHANGED: close and reopen workspace to accept the new source version')
            return doc, draft.state()

    def editor_state(self, draft_id: str) -> dict:
        return self._editor_snapshot(draft_id)[1]

    def editor_edit(self, draft_id: str, revision: int, command: dict) -> dict:
        self._editor_snapshot(draft_id, revision, exact_revision=True)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            return self.editors.edit(draft_id, revision, command)

    def editor_history(self, draft_id: str, revision: int, *, redo=False) -> dict:
        self._editor_snapshot(draft_id, revision, exact_revision=True)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            return self.editors.move_history(draft_id, revision, redo=redo)

    @staticmethod
    def _page_parameters(page, dpi, thumbnail) -> None:
        if (type(page) is not int or page < 1 or type(dpi) is not int or not 36 <= dpi <= 300
                or type(thumbnail) is not bool):
            raise ValueError('Invalid physical page, DPI or thumbnail flag')

    def _finish_editor_read(self, doc: Document, state: dict, result: dict, *, cache_key=None) -> dict:
        expected = self._freeze(doc)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            draft = self.editors.get(state['draft_id'], state['revision'])
            if draft.invalidated or expected != state['source_sha256']:
                raise ValueError('SOURCE_CHANGED: source changed during edit preview')
            if result.get('source_sha256') != expected:
                raise ValueError('Editor preview identity mismatch')
            result.update(draft_id=state['draft_id'], revision=state['revision'])
            if cache_key is not None:
                self.read_cache.put(cache_key, result)
            return result

    def editor_page(self, draft_id: str, revision: int, *, page: int = 1,
                    dpi: int = 120, thumbnail: bool = False) -> dict:
        self._page_parameters(page, dpi, thumbnail)
        doc, state = self._editor_snapshot(draft_id, revision, exact_revision=True)
        if state['eligibility'] != 'ELIGIBLE':
            raise ValueError('This PDF is blocked for page organization')
        if page > state['page_count']:
            raise ValueError('Physical page is outside this document')
        parameters = {'order': state['order'], 'rotations': state['rotations'],
                      'page': page, 'dpi': 36 if thumbnail else dpi, 'thumbnail': thumbnail}
        key = (doc.id, state['source_sha256'], 'organize-preview',
               json.dumps([draft_id, revision, parameters], sort_keys=True, separators=(',', ':')))
        result = self.read_cache.get(key)
        cache_hit = result is not None
        if not cache_hit:
            result = self._native({'operation': 'organize-preview', 'path': str(doc.path),
                                   'expected_sha256': state['source_sha256'], **parameters},
                                  timeout=120, cancel_event=self.close_event)
        return self._finish_editor_read(doc, state, result, cache_key=None if cache_hit else key)

    def editor_navigation(self, draft_id: str, revision: int) -> dict:
        doc, state = self._editor_snapshot(draft_id, revision, exact_revision=True)
        result = self.document_action(doc.id, 'navigation')
        positions = {source: position for position, source in enumerate(state['order'], 1)}
        for bookmark in result['bookmarks']:
            source_page = bookmark.get('physical_page')
            bookmark['source_page'] = source_page
            bookmark['physical_page'] = positions.get(source_page)
        by_source = {row['physical_page']: row for row in result['page_labels']}
        result['page_labels'] = [{**by_source[source_page], 'source_page': source_page,
                                  'physical_page': position}
                                 for position, source_page in enumerate(state['order'], 1)
                                 if source_page in by_source]
        result.update(preview_only=True, verification_status='DRAFT_TARGET_MAPPING_NOT_SAVED_OUTPUT')
        return self._finish_editor_read(doc, state, result)

    def editor_save(self, draft_id: str, revision: int, *, confirmed=False, retry=False) -> str:
        if confirmed is not True or type(retry) is not bool:
            raise ValueError('Saving an edited copy requires explicit confirmation')
        doc, state = self._editor_snapshot(draft_id, revision, exact_revision=True)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            draft = self.editors.get(draft_id, revision)
            previous_id = draft.saves.get(revision)
            if previous_id is not None:
                previous = self.jobs[previous_id]
                if not retry or previous['status'] in ACTIVE_JOB_STATES or previous.get('published_copy'):
                    return previous_id
            elif retry:
                raise ValueError('There is no save of this revision to retry')
            self.editors.require_editable(draft)
            if not state['has_changes']:
                raise ValueError('No page organization changes to save')
            if not state['dirty'] and previous_id is None:
                raise ValueError('This edit state is already saved')
            if len(self.jobs) >= 100:
                raise ValueError('Session task limit reached')
            if any(job['status'] in ACTIVE_JOB_STATES for job in self.jobs.values()):
                raise EditorConflict('DRAFT_BUSY', 'A batch task is already active; finish or cancel it first')
            job_id = uuid.uuid4().hex
            self.events[job_id] = threading.Event()
            self.jobs[job_id] = {'id': job_id, 'kind': 'organize', 'status': 'QUEUED',
                                 'done': 0, 'total': 1, 'remaining': 1, 'current': '', 'results': [],
                                 'requested_ids': [doc.id], 'retry_of': previous_id, 'source_plan_id': None,
                                 'draft_id': draft_id, 'revision': revision,
                                 'output_relative_root': f'copies/{job_id}',
                                 'created_unix': time.time(), 'official_compliance': 'NOT_ESTABLISHED'}
            old_job_id, old_save_revision = draft.save_job_id, draft.save_revision
            draft.saving, draft.save_job_id, draft.save_revision = True, job_id, revision
            draft.saves[revision] = job_id
            thread = threading.Thread(target=self._run_editor_save, args=(job_id, doc, state), daemon=True)
            self.editor_threads[job_id] = thread
            try:
                thread.start()
            except Exception:
                self.jobs.pop(job_id)
                self.events.pop(job_id)
                self.editor_threads.pop(job_id)
                draft.saving, draft.save_job_id, draft.save_revision = False, old_job_id, old_save_revision
                if previous_id is None:
                    draft.saves.pop(revision)
                else:
                    draft.saves[revision] = previous_id
                raise
            return job_id

    def _run_editor_save(self, job_id: str, doc: Document, state: dict) -> None:
        event = self.events[job_id]
        output = self.output / 'copies' / job_id / doc.relative
        row = {'id': doc.id, 'relative_path': doc.relative, 'saved_revision': state['revision']}
        with self.lock:
            job = self.jobs[job_id]
            job.update(status='RUNNING', current=doc.relative, phase='VERIFYING_EDITED_COPY')
        published = False
        try:
            try:
                expected = self._freeze(doc)
                if expected != state['source_sha256']:
                    raise ValueError('SOURCE_CHANGED: draft input changed; no rewrite performed')
                with self.lock:
                    if self.editors.get(state['draft_id']).invalidated:
                        raise ValueError('SOURCE_CHANGED: draft was invalidated; no rewrite performed')
                with self._native_slot(event):
                    proof = organize_copy(doc.path, output, roots=(self.root,), expected=expected,
                                          order=state['order'], rotations=state['rotations'],
                                          cancel_event=event)
                published = True
                row.update(status='VERIFIED_COPY', output_relative=output.relative_to(self.output).as_posix(),
                           output_basename=output.name, page_count=proof['page_count'], proof=proof)
                with self.lock:
                    self.editor_outputs[job_id] = {'path': output, 'sha256': proof['output_sha256'],
                                                    'source_document_id': doc.id,
                                                    'saved_revision': state['revision'],
                                                    'page_mapping': deepcopy(proof['page_mapping']),
                                                    'invalidated': False}
                    job['published_copy'] = True
            except Exception as exc:
                row.update(status='CANCELLED' if event.is_set() else 'ERROR',
                           message=f'{type(exc).__name__}: {exc}')
            try:
                observed = sha256_file(self.scope.authorize(doc.path))
            except (ValueError, OSError):
                observed = None
            integrity = {'id': doc.id, 'sha256_expected': state['source_sha256'],
                         'sha256_at_completion': observed, 'unchanged': observed == state['source_sha256']}
            with self.lock:
                if not integrity['unchanged']:
                    self._invalidate_document_locked(doc)
                job.update(status='FINALIZING', phase='SAVING_JOB_RECORD', current='', done=1, remaining=0,
                           results=[row], input_integrity=[integrity])
                failed = row['status'] == 'ERROR' or not integrity['unchanged']
                final_status = ('CANCELLED' if event.is_set() else
                                'COMPLETED_WITH_ERRORS' if failed else 'COMPLETED')
                snapshot = deepcopy(job)
                snapshot.update(status=final_status, counts=self._counts_locked(job))
            write_new_text(self.output / 'jobs' / f'{job_id}.json',
                           json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', input_roots=(self.root,))
            with self.lock:
                draft = self.editors.get(state['draft_id'])
                draft.saving = False
                if published:
                    draft.saved_snapshot = tuple(state['order']), tuple(state['rotations'])
                    draft.last_saved_revision = state['revision']
                job['status'] = final_status
        except Exception as exc:
            with self.lock:
                job.update(status='ERROR', message=f'{type(exc).__name__}: {exc}', current='')
                if not job['results']:
                    job.update(results=[row], done=1, remaining=0)
        finally:
            with self.lock:
                draft = self.editors.get(state['draft_id'])
                # A new save may start after the terminal job status above.
                # This older thread must not unlock or relabel that new save.
                if draft.save_job_id == job_id:
                    draft.saving = False
                    if published:
                        draft.saved_snapshot = tuple(state['order']), tuple(state['rotations'])
                        draft.last_saved_revision = state['revision']

    def editor_output(self, job_id: str, action: str, *, page=1, dpi=120, thumbnail=False) -> dict:
        if action not in ('page', 'navigation'):
            raise ValueError('Unsupported saved-output reader action')
        self._page_parameters(page, dpi, thumbnail)
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            if not isinstance(job_id, str) or job_id not in self.editor_outputs:
                raise ValueError('Unknown session editor output; filesystem paths are not accepted')
            registration = self.editor_outputs[job_id]
            registered = deepcopy(registration)
            if registered['invalidated']:
                raise ValueError('OUTPUT_CHANGED: the saved output no longer matches its proof')
            if self.jobs[job_id]['status'] in ACTIVE_JOB_STATES:
                raise EditorConflict('DRAFT_BUSY', 'Wait for saving to finish before opening the output')
        path = registered['path']
        expected = registered['sha256']

        def verify_output():
            try:
                current = sha256_file(self.output_scope.authorize(path))
            except (ValueError, OSError):
                current = None
            if current != expected:
                with self.lock:
                    self.editor_outputs[job_id]['invalidated'] = True
                raise ValueError('OUTPUT_CHANGED: the saved output no longer matches its proof')

        verify_output()
        parameters = {} if action == 'navigation' else ({'page': page} if thumbnail else {'page': page, 'dpi': dpi})
        operation = 'navigation' if action == 'navigation' else 'thumbnail' if thumbnail else 'view-page'
        try:
            result = self._native({'operation': operation, 'path': str(path),
                                   'expected_sha256': expected, **parameters},
                                  timeout=120, cancel_event=self.close_event)
        except (RuntimeError, ValueError) as exc:
            if any(signal in str(exc).lower() for signal in
                   ('input changed', 'source changed', 'identity mismatch')):
                with self.lock:
                    if self.editor_outputs.get(job_id) is registration:
                        registration['invalidated'] = True
                raise ValueError('OUTPUT_CHANGED: native reader observed changed output bytes') from exc
            raise
        verify_output()
        with self.lock:
            if self.closed:
                raise ValueError('Workspace is closed')
            current = self.editor_outputs.get(job_id)
            if (current is not registration or current.get('invalidated')
                    or current.get('path') != path or current.get('sha256') != expected):
                raise ValueError('OUTPUT_CHANGED: saved output was invalidated while being read')
            if result.get('source_sha256', result.get('input_sha256')) != expected:
                current['invalidated'] = True
                raise ValueError('OUTPUT_CHANGED: output reader identity does not match the saved proof')
            result.update(job_id=job_id, saved_revision=registered['saved_revision'],
                          source_document_id=registered['source_document_id'], read_only=True,
                          output_sha256=expected, output_relative=path.relative_to(self.output).as_posix())
            if action == 'navigation':
                result['page_mapping'] = registered['page_mapping']
            return result

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
        with self.lock:
            return self._start_locked(kind, ids, plan_id=plan_id, confirmed=confirmed)

    def _start_locked(self, kind: str, ids=None, *, plan_id=None, confirmed=False,
                      retry_of: str | None = None) -> str:
        if kind not in ('scan', 'plan', 'apply'):
            raise ValueError('Unknown task')
        if self.closed or len(self.jobs) >= 100:
            raise ValueError('Workspace is closed or session task limit reached')
        if any(j['status'] in ACTIVE_JOB_STATES for j in self.jobs.values()):
            raise ValueError('A batch task is already active; finish or cancel it first')
        if kind == 'apply':
            if (confirmed is not True or not isinstance(plan_id, str)
                    or plan_id not in self.plans or self.plans[plan_id]['used']):
                raise ValueError('An unused completed plan and explicit confirmation are required')
            entries = deepcopy(self.plans[plan_id]['entries'])
            ids = [entry['id'] for entry in entries if entry.get('eligibility') == 'ELIGIBLE']
            if not ids:
                raise ValueError('No eligible changes in this plan')
        else:
            entries = None
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 10000
                or any(not isinstance(ident, str) for ident in ids)
                or len(ids) != len(set(ids))):
            raise ValueError('Choose unique document IDs')
        for ident in ids:
            self._document(ident)
        ids = list(ids)
        ident = uuid.uuid4().hex
        self.events[ident] = threading.Event()
        self.jobs[ident] = {'id': ident, 'kind': kind, 'status': 'QUEUED', 'done': 0,
                            'total': len(ids), 'remaining': len(ids), 'current': '', 'results': [],
                            'requested_ids': ids, 'retry_of': retry_of, 'source_plan_id': plan_id,
                            'output_relative_root': f'copies/{ident}' if kind == 'apply' else None,
                            'created_unix': time.time(), 'official_compliance': 'NOT_ESTABLISHED'}
        # Consume only after every argument has been validated and a valid job
        # created. A failed/no-eligible attempt must not burn the user's plan.
        if kind == 'apply':
            self.plans[plan_id]['used'] = True
        try:
            threading.Thread(target=self._run, args=(ident, ids, entries), daemon=True).start()
        except Exception:
            self.jobs.pop(ident)
            self.events.pop(ident)
            if kind == 'apply':
                self.plans[plan_id]['used'] = False
            raise
        return ident

    @staticmethod
    def _retry_ids(job: dict) -> list[str]:
        rows = {row['id']: row for row in job['results']}
        return [ident for ident in job['requested_ids'] if ident not in rows
                or rows[ident]['status'] in RETRYABLE_ROW_STATES]

    def retry(self, ident: str) -> str:
        with self.lock:
            if not isinstance(ident, str) or ident not in self.jobs:
                raise ValueError('Unknown session job')
            previous = self.jobs[ident]
            if previous['kind'] == 'organize':
                raise ValueError('Retry a page-edit save from its current draft with explicit confirmation')
            if previous['status'] in ACTIVE_JOB_STATES:
                raise ValueError('Wait for the task to finish before retrying')
            ids = self._retry_ids(previous)
            if not ids:
                raise ValueError('This task has no failed, cancelled or unstarted files to retry')
            # A failed copy never reuses a consumed plan or republishes a
            # successful row. Generate a fresh plan requiring confirmation.
            kind = 'plan' if previous['kind'] == 'apply' else previous['kind']
            return self._start_locked(kind, ids, retry_of=ident)

    def _append_pending_locked(self, job: dict) -> None:
        seen = {row['id'] for row in job['results']}
        for ident in job['requested_ids']:
            if ident not in seen:
                job['results'].append({'id': ident, 'relative_path': self._document(ident).relative,
                                       'status': 'NOT_STARTED',
                                       'message': 'Not started; no successful result is asserted'})
        job['remaining'] = job['total'] - job['done']

    def _run(self, job_id: str, ids: list[str], plan_entries: list | None) -> None:
        event = self.events[job_id]
        with self.lock:
            job = self.jobs[job_id]
            job['status'] = 'RUNNING'
        plan_by_id = {row['id']: row for row in plan_entries or []}
        source_generations: dict[str, int] = {}
        try:
            for ident in ids:
                if event.is_set():
                    break
                doc = self._document(ident)
                with self.lock:
                    job['current'] = doc.relative
                    source_generations[ident] = doc.invalidation_generation
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
                        with self._native_slot(event):
                            result = inspect_linearization(doc.path, roots=(self.root,), expected=expected,
                                                          cancel_event=event)
                        row.update(status='PLANNED', **result)
                    else:
                        if expected != plan_by_id[ident]['source_sha256']:
                            raise ValueError('Plan input changed; no rewrite performed')
                        output = self.output / 'copies' / job_id / doc.relative
                        with self._native_slot(event):
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
                    job['remaining'] = job['total'] - job['done']
            with self.lock:
                job['status'] = 'FINALIZING'
                job['current'] = ''
                job['phase'] = 'VERIFYING_INPUTS'
                self._append_pending_locked(job)
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
                if observed != doc.sha256:
                    with self.lock:
                        self._invalidate_document_locked(doc)
            with self.lock:
                integrity_by_id = {item['id']: item for item in integrity}
                eligible_entries = []
                if job['kind'] == 'plan':
                    for row in job['results']:
                        if row.get('status') != 'PLANNED' or row.get('eligibility') != 'ELIGIBLE':
                            continue
                        checked = integrity_by_id[row['id']]
                        if (checked.get('unchanged') is True
                                and checked.get('sha256_expected') == row.get('source_sha256')
                                and self._document(row['id']).invalidation_generation
                                    == source_generations[row['id']]):
                            eligible_entries.append(deepcopy(row))
                        else:
                            row.update(status='ERROR', eligibility='BLOCKED',
                                       preflight_eligibility='ELIGIBLE',
                                       message='Source changed after preflight; no usable plan for this file')
                            row['blockers'] = [*row.get('blockers', []), 'SOURCE_CHANGED_AT_COMPLETION']
                failed = any(r['status'] == 'ERROR' for r in job['results']) or any(
                    row.get('unchanged') is False for row in integrity)
                final_status = 'CANCELLED' if event.is_set() else 'COMPLETED_WITH_ERRORS' if failed else 'COMPLETED'
                job['input_integrity'] = integrity
                job['plan_eligible_ids'] = [row['id'] for row in eligible_entries]
                # Processing and input checks are complete. Close the cancel
                # window before fixing the immutable record's final status.
                job['phase'] = 'SAVING_JOB_RECORD'
                snapshot = deepcopy(job)
                snapshot['status'] = final_status
                snapshot['counts'] = self._counts_locked(job)
            write_new_text(self.output / 'jobs' / f'{job_id}.json',
                           json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', input_roots=(self.root,))
            with self.lock:
                job['status'] = final_status
                # Publish actionable plans only after their job evidence was
                # saved. Another request can observe source invalidation while
                # the job record is being saved, before this plan exists to prune.
                # Its generation must still match; frozen SHA alone retains
                # the old identity and cannot detect that intervening event.
                usable_entries = []
                for row in eligible_entries:
                    doc = self._document(row['id'])
                    if (doc.invalidation_generation == source_generations[row['id']]
                            and doc.sha256 == row['source_sha256']):
                        usable_entries.append(row)
                    else:
                        invalidated = job.setdefault('invalidated_plan_ids', [])
                        if row['id'] not in invalidated:
                            invalidated.append(row['id'])
                job['plan_eligible_ids'] = [row['id'] for row in usable_entries]
                # The saved JSON remains the immutable preflight snapshot;
                # later invalidations are reflected in current session state.
                if (job['kind'] == 'plan' and not self.closed and not event.is_set()
                        and usable_entries):
                    self.plans[job_id] = {'used': False, 'entries': usable_entries}
        except Exception as exc:
            with self.lock:
                job['status'] = 'ERROR'
                job['message'] = f'{type(exc).__name__}: {exc}'
                job['current'] = ''
                self._append_pending_locked(job)

    @staticmethod
    def _counts_locked(job: dict) -> dict:
        counts = {'succeeded': 0, 'errors': 0, 'cancelled': 0, 'pending': 0,
                  'blocked': 0, 'skipped': 0}
        for row in job['results']:
            status = row['status']
            if status == 'ERROR':
                counts['errors'] += 1
            elif status == 'CANCELLED':
                counts['cancelled'] += 1
            elif status == 'NOT_STARTED':
                counts['pending'] += 1
            elif row.get('eligibility') == 'BLOCKED':
                counts['blocked'] += 1
            elif row.get('eligibility') == 'NO_CHANGE_NEEDED':
                counts['skipped'] += 1
            else:
                counts['succeeded'] += 1
        counts['pending'] += job['total'] - len(job['results'])
        return counts

    def _summary_locked(self, job: dict) -> dict:
        summary = {key: deepcopy(value) for key, value in job.items()
                   if key not in ('results', 'input_integrity')}
        plan = self.plans.get(job['id'])
        terminal = job['status'] not in ACTIVE_JOB_STATES
        retryable = 0 if job['kind'] == 'organize' else len(self._retry_ids(job))
        summary.update(counts=self._counts_locked(job), retryable_count=retryable,
                       can_retry=not self.closed and terminal and retryable > 0,
                       eligible_count=len(plan['entries']) if plan else 0,
                       can_apply=bool(not self.closed and terminal and plan
                                      and not plan['used'] and plan['entries']),
                       history_scope='CURRENT_SERVER_SESSION')
        return summary

    def job_history(self) -> dict:
        with self.lock:
            jobs = [self._summary_locked(job) for job in reversed(list(self.jobs.values()))]
            active = next((job['id'] for job in jobs if job['status'] in ACTIVE_JOB_STATES), None)
            return {'jobs': jobs, 'active_job_id': active,
                    'history_scope': 'CURRENT_SERVER_SESSION'}

    def job(self, ident: str, *, include_results: bool = True) -> dict:
        with self.lock:
            if not isinstance(ident, str) or ident not in self.jobs:
                raise ValueError('Unknown session job')
            job = self.jobs[ident]
            result = self._summary_locked(job)
            if 'input_integrity' in job:
                result['input_integrity'] = deepcopy(job['input_integrity'])
            if include_results:
                result['results'] = deepcopy(job['results'])
            return result

    def cancel(self, ident: str) -> None:
        with self.lock:
            if not isinstance(ident, str) or ident not in self.events:
                raise ValueError('Unknown session job')
            if self.jobs[ident]['status'] not in ACTIVE_JOB_STATES:
                raise ValueError('Task has already finished')
            if self.jobs[ident].get('phase') == 'SAVING_JOB_RECORD':
                raise ValueError('Task processing has finished; its result record is being saved')
            self.events[ident].set()

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.close_event.set()
            self.read_cache.clear()
            for event in self.events.values():
                event.set()
            threads = list(self.editor_threads.values())
        # Page-copy workers observe cancellation and remove incomplete staging.
        # Join outside the lock so their final job record can be completed.
        deadline = time.monotonic() + 15
        for thread in threads:
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(max(0, deadline - time.monotonic()))
