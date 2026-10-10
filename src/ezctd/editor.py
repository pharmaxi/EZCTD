"""Bounded, native-free edit history for one-document page organization.

The workspace owns locking and byte-identity checks. This module stores immutable
page orders and rotation deltas; it never opens or mutates a PDF.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import uuid

MAX_DRAFTS = 16
MAX_HISTORY = 50
MAX_PAGES = 2000
_UNSPECIFIED = object()


class EditorConflict(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Draft:
    id: str
    document_id: str
    source_sha256: str
    page_count: int
    pages: list[dict]
    eligibility: str
    blockers: list
    order: tuple[int, ...]
    rotations: tuple[int, ...]
    revision: int = 0
    undo: list[tuple[tuple[int, ...], tuple[int, ...]]] = field(default_factory=list)
    redo: list[tuple[tuple[int, ...], tuple[int, ...]]] = field(default_factory=list)
    saved_snapshot: tuple[tuple[int, ...], tuple[int, ...]] | None = None
    last_saved_revision: int | None = None
    save_job_id: str | None = None
    save_revision: int | None = None
    saves: dict[int, str] = field(default_factory=dict)
    saving: bool = False
    invalidated: bool = False

    @property
    def snapshot(self):
        return self.order, self.rotations

    @property
    def original(self):
        return tuple(range(1, len(self.pages) + 1)), (0,) * len(self.pages)

    def state(self) -> dict:
        can_edit = self.eligibility == 'ELIGIBLE' and not self.invalidated and not self.saving
        return deepcopy({
            'draft_id': self.id, 'document_id': self.document_id,
            'source_sha256': self.source_sha256, 'revision': self.revision,
            'page_count': self.page_count, 'order': list(self.order),
            'rotations': list(self.rotations), 'pages': self.pages,
            'eligibility': 'BLOCKED' if self.invalidated else self.eligibility,
            'blockers': [*self.blockers, *(['SOURCE_CHANGED'] if self.invalidated else [])],
            'invalidated': self.invalidated, 'saving': self.saving,
            'dirty': self.snapshot != (self.saved_snapshot or self.original),
            'has_changes': self.snapshot != self.original,
            'can_undo': can_edit and bool(self.undo), 'can_redo': can_edit and bool(self.redo),
            'save_job_id': self.save_job_id, 'save_revision': self.save_revision,
            'last_saved_revision': self.last_saved_revision,
            'history_scope': 'CURRENT_SERVER_SESSION',
            'limits': {'max_drafts': MAX_DRAFTS, 'max_history': MAX_HISTORY, 'max_pages': MAX_PAGES},
        })


class EditorStore:
    def __init__(self):
        self.drafts: dict[str, Draft] = {}
        self.by_document: dict[str, str] = {}

    def get(self, ident: str, revision=_UNSPECIFIED) -> Draft:
        if not isinstance(ident, str) or ident not in self.drafts:
            raise ValueError('Unknown session draft; filesystem paths are not accepted')
        draft = self.drafts[ident]
        if revision is not _UNSPECIFIED:
            if type(revision) is not int or revision < 0:
                raise ValueError('Draft revision must be a nonnegative integer')
            if revision != draft.revision:
                raise EditorConflict('STALE_DRAFT', 'Draft changed; refresh its current revision before continuing')
        return draft

    def open(self, document_id: str, inspected: dict) -> Draft:
        if document_id in self.by_document:
            return self.get(self.by_document[document_id])
        if len(self.drafts) >= MAX_DRAFTS:
            raise ValueError('Session draft limit reached (16); finish this workspace before opening more editors')
        count, pages = inspected.get('page_count'), inspected.get('pages')
        eligible = inspected.get('eligibility') == 'ELIGIBLE'
        if type(count) is not int or count < 0 or (eligible and not 1 <= count <= MAX_PAGES):
            raise ValueError('Page editor supports PDFs of 1 to 2000 pages')
        if (not isinstance(pages, list) or (eligible and len(pages) != count)
                or any(not isinstance(item, dict) for item in pages)
                or (pages and [item.get('source_page') for item in pages] != list(range(1, count + 1)))):
            raise RuntimeError('Page inspection returned incomplete source-page metadata')
        draft = Draft(uuid.uuid4().hex, document_id, inspected['source_sha256'], count,
                      deepcopy(pages), inspected['eligibility'], deepcopy(inspected.get('blockers', [])),
                      tuple(range(1, len(pages) + 1)), (0,) * len(pages))
        self.drafts[draft.id] = draft
        self.by_document[document_id] = draft.id
        return draft

    def invalidate(self, document_id: str) -> None:
        if document_id in self.by_document:
            self.get(self.by_document[document_id]).invalidated = True

    @staticmethod
    def require_editable(draft: Draft) -> None:
        if draft.invalidated:
            raise ValueError('SOURCE_CHANGED: close and reopen workspace to accept the new source version')
        if draft.saving:
            raise EditorConflict('DRAFT_BUSY', 'Wait for the current save to finish before editing')
        if draft.eligibility != 'ELIGIBLE':
            raise ValueError('This PDF is blocked for page organization: ' + ', '.join(map(str, draft.blockers)))

    def edit(self, ident: str, revision: int, command: dict) -> dict:
        draft = self.get(ident, revision)
        self.require_editable(draft)
        if not isinstance(command, dict):
            raise ValueError('An explicit edit command is required')
        kind = command.get('type')
        order, rotations = draft.snapshot
        count = len(order)
        if kind == 'reorder' and set(command) == {'type', 'order'}:
            requested = command['order']
            if (not isinstance(requested, list) or len(requested) != count
                    or any(type(page) is not int for page in requested)
                    or set(requested) != set(range(1, count + 1))):
                raise ValueError('Order must contain every original page exactly once')
            order = tuple(requested)
        elif kind == 'rotate' and set(command) == {'type', 'pages', 'degrees'}:
            pages, degrees = command['pages'], command['degrees']
            if (not isinstance(pages, list) or not 1 <= len(pages) <= count
                    or any(type(page) is not int or not 1 <= page <= count for page in pages)
                    or len(set(pages)) != len(pages)
                    or type(degrees) is not int or degrees not in (-90, 90)):
                raise ValueError('Rotate requires unique original page numbers and +90 or -90 degrees')
            selected = set(pages)
            rotations = tuple((rotation + degrees) % 360 if index in selected else rotation
                              for index, rotation in enumerate(rotations, 1))
        elif kind == 'reset' and set(command) == {'type'}:
            order, rotations = draft.original
        else:
            raise ValueError('Unsupported edit command or unexpected parameters')
        if (order, rotations) != draft.snapshot:
            draft.undo.append(draft.snapshot)
            del draft.undo[:-MAX_HISTORY]
            draft.redo.clear()
            draft.order, draft.rotations = order, rotations
            draft.revision += 1
        return draft.state()

    def move_history(self, ident: str, revision: int, *, redo: bool = False) -> dict:
        draft = self.get(ident, revision)
        self.require_editable(draft)
        source, target = (draft.redo, draft.undo) if redo else (draft.undo, draft.redo)
        if not source:
            raise ValueError('No edit to redo' if redo else 'No edit to undo')
        target.append(draft.snapshot)
        del target[:-MAX_HISTORY]
        draft.order, draft.rotations = source.pop()
        draft.revision += 1
        return draft.state()
