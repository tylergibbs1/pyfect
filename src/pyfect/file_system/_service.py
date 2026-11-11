"""The ``FileSystem`` service: its interface, the ``File`` handle, and the
operations every implementation derives from the others (Effect's
``FileSystem.make``)."""

from __future__ import annotations

import codecs
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any, Never, Protocol

from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.errors import Done
from pyfect.file_system._glob import glob as glob_walk
from pyfect.file_system._model import (
    DirectoryEntry,
    FileInfo,
    OpenFlag,
    SeekMode,
    WatchEvent,
)
from pyfect.platform_error import NotFound, PlatformError, bad_argument
from pyfect.scope import Scope
from pyfect.sink import Sink, for_each
from pyfect.sink import unwrap as unwrap_sink
from pyfect.stream import Stream

DEFAULT_CHUNK_SIZE = 64 * 1024
"""Bytes per chunk ``FileSystem.stream`` reads by default."""


class File(ABC):
    """An open file, closed when the scope ``FileSystem.open`` ran in
    closes. Reads and writes move a cursor the handle keeps, unless given a
    ``position``."""

    @abstractmethod
    def stat(self) -> Effect[FileInfo, PlatformError]: ...

    @abstractmethod
    def seek(self, offset: int, whence: SeekMode = "start") -> Effect[int, PlatformError]:
        """Move the cursor to ``offset`` from the start or the current
        position; succeeds with the new position. Fails with a
        ``BadArgument`` before the start of the file."""

    @abstractmethod
    def sync(self) -> Effect[None, PlatformError]:
        """Flush the file's data to the device (``fsync``)."""

    @abstractmethod
    def read(
        self, buffer: bytearray | memoryview, *, position: int | None = None
    ) -> Effect[int, PlatformError]:
        """Read into ``buffer``; succeeds with the bytes read (0 at the
        end)."""

    @abstractmethod
    def read_alloc(
        self, size: int, *, position: int | None = None
    ) -> Effect[bytes | None, PlatformError]:
        """Read up to ``size`` bytes; ``None`` at the end of the file."""

    @abstractmethod
    def truncate(self, length: int = 0) -> Effect[None, PlatformError]: ...

    @abstractmethod
    def write(self, data: bytes) -> Effect[int, PlatformError]:
        """Write once; succeeds with the bytes written, maybe fewer than
        ``len(data)``."""

    @abstractmethod
    def write_all(self, data: bytes) -> Effect[None, PlatformError]:
        """Write all of ``data``."""


