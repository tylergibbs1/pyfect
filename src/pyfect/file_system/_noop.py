"""``NoopFileSystem``: a file system with nothing in it, for tests (Effect's
``FileSystem.makeNoop`` / ``layerNoop``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Never

from pyfect import sink as sink_
from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect.effect import die, fail, succeed, void
from pyfect.file_system._errors import not_found
from pyfect.file_system._model import FileInfo, OpenFlag, WatchEvent
from pyfect.file_system._service import (
    DEFAULT_CHUNK_SIZE,
    File,
    FileSystem,
    FileSystemService,
)
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import PlatformError
from pyfect.scope import Scope
from pyfect.sink import Sink
from pyfect.stream import Stream


def _missing[A = Never](method: str, path: str) -> Effect[A, PlatformError]:
    return fail(not_found(method, path))


def _unimplemented() -> Effect[Never]:
    return die(NotImplementedError("not implemented"))


class NoopFileSystem(FileSystemService):
    """Every path is missing: reads fail with ``NotFound``, ``exists`` is
    ``False``, ``remove`` does nothing, and making directories or temporary
    files dies. Subclass it and override what a test needs::

        class Env(NoopFileSystem):
            def read_file_string(self, path: str, encoding: str = "utf-8"):
                return fx.succeed("A=1")
    """

    def access(
        self, path: str, *, readable: bool = False, writable: bool = False
    ) -> Effect[None, PlatformError]:
        return _missing("access", path)

    def copy(
        self,
        from_path: str,
        to_path: str,
        *,
        overwrite: bool = False,
        preserve_timestamps: bool = False,
    ) -> Effect[None, PlatformError]:
        return _missing("copy", from_path)

    def copy_file(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return _missing("copy_file", from_path)

    def chmod(self, path: str, mode: int) -> Effect[None, PlatformError]:
        return _missing("chmod", path)

    def chown(self, path: str, uid: int, gid: int) -> Effect[None, PlatformError]:
        return _missing("chown", path)

    def glob(
        self, pattern: str, *, root: str | None = None, exclude: tuple[str, ...] = ()
    ) -> Effect[list[str], PlatformError]:
        return _missing("glob", pattern)

    def exists(self, path: str) -> Effect[bool, PlatformError]:
        return succeed(False)

    def link(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return _missing("link", from_path)

    def lstat(self, path: str) -> Effect[FileInfo, PlatformError]:
        return _missing("lstat", path)

    def make_directory(
        self, path: str, *, recursive: bool = False, mode: int = 0o777
    ) -> Effect[None, PlatformError]:
        return _unimplemented()

    def make_temp_directory(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError]:
        return _unimplemented()

    def make_temp_directory_scoped(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        return _unimplemented()

    def make_temp_file(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError]:
        return _unimplemented()

    def make_temp_file_scoped(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        return _unimplemented()

    def open(
        self, path: str, *, flag: OpenFlag = "r", mode: int = 0o666, no_follow: bool = False
    ) -> Effect[File, PlatformError, Scope]:
        return _missing("open", path)

    def read_directory(
        self, path: str, *, recursive: bool = False
    ) -> Effect[list[str], PlatformError]:
        return _missing("read_directory", path)

    def read_file(self, path: str) -> Effect[bytes, PlatformError]:
        return _missing("read_file", path)

    def read_file_string(self, path: str, encoding: str = "utf-8") -> Effect[str, PlatformError]:
        return _missing("read_file_string", path)

    def read_link(self, path: str) -> Effect[str, PlatformError]:
        return _missing("read_link", path)

    def real_path(self, path: str) -> Effect[str, PlatformError]:
        return _missing("real_path", path)

    def remove(
        self, path: str, *, recursive: bool = False, force: bool = False
    ) -> Effect[None, PlatformError]:
        return void

    def rename(self, old_path: str, new_path: str) -> Effect[None, PlatformError]:
        return _missing("rename", old_path)

    def sink(
        self, path: str, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Sink[None, bytes, Never, PlatformError]:
        return sink_.fail(not_found("sink", path))

    def stat(self, path: str) -> Effect[FileInfo, PlatformError]:
        return _missing("stat", path)

    def stream(
        self,
        path: str,
        *,
        offset: int = 0,
        bytes_to_read: int | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> Stream[bytes, PlatformError]:
        return stream_.fail(not_found("stream", path))

    def symlink(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return _missing("symlink", from_path)

    def truncate(self, path: str, length: int = 0) -> Effect[None, PlatformError]:
        return _missing("truncate", path)

    def utimes(
        self, path: str, atime: datetime | float, mtime: datetime | float
    ) -> Effect[None, PlatformError]:
        return _missing("utimes", path)

    def watch(
        self, path: str, *, recursive: bool = False, on_ready: Callable[[], None] | None = None
    ) -> Stream[WatchEvent, PlatformError]:
        return stream_.fail(not_found("watch", path))

    def write_file(
        self, path: str, data: bytes, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Effect[None, PlatformError]:
        return _missing("write_file", path)

    def write_file_string(
        self, path: str, data: str, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Effect[None, PlatformError]:
        return _missing("write_file_string", path)


def layer_noop(file_system: NoopFileSystem | None = None) -> Layer[FileSystem]:
    """A layer providing ``file_system`` (a ``NoopFileSystem`` subclass
    instance), or an empty ``NoopFileSystem``."""
    return layer_succeed(FileSystem, NoopFileSystem() if file_system is None else file_system)
