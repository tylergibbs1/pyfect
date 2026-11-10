"""``LiveFileSystem``: the ``FileSystem`` over Python's ``os``, ``shutil``
and ``tempfile`` (the counterpart of Effect's Node file system). Every call
runs on a worker thread, so fibers never block on the disk."""

from __future__ import annotations

import errno
import os
import secrets
import shutil
import stat
import tempfile
from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any

from pyfect import option
from pyfect import stream as stream_
from pyfect._context_effects import service_option
from pyfect._core import Effect
from pyfect.duration import Seconds
from pyfect.effect import fail, gen
from pyfect.file_system._copy import copy_tree
from pyfect.file_system._errors import run
from pyfect.file_system._file import LiveFile
from pyfect.file_system._model import DirectoryEntry, FileInfo, FileType, OpenFlag, WatchEvent
from pyfect.file_system._service import (
    File,
    FileSystem,
    FileSystemService,
    WatchBackend,
    WatchBackendService,
)
from pyfect.file_system._stat import EPOCH, file_info
from pyfect.file_system._watch import poll
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.platform_error import PlatformError, bad_argument
from pyfect.scope import Scope, acquire_release
from pyfect.stream import Stream

_O_BINARY: int = getattr(os, "O_BINARY", 0)

_OPEN_FLAGS: dict[OpenFlag, int] = {
    "r": os.O_RDONLY,
    "r+": os.O_RDWR,
    "w": os.O_TRUNC | os.O_CREAT | os.O_WRONLY,
    "wx": os.O_TRUNC | os.O_CREAT | os.O_WRONLY | os.O_EXCL,
    "w+": os.O_TRUNC | os.O_CREAT | os.O_RDWR,
    "wx+": os.O_TRUNC | os.O_CREAT | os.O_RDWR | os.O_EXCL,
    "a": os.O_APPEND | os.O_CREAT | os.O_WRONLY,
    "ax": os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_EXCL,
    "a+": os.O_APPEND | os.O_CREAT | os.O_RDWR,
    "ax+": os.O_APPEND | os.O_CREAT | os.O_RDWR | os.O_EXCL,
}

DEFAULT_WATCH_INTERVAL = Seconds(0.05)


def _open_flags(flag: OpenFlag) -> int:
    return _OPEN_FLAGS[flag] | _O_BINARY


def _access(path: str, readable: bool, writable: bool) -> None:
    os.stat(path)
    mode = (os.R_OK if readable else 0) | (os.W_OK if writable else 0)
    if mode and not os.access(path, mode):
        raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)


def _copy_file(source: str, target: str) -> None:
    shutil.copyfile(source, target)
    shutil.copymode(source, target)


def _entry_type(entry: os.DirEntry[str]) -> FileType:
    """Node's ``Dirent`` type: the entry itself, a link not followed."""
    try:
        if entry.is_symlink():
            return "SymbolicLink"
        if entry.is_dir(follow_symlinks=False):
            return "Directory"
        if entry.is_file(follow_symlinks=False):
            return "File"
        return file_info(entry.stat(follow_symlinks=False)).type
    except OSError:
        return "Unknown"


def _read_directory_entries(path: str) -> tuple[DirectoryEntry, ...]:
    with os.scandir(path) as entries:
        return tuple(DirectoryEntry(entry.name, _entry_type(entry)) for entry in entries)


def _make_directory(path: str, recursive: bool, mode: int) -> None:
    if recursive:
        os.makedirs(path, mode, exist_ok=True)
    else:
        os.mkdir(path, mode)


def _temp_directory(directory: str | None, prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=directory)


def _temp_file(directory: str | None, prefix: str, suffix: str) -> str:
    name = os.path.join(_temp_directory(directory, prefix), secrets.token_hex(6) + suffix)
    _write(name, b"", "w", 0o666)
    return name


