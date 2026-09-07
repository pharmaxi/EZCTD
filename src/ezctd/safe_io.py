"""No-clobber report output for trusted local workspaces.

Reject existing destinations, source-tree outputs and linked parent directories.
Publish a complete temporary file using a no-replace hard link. Unsupported
filesystems fail closed. This is not an OS sandbox against a hostile process
concurrently replacing directories; Windows/NAS integration remains required.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import Iterable


class UnsafeOutputError(ValueError):
    """The requested output could overwrite or pollute protected input."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _reject_linked_components(path: Path) -> None:
    # Do not resolve first: doing so would hide a symlink or Windows junction.
    for component in [*reversed(path.parents), path]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        ):
            raise UnsafeOutputError('Output path includes a symlink or reparse point')


def validate_new_output(path: Path, *, inputs: Iterable[Path] = (),
                        input_roots: Iterable[Path] = ()) -> Path:
    target = Path(os.path.abspath(path))
    _reject_linked_components(target)
    if os.path.lexists(target):
        # Refusing ALL existing outputs also rejects hard-linked input aliases.
        raise UnsafeOutputError('Output already exists; choose a new destination')
    for source in inputs:
        if target == source.resolve():
            raise UnsafeOutputError('Output must not equal an input')
    for root in input_roots:
        if target.is_relative_to(root.resolve()):
            raise UnsafeOutputError('Reports must be outside the input directory tree')
    return target


def write_new_text(path: Path, text: str, *, inputs: Iterable[Path] = (),
                   input_roots: Iterable[Path] = ()) -> Path:
    protected = tuple(inputs)
    roots = tuple(input_roots)
    target = validate_new_output(path, inputs=protected, input_roots=roots)
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_new_output(target, inputs=protected, input_roots=roots)
    fd, temporary = tempfile.mkstemp(prefix='.ezctd-report-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        validate_new_output(target, inputs=protected, input_roots=roots)
        # Unlike POSIX rename/replace, link fails if a destination appeared.
        os.link(temporary, target)
    finally:
        os.unlink(temporary)
    return target
