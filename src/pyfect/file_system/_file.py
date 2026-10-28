"""``LiveFile``: a ``File`` over an OS file descriptor.

The handle keeps its own cursor and reads and writes at positions
(``pread`` / ``pwrite``), so a positional read never moves it and
concurrent reads cannot disturb each other. In append mode writes go to
the end and leave the cursor where it is, as Effect's Node file does."""

from __future__ import annotations

import os
import threading
from typing import Never

from pyfect._core import Effect
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
    __slots__ = ("_append", "_fd", "_position")

    def __init__(self, fd: int, *, append: bool) -> None:
        self._fd = fd
        self._append = append
        self._position = 0

    @property
    def fd(self) -> int:
        return self._fd

    def stat(self) -> Effect[FileInfo, PlatformError]:
        return run("stat", self._fd, lambda: file_info(os.fstat(self._fd)))

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
        return run("sync", self._fd, lambda: os.fsync(self._fd))

    def read(
        self, buffer: bytearray | memoryview, *, position: int | None = None
    ) -> Effect[int, PlatformError]:
        def go() -> Effect[int, PlatformError]:
            explicit = position
            if explicit is not None:
                if explicit < 0:
                    return _before_start("read")
                return run("read", self._fd, lambda: _read_into(self._fd, buffer, explicit))
            start = self._position
            return run("read", self._fd, lambda: _read_into(self._fd, buffer, start)).map(
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

            return run("read_alloc", self._fd, lambda: _pread(self._fd, size, start)).map(got)

        return suspend(go)

    def truncate(self, length: int = 0) -> Effect[None, PlatformError]:
        def clamp(_: None) -> None:
            if not self._append and self._position > length:
                self._position = length

        return run("truncate", self._fd, lambda: os.ftruncate(self._fd, length)).map(clamp)

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
                    path_or_descriptor=self._fd,
                    description="write returned 0 bytes written",
                )
            )
        return void if written >= len(data) else self.write_all(data[written:])

    def _write_once(self, method: str, data: bytes) -> Effect[int, PlatformError]:
        if self._append:
            return run(method, self._fd, lambda: os.write(self._fd, data))
        start = self._position
        return run(method, self._fd, lambda: _pwrite(self._fd, data, start)).map(
            lambda count: self._advance(start, count)
        )

    def _advance(self, start: int, count: int) -> int:
        self._position = start + count
        return count