def _read_directory(path: str, recursive: bool) -> list[str]:
    names = os.listdir(path)
    if not recursive:
        return names
    found: list[str] = []
    pending = [""]
    while pending:
        relative = pending.pop()
        for name in os.listdir(os.path.join(path, relative)) if relative else names:
            child = os.path.join(relative, name) if relative else name
            found.append(child)
            if os.path.isdir(os.path.join(path, child)) and not os.path.islink(
                os.path.join(path, child)
            ):
                pending.append(child)
    return found


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _remove(path: str, recursive: bool, force: bool) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if force:
            return
        raise
    if not stat.S_ISDIR(info.st_mode):
        os.remove(path)
    elif recursive:
        shutil.rmtree(path)
    else:
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)


def _nanos(time: datetime | float) -> int:
    if isinstance(time, datetime):
        if time.tzinfo is None:
            raise ValueError("naive datetime: give it a time zone")
        delta = time - EPOCH
        return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000
    return round(time * 1_000_000_000)


def _write(path: str, data: bytes, flag: OpenFlag, mode: int) -> None:
    fd = os.open(path, _open_flags(flag), mode)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written == 0:
                raise OSError(errno.EIO, "write returned 0 bytes written", path)
            view = view[written:]
    finally:
        os.close(fd)


class LiveFileSystem(FileSystemService):
    """The host's file system. ``watch`` polls every ``watch_interval``
    seconds unless a ``WatchBackend`` takes the path: the one provided
    where the stream runs, else ``backend``."""

    __slots__ = ("_backend", "_watch_interval")

    def __init__(
        self,
        *,
        backend: WatchBackendService | None = None,
        watch_interval: Seconds = DEFAULT_WATCH_INTERVAL,
    ) -> None:
        self._backend = backend
        self._watch_interval = watch_interval

    def access(
        self, path: str, *, readable: bool = False, writable: bool = False
    ) -> Effect[None, PlatformError]:
        return run("access", path, lambda: _access(path, readable, writable))

    def copy(
        self,
        from_path: str,
        to_path: str,
        *,
        overwrite: bool = False,
        preserve_timestamps: bool = False,
    ) -> Effect[None, PlatformError]:
        return run(
            "copy",
            from_path,
            lambda: copy_tree(from_path, to_path, overwrite, preserve_timestamps),
        )

    def copy_file(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return run("copy_file", from_path, lambda: _copy_file(from_path, to_path))

    def chmod(self, path: str, mode: int) -> Effect[None, PlatformError]:
        return run("chmod", path, lambda: os.chmod(path, mode))

    def chown(self, path: str, uid: int, gid: int) -> Effect[None, PlatformError]:
        return run("chown", path, lambda: os.chown(path, uid, gid))

    def link(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return run("link", from_path, lambda: os.link(from_path, to_path))

    def lstat(self, path: str) -> Effect[FileInfo, PlatformError]:
        return run("lstat", path, lambda: file_info(os.lstat(path)))

    def make_directory(
        self, path: str, *, recursive: bool = False, mode: int = 0o777
    ) -> Effect[None, PlatformError]:
        return run("make_directory", path, lambda: _make_directory(path, recursive, mode))

    def make_temp_directory(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError]:
        return run("make_temp_directory", directory, lambda: _temp_directory(directory, prefix))

    def make_temp_directory_scoped(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        method = "make_temp_directory_scoped"
        return acquire_release(
            run(method, directory, lambda: _temp_directory(directory, prefix)),
            lambda path, _exit: run(method, path, lambda: _remove(path, True, True)).or_die(),
        )

    def make_temp_file(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError]:
        return run("make_temp_file", directory, lambda: _temp_file(directory, prefix, suffix))

    def make_temp_file_scoped(
        self, *, directory: str | None = None, prefix: str = "", suffix: str = ""
    ) -> Effect[str, PlatformError, Scope]:
        method = "make_temp_file_scoped"
        return acquire_release(
            run(method, directory, lambda: _temp_file(directory, prefix, suffix)),
            lambda path, _exit: run(
                method, path, lambda: _remove(os.path.dirname(path), True, True)
            ).or_die(),
        )

    def open(
        self, path: str, *, flag: OpenFlag = "r", mode: int = 0o666, no_follow: bool = False
    ) -> Effect[File, PlatformError, Scope]:
        flags = _open_flags(flag)
        if no_follow:
            no_follow_flag: int = getattr(os, "O_NOFOLLOW", 0)
            if os.name == "nt" or not no_follow_flag:
                return fail(
                    bad_argument(
                        module="FileSystem",
                        method="open",
                        description="no_follow is not supported on this platform",
                    )
                )
            flags |= no_follow_flag
        return acquire_release(
            run("open", path, lambda: os.open(path, flags, mode)),
            lambda fd, _exit: run("open", fd, lambda: os.close(fd)).or_die(),
        ).map(lambda fd: LiveFile(fd, append=flag.startswith("a")))

    def read_directory(
        self, path: str, *, recursive: bool = False
    ) -> Effect[list[str], PlatformError]:
        return run("read_directory", path, lambda: _read_directory(path, recursive))

    def read_directory_entries(
        self, path: str
    ) -> Effect[tuple[DirectoryEntry, ...], PlatformError]:
        return run("read_directory_entries", path, lambda: _read_directory_entries(path))

    def read_file(self, path: str) -> Effect[bytes, PlatformError]:
        return run("read_file", path, lambda: _read(path))

    def read_link(self, path: str) -> Effect[str, PlatformError]:
        return run("read_link", path, lambda: os.readlink(path))

    def real_path(self, path: str) -> Effect[str, PlatformError]:
        return run("real_path", path, lambda: os.path.realpath(path, strict=True))

    def remove(
        self, path: str, *, recursive: bool = False, force: bool = False
    ) -> Effect[None, PlatformError]:
        return run("remove", path, lambda: _remove(path, recursive, force))

    def rename(self, old_path: str, new_path: str) -> Effect[None, PlatformError]:
        return run("rename", old_path, lambda: os.replace(old_path, new_path))

    def stat(self, path: str) -> Effect[FileInfo, PlatformError]:
        return run("stat", path, lambda: file_info(os.stat(path)))

    def symlink(self, from_path: str, to_path: str) -> Effect[None, PlatformError]:
        return run("symlink", from_path, lambda: os.symlink(from_path, to_path))

    def truncate(self, path: str, length: int = 0) -> Effect[None, PlatformError]:
        return run("truncate", path, lambda: os.truncate(path, length))

    def utimes(
        self, path: str, atime: datetime | float, mtime: datetime | float
    ) -> Effect[None, PlatformError]:
        return run("utimes", path, lambda: os.utime(path, ns=(_nanos(atime), _nanos(mtime))))

    def watch(
        self, path: str, *, recursive: bool = False, on_ready: Callable[[], None] | None = None
    ) -> Stream[WatchEvent, PlatformError]:
        def make() -> Generator[Effect[Any, PlatformError], Any, Stream[WatchEvent, PlatformError]]:
            info = yield from self.stat(path)
            caller = yield from service_option(WatchBackend)
            backend = option.get_or_none(caller) or self._backend
            if backend is not None:
                found = backend.register(path, info, recursive=recursive, on_ready=on_ready)
                if found is not None:
                    return found
            return poll(
                path,
                directory=info.type == "Directory",
                recursive=recursive,
                on_ready=on_ready,
                interval=self._watch_interval,
            )

        return stream_.unwrap(gen(make))

    def write_file(
        self, path: str, data: bytes, *, flag: OpenFlag = "w", mode: int = 0o666
    ) -> Effect[None, PlatformError]:
        return run("write_file", path, lambda: _write(path, data, flag, mode))


def _build(backend: option.Option[WatchBackendService]) -> FileSystemService:
    return LiveFileSystem(backend=option.get_or_none(backend))


layer: Layer[FileSystem] = layer_effect(FileSystem, service_option(WatchBackend).map(_build))
"""The host's file system, with the ``WatchBackend`` provided where the
layer is built (if any)."""
