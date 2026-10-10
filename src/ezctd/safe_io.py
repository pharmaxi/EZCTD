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
from typing import Callable, Iterable


class UnsafeOutputError(ValueError):
    """The requested output could overwrite or pollute protected input."""


class PublishedOutputCleanupError(OSError):
    """The owned output was linked, but removing its temporary name failed.

    Transaction callers can roll back only this recorded inode. A plain path
    existence check cannot establish ownership after a partially completed call.
    """

    def __init__(self, output_path: Path, published_identity: tuple[int, int],
                 temporary_path: Path, cleanup_error: OSError):
        super().__init__('Output was published but temporary cleanup failed: '
                         f'{type(cleanup_error).__name__}: {cleanup_error}')
        self.output_path = output_path
        self.published_identity = published_identity
        self.temporary_path = temporary_path


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


def write_new_bytes(path: Path, data: bytes, *, inputs: Iterable[Path] = (),
                    input_roots: Iterable[Path] = (),
                    on_published: Callable[[Path, tuple[int, int]], None] | None = None) -> Path:
    protected = tuple(inputs)
    roots = tuple(input_roots)
    target = validate_new_output(path, inputs=protected, input_roots=roots)
    target.parent.mkdir(parents=True, exist_ok=True)
    validate_new_output(target, inputs=protected, input_roots=roots)
    fd, temporary = tempfile.mkstemp(prefix='.ezctd-output-', dir=target.parent)
    published = False
    identity = None
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            info = os.fstat(handle.fileno())
            identity = (info.st_dev, info.st_ino)
        validate_new_output(target, inputs=protected, input_roots=roots)
        os.link(temporary, target)
        published = True
        if on_published is not None:
            # The receipt comes from our written file descriptor, before
            # returning control. A later lstat of the destination cannot prove
            # ownership if another process has replaced that pathname.
            on_published(target, identity)
    finally:
        try:
            os.unlink(temporary)
        except OSError as exc:
            if published:
                raise PublishedOutputCleanupError(target, identity, Path(temporary), exc) from exc
            raise
    return target


def write_new_text(path: Path, text: str, *, inputs: Iterable[Path] = (),
                   input_roots: Iterable[Path] = (),
                   on_published: Callable[[Path, tuple[int, int]], None] | None = None) -> Path:
    return write_new_bytes(path, text.encode('utf-8'), inputs=inputs, input_roots=input_roots,
                           on_published=on_published)
