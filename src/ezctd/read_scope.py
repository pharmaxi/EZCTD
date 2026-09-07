"""Explicit local read boundaries for a partial CRO dataset.

This is application-level policy for a trusted workspace, not an OS sandbox.
Document references outside selected roots are never probed. Linked components
are rejected before opening; a hostile concurrent rename still needs OS isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import re
import stat


class UnsafeInputError(ValueError):
    pass


def reject_linked_components(path: Path) -> None:
    for component in [*reversed(path.parents), path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (getattr(info, 'st_file_attributes', 0) & 0x400):
            raise UnsafeInputError('Linked input component requires an explicit non-linked location')


def selected_path(path: Path, *, directory: bool = False) -> Path:
    # Never resolve first: it hides the symlink the caller actually selected.
    candidate = Path(os.path.abspath(path))
    reject_linked_components(candidate)
    info = candidate.stat()
    wanted = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not wanted:
        raise UnsafeInputError('Input must be a directory' if directory else 'Input must be a regular file')
    return candidate


@dataclass(frozen=True)
class TargetResolution:
    state: str
    path: Path | None = None
    reason: str = ''


class ReadScope:
    def __init__(self, roots: tuple[Path, ...]):
        if not roots:
            raise UnsafeInputError('At least one explicitly selected read root is required')
        self.roots = tuple(selected_path(root, directory=True) for root in roots)

    def contains(self, path: Path) -> bool:
        candidate = Path(os.path.abspath(path))
        return any(candidate.is_relative_to(root) for root in self.roots)

    def authorize(self, path: Path) -> Path:
        candidate = Path(os.path.abspath(path))
        # Check lexical membership BEFORE stat, exists, resolve, or opening.
        if not self.contains(candidate):
            raise UnsafeInputError('Target is outside the explicitly selected read roots')
        return selected_path(candidate)

    def resolve_reference(self, source: Path, raw: str | None) -> TargetResolution:
        if not raw or '\x00' in raw:
            return TargetResolution('UNRESOLVED', reason='Missing or invalid file specification')
        if PureWindowsPath(raw).drive or raw.startswith(('/', '\\')):
            return TargetResolution('ABSOLUTE_NOT_FOLLOWED', reason='Absolute/UNC targets are not automatically accessed')
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw):
            return TargetResolution('EXTERNAL_NOT_FOLLOWED', reason='URI targets are not fetched')
        candidate = Path(os.path.abspath(source.parent / raw.replace('\\', '/')))
        if not self.contains(candidate):
            return TargetResolution('NOT_PROVIDED', reason='Outside this partial delivery; not proof of a broken submission link')
        try:
            authorized = self.authorize(candidate)
        except FileNotFoundError:
            return TargetResolution('NOT_PROVIDED', reason='Target is absent from the selected delivery')
        except UnsafeInputError as exc:
            return TargetResolution('ACCESS_BLOCKED', reason=str(exc))
        return TargetResolution('AVAILABLE', authorized)