class FileSystemService(ABC):
    """Files and directories (Effect's ``FileSystem``). Paths are strings;
    every operation fails with a ``PlatformError``.

    An implementation defines the abstract operations; ``exists``, ``glob``,
    ``read_file_string``, ``write_file_string``, ``stream`` and ``sink`` are
    built from them."""

    @abstractmethod
    def access(
        self, path: str, *, readable: bool = False, writable: bool = False
    ) -> Effect[None, PlatformError]:
        """Succeed when ``path`` exists (and is readable / writable)."""

    @abstractmethod
    def copy(
        self,
        from_path: str,
        to_path: str,
        *,
        overwrite: bool = False,
        preserve_timestamps: bool = False,
    ) -> Effect[None, PlatformError]:
        """Copy a file or a directory tree. Without ``overwrite``, files
        that exist at the destination are kept."""

    @abstractmethod
    def copy_file(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        """Copy the file ``from_path`` (its contents and permissions) to
        ``to_path``, replacing a file there."""

    @abstractmethod
    def chmod(self, path: str, mode: int) -> Effect[None, PlatformError]:
        """Set the permissions of ``path`` to ``mode`` (``0o644``, say)."""

    @abstractmethod
    def chown(self, path: str, uid: int, gid: int) -> Effect[None, PlatformError]:
        """Set the owner of ``path`` to user ``uid`` and group ``gid``."""

    @abstractmethod
    def link(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        """Make ``to_path`` a hard link to ``from_path``."""

    @abstractmethod
    def lstat(self, path: str) -> Effect[FileInfo, PlatformError]:
        """``stat`` of a symbolic link itself."""

    @abstractmethod
    def make_directory(
        self, path: str, *, recursive: bool = False, mode: int = 0o777
    ) -> Effect[None, PlatformError]:
        """Make a directory; with ``recursive``, its missing parents too, and
        an existing directory is no error."""

    @abstractmethod
    def make_temp_directory(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError]:
        """Make a new directory named with ``prefix`` in ``directory`` (the
        system's temporary directory by default) and give its path. Nothing
        removes it; ``make_temp_directory_scoped`` does."""

    @abstractmethod
    def make_temp_directory_scoped(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        """A temporary directory, removed with its contents when the scope
        closes."""

    @abstractmethod
    def make_temp_file(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError]:
        """An empty file in a new temporary directory named with
        ``prefix``."""

    @abstractmethod
    def make_temp_file_scoped(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        """A temporary file, removed with its directory when the scope
        closes."""

    @abstractmethod
    def open(
        self, path: str, *, flag: OpenFlag = "r", mode: int = 0o666, no_follow: bool = False
    ) -> Effect[File, PlatformError, Scope]:
        """Open a file until the scope closes. ``no_follow`` refuses a
        symbolic link (``BadResource``), or fails with ``BadArgument``
        where the platform cannot tell."""

    @abstractmethod
    def read_directory(
        self, path: str, *, recursive: bool = False
    ) -> Effect[list[str], PlatformError]:
        """The names in a directory; with ``recursive``, every path below
        it, relative to it."""

    @abstractmethod
    def read_directory_entries(
        self, path: str
    ) -> Effect[tuple[DirectoryEntry, ...], PlatformError]:
        """The names in a directory (as ``read_directory``, in no particular
        order) with the type of each entry itself, not of a link's target;
        ``"Unknown"`` where the listing cannot tell, and ``glob`` then asks
        ``stat``. A wrapper that changes ``read_directory`` (prefixing
        paths, say) must change this the same way for ``glob`` to list the
        right directory."""

    @abstractmethod
    def read_file(self, path: str) -> Effect[bytes, PlatformError]:
        """The contents of the file ``path``."""

    @abstractmethod
    def read_link(self, path: str) -> Effect[str, PlatformError]:
        """Where the symbolic link ``path`` points, as written in the
        link."""

    @abstractmethod
    def real_path(self, path: str) -> Effect[str, PlatformError]:
        """The canonical path, every symbolic link resolved."""

    @abstractmethod
    def remove(
        self, path: str, *, recursive: bool = False, force: bool = False
    ) -> Effect[None, PlatformError]:
        """Remove a file, or a directory with ``recursive``. With ``force``
        a missing path is no error."""

    @abstractmethod
    def rename(self, old_path: str, new_path: str) -> Effect[None, PlatformError]:
        """Move the file or directory ``old_path`` to ``new_path``."""

    @abstractmethod
    def stat(self, path: str) -> Effect[FileInfo, PlatformError]:
        """What is known about ``path`` (a symbolic link is followed; see
        ``lstat``)."""

    @abstractmethod
    def symlink(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        """Make ``to_path`` a symbolic link pointing at ``from_path``."""

    @abstractmethod
    def truncate(self, path: str, length: int = 0) -> Effect[None, PlatformError]:
        """Cut the file ``path`` to ``length`` bytes (empty by default),
        or extend it with zero bytes."""

    @abstractmethod
    def utimes(
        self, path: str, atime: datetime | float, mtime: datetime | float
    ) -> Effect[None, PlatformError]:
        """Set the access and modification times (a ``datetime``, or
        seconds since the epoch)."""

    @abstractmethod
    def watch(
        self, path: str, *, recursive: bool = False, on_ready: Callable[[], None] | None = None
    ) -> Stream[WatchEvent, PlatformError]:
        """The changes under ``path`` (a directory, or one file), as they
        happen. ``on_ready`` runs once changes are being watched."""

    @abstractmethod
    def write_file(
        self, path: str, data: bytes, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Effect[None, PlatformError]:
        """Write ``data`` to the file ``path``, opened with ``flag`` (made
        or truncated by default; ``"a"`` appends). A file it makes gets
        ``mode`` (less the umask)."""

    # --- derived -------------------------------------------------------------

    def glob(
        self,
        pattern: str,
        *,
        root: str | None = None,
        exclude: tuple[str, ...] = (),
        dot: bool = False,
    ) -> Effect[list[str], PlatformError]:
        """The paths below ``root`` (the working directory) matching the
        ``pyfect.glob`` pattern and none of ``exclude``: ``/``-separated,
        relative to ``root`` (absolute for an absolute pattern), depth
        first with each directory's entries sorted by name. Wildcards skip
        names that start with ``.`` unless the segment does or ``dot`` is
        set, and ``dir/**`` includes ``dir``. ``**`` does not follow
        symbolic links to directories; a link named by another segment is
        followed. Excluded directories are not read; an entry whose type
        cannot be told (a broken link) counts as a file.

        Failing to read the root or a leading literal directory fails;
        missing paths give nothing, and unreadable directories reached
        through wildcards are skipped. Wildcards are case-sensitive; leading
        literal segments use ``stat``, so they follow the file system's case
        rules and results keep the pattern's spelling. Built from
        ``read_directory_entries``, ``stat`` and ``read_link``."""
        return glob_walk(self, pattern, root=root, exclude=exclude, dot=dot)

    def exists(self, path: str) -> Effect[bool, PlatformError]:
        """Whether ``path`` exists; errors other than ``NotFound`` fail."""
        return self.access(path).map(lambda _: True).catch_all(_false_if_not_found)

    def read_file_string(self, path: str, encoding: str = "utf-8") -> Effect[str, PlatformError]:
        """The file decoded as ``encoding``; undecodable bytes become
        U+FFFD and a leading byte order mark is dropped, as JavaScript's
        ``TextDecoder`` does. An unknown encoding is a ``BadArgument``."""
        return self.read_file(path).flat_map(lambda data: _decode(data, encoding))

    def write_file_string(
        self, path: str, data: str, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Effect[None, PlatformError]:
        """``data`` as UTF-8 (a lone surrogate becomes U+FFFD)."""
        return self.write_file(path, text_encode(data), flag=flag, mode=mode)

    def stream(
        self,
        path: str,
        *,
        offset: int = 0,
        bytes_to_read: int | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> Stream[bytes, PlatformError]:
        """The file's bytes from ``offset``, ``chunk_size`` at a time, up to
        ``bytes_to_read`` of them. The file opens when the stream starts and
        closes when it ends."""

        def make() -> Generator[
            Effect[Any, PlatformError, Scope], Any, Stream[bytes, PlatformError]
        ]:
            file = yield from self.open(path, flag="r")
            if offset:
                yield from file.seek(offset, "start")
            return stream_.from_pull(succeed(_reader(file, bytes_to_read, chunk_size)))

        return stream_.unwrap(gen(make))

    def sink(
        self, path: str, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Sink[None, bytes, Never, PlatformError]:
        """A sink writing each chunk it reads to the file, opened (truncated
        by default) when the sink starts."""
        return unwrap_sink(
            self.open(path, flag=flag, mode=mode).map(lambda file: for_each(file.write_all))
        )


def _false_if_not_found(error: PlatformError) -> Effect[bool, PlatformError]:
    return succeed(False) if isinstance(error.reason, NotFound) else fail(error)


def _decode(data: bytes, encoding: str) -> Effect[str, PlatformError]:
    try:
        name = codecs.lookup(encoding).name
        # A codec that is no text encoding (rot13, base64) raises here.
        text = data.decode(name, errors="replace")
    except LookupError as error:
        return fail(
            bad_argument(
                module="FileSystem",
                method="read_file_string",
                description="invalid encoding",
                cause=error,
            )
        )
    if text.startswith("﻿") and name.startswith(("utf-8", "utf-16")):
        text = text[1:]
    return succeed(text)


def _reader(
    file: File, bytes_to_read: int | None, chunk_size: int
) -> Effect[tuple[bytes, ...], PlatformError | Done]:
    total = 0

    def pull() -> Effect[tuple[bytes, ...], PlatformError | Done]:
        if bytes_to_read is not None and bytes_to_read <= total:
            return fail(Done())
        size = chunk_size if bytes_to_read is None else min(chunk_size, bytes_to_read - total)
        return file.read_alloc(size).flat_map(got)

    def got(data: bytes | None) -> Effect[tuple[bytes, ...], Done]:
        nonlocal total
        if data is None:
            return fail(Done())
        total += len(data)
        return succeed((data,))

    return suspend(pull)


class FileSystem(Tag[FileSystemService]):
    """The file system a program uses."""


class WatchBackendService(Protocol):
    """Watches a path in place of the file system's own watcher: ``None``
    leaves the path to it."""

    def register(
        self,
        path: str,
        info: FileInfo,
        *,
        recursive: bool,
        on_ready: Callable[[], None] | None,
    ) -> Stream[WatchEvent, PlatformError] | None: ...


class WatchBackend(Tag[WatchBackendService]):
    """A watcher ``FileSystem.watch`` tries first: the one provided where the
    stream runs, else the one provided where the file system was built."""
