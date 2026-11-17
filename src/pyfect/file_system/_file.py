"""``LiveFile``: a ``File`` over an OS file descriptor.

The handle keeps its own cursor and reads and writes at positions
(``pread`` / ``pwrite``), so a positional read never moves it and
concurrent reads cannot disturb each other. In append mode writes go to
the end and leave the cursor where it is, as Effect's Node file does."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Never

from pyfect._core import Effect
from pyfect._owned_fd import OwnedFd
from pyfect.effect import fail, succeed, suspend, void
from pyfect.file_system._errors import run
from pyfect.file_system._model import FileInfo, SeekMode
from pyfect.file_system._service import File
from pyfect.file_system._stat import file_info
from pyfect.platform_error import PlatformError, bad_argument, system_error

# Without pread / pwrite (Windows), a seek and a read must not interleave.
_seek_lock = threading.Lock()


def _pread(fd: int, size: int, position: int) -> bytes:
    if hasattr(os, "pread"):
        return os.pread(fd, size, position)
    with _seek_lock:
        os.lseek(fd, position, os.SEEK_SET)
        return os.read(fd, size)


def _pwrite(fd: int, data: bytes, position: int) -> int:
    if hasattr(os, "pwrite"):
        return os.pwrite(fd, data, position)
    with _seek_lock:
        os.lseek(fd, position, os.SEEK_SET)
        return os.write(fd, data)


def _read_into(fd: int, buffer: bytearray | memoryview, position: int) -> int:
    data = _pread(fd, len(buffer), position)
    buffer[: len(data)] = data
    return len(data)


def _before_start(method: str) -> Effect[Never, PlatformError]:
    return fail(
        bad_argument(
            module="FileSystem",
            method=method,
            description="Cannot read before the start of the file",
        )
    )


class LiveFile(File):
    """Its operations use the descriptor through ``owned``, which the
    scope that opened the file closes once they end."""

    __slots__ = ("_append", "_number", "_owned", "_position")

    def __init__(self, number: int, owned: OwnedFd[int], *, append: bool) -> None:
        self._number = number
        self._owned = owned
        self._append = append
        self._position = 0

    @property
    def fd(self) -> int:
        return self._number

    def _run[A](self, method: str, work: Callable[[int], A]) -> Effect[A, PlatformError]:
        """``work`` on the descriptor, on a worker thread."""
        return run(method, self._number, lambda: self._owned.use(work))

    def stat(self) -> Effect[FileInfo, PlatformError]:
        return self._run("stat", lambda fd: file_info(os.fstat(fd)))

    def seek(self, offset: int, whence: SeekMode = "start") -> Effect[int, PlatformError]:
        def go() -> Effect[int, PlatformError]:
            position = offset if whence == "start" else self._position + offset
            if position < 0:
                return fail(
                    bad_argument(
                        module="FileSystem",
                        method="seek",
                        description="Cannot seek before the start of the file",
                    )
                )
            self._position = position
            return succeed(position)

        return suspend(go)

    def sync(self) -> Effect[None, PlatformError]:
        return self._run("sync", os.fsync)

    def read(
        self, buffer: bytearray | memoryview, *, position: int | None = None
    ) -> Effect[int, PlatformError]:
        def go() -> Effect[int, PlatformError]:
            explicit = position
            if explicit is not None:
                if explicit < 0:
                    return _before_start("read")
                return self._run("read", lambda fd: _read_into(fd, buffer, explicit))
            start = self._position
            return self._run("read", lambda fd: _read_into(fd, buffer, start)).map(
                lambda count: self._advance(start, count)
            )

        return suspend(go)

    def read_alloc(
        self, size: int, *, position: int | None = None
    ) -> Effect[bytes | None, PlatformError]:
        def go() -> Effect[bytes | None, PlatformError]:
            if size < 0:
                return fail(
                    bad_argument(
                        module="FileSystem",
                        method="read_alloc",
                        description="size must be a non-negative integer",
                    )
                )
            if position is not None and position < 0:
                return _before_start("read_alloc")
            start = self._position if position is None else position

            def got(data: bytes) -> bytes | None:
                if not data:
                    return None
                if position is None:
                    self._position = start + len(data)
                return data

            return self._run("read_alloc", lambda fd: _pread(fd, size, start)).map(got)

        return suspend(go)

    def truncate(self, length: int = 0) -> Effect[None, PlatformError]:
        def clamp(_: None) -> None:
            if not self._append and self._position > length:
                self._position = length

        return self._run("truncate", lambda fd: os.ftruncate(fd, length)).map(clamp)

    def write(self, data: bytes) -> Effect[int, PlatformError]:
        return suspend(lambda: self._write_once("write", data))

    def write_all(self, data: bytes) -> Effect[None, PlatformError]:
        if not data:
            return void
        return suspend(
            lambda: self._write_once("write_all", data).flat_map(
                lambda written: self._rest(data, written)
            )
        )

    def _rest(self, data: bytes, written: int) -> Effect[None, PlatformError]:
        if written == 0:
            return fail(
                system_error(
                    "WriteZero",
                    module="FileSystem",
                    method="write_all",
                    path_or_descriptor=self._number,
                    description="write returned 0 bytes written",
                )
            )
        return void if written >= len(data) else self.write_all(data[written:])

    def _write_once(self, method: str, data: bytes) -> Effect[int, PlatformError]:
        if self._append:
            return self._run(method, lambda fd: os.write(fd, data))
        start = self._position
        return self._run(method, lambda fd: _pwrite(fd, data, start)).map(
            lambda count: self._advance(start, count)
        )

    def _advance(self, start: int, count: int) -> int:
        self._position = start + count
        return count
