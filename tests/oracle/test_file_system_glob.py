"""Ports of Effect's ``effect/test/FileSystem.test.ts``: the ``glob`` every file system
derives from ``read_directory_entries``, ``stat`` and ``read_link``, over a
fake file system whose listings report every entry as ``"Unknown"``.
Errors name pyfect's methods (``read_directory`` where Effect says
``readDirectory``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import exit as exit_
from pyfect import testing
from pyfect.byte_size import ByteSize
from pyfect.file_system import (
    DirectoryEntry,
    FileInfo,
    FileSystemService,
    FileType,
    NoopFileSystem,
)
from pyfect.latch import Latch
from pyfect.platform_error import PlatformError, SystemErrorTag, system_error

type Fx[A] = fx.Effect[A, PlatformError]


def _info(type: FileType) -> FileInfo:
    return FileInfo(
        type=type,
        mtime=None,
        atime=None,
        birthtime=None,
        dev=0,
        ino=None,
        mode=0,
        nlink=None,
        uid=None,
        gid=None,
        rdev=None,
        size=ByteSize(0),
        blksize=None,
        blocks=None,
    )


def _failure(tag: SystemErrorTag, method: str, path: str) -> PlatformError:
    return system_error(tag, module="FileSystem", method=method, path_or_descriptor=path)


class _Fake(NoopFileSystem):
    """Each directory holds the file ``x.ts``; an override returning
    ``None`` falls back to that tree. ``glob`` is the derived one, as
    ``FileSystem.make({...makeNoop({}), ...})`` gives in Effect."""

    glob = FileSystemService.glob

    def __init__(
        self,
        *,
        directories: Mapping[str, Sequence[str]] | None = None,
        read_directory: Callable[[str], Fx[list[str]] | None] = lambda _: None,
        stat: Callable[[str], Fx[FileInfo] | None] = lambda _: None,
        read_link: Callable[[str], Fx[str]] | None = None,
    ) -> None:
        self._directories = directories if directories is not None else {".": ["a"], "a": ["x.ts"]}
        self._read_directory = read_directory
        self._stat = stat
        self._read_link = read_link

    def read_directory(self, path: str, *, recursive: bool = False) -> Fx[list[str]]:
        found = self._read_directory(path)
        if found is not None:
            return found
        if path in self._directories:
            return fx.succeed(list(self._directories[path]))
        return fx.fail(_failure("NotFound", "read_directory", path))

    def read_directory_entries(self, path: str) -> Fx[tuple[DirectoryEntry, ...]]:
        return self.read_directory(path).map(
            lambda names: tuple(DirectoryEntry(name, "Unknown") for name in names)
        )

    def stat(self, path: str) -> Fx[FileInfo]:
        found = self._stat(path)
        if found is not None:
            return found
        if path in self._directories:
            return fx.succeed(_info("Directory"))
        if path.endswith("/x.ts") and path[:-5] in self._directories:
            return fx.succeed(_info("File"))
        return fx.fail(_failure("NotFound", "stat", path))

    def read_link(self, path: str) -> Fx[str]:
        if self._read_link is not None:
            return self._read_link(path)
        # Node reports EINVAL as "Unknown" for a path that is not a link
        return fx.fail(_failure("Unknown", "read_link", path))


# `secret` and `src` are named by literal pattern segments below, and `open` is only
# reached through wildcards
_PERMISSION_TREE = {
    ".": ["open", "secret", "src"],
    "open": ["x.ts"],
    "secret": ["x.ts"],
    "src": ["x.ts"],
}

# More subdirectories than glob walks in forked fibers (16), so the rest are walked
# inline by the fiber that listed them
_WIDE = [f"d{i:02}" for i in range(64)]
_WIDE_TREE: dict[str, list[str]] = {".": _WIDE, **{name: ["x.ts"] for name in _WIDE}}


def _pending_inline(d00: Fx[Any]) -> _Fake:
    """Holds the forked reads ``d00`` to ``d15`` until ``d63`` is being read
    inline. A serial walk never reaches ``d63``, so ``d00`` stops waiting
    after 200 millis."""
    inline = Latch()

    def read(path: str) -> Fx[list[str]] | None:
        index = _WIDE.index(path) if path in _WIDE else -1
        if index == 63:
            return inline.open().and_then(fx.never)
        if index == 0:
            return inline.wait().timeout_option("200 millis").and_then(d00)
        if 0 < index < 16:
            return inline.wait().and_then(fx.succeed(["x.ts"]))
        return None

    return _Fake(directories=_WIDE_TREE, read_directory=read)


@testing.effect
def test_traverses_directories_whose_read_link_reports_that_they_are_not_links():
    """traverses directories whose readLink reports that they are not links"""
    assert (yield from _Fake().glob("**")) == ["a", "a/x.ts"]


@pytest.mark.parametrize("pattern", [".", "../*", "/x"])
@testing.effect
def test_fails_when_probing_fails_unexpectedly(pattern: str):
    """fails when probing %s fails unexpectedly"""
    error = _failure("Unknown", "stat", pattern)
    fs = _Fake(stat=lambda path: fx.fail(error) if path in (".", "..", "/") else None)
    assert (yield from fs.glob(pattern).exit()) == exit_.fail(error)


@testing.effect
def test_fails_when_read_link_fails_unexpectedly():
    """fails when readLink fails unexpectedly"""
    error = _failure("Busy", "read_link", "a")
    fs = _Fake(read_link=lambda _: fx.fail(error))
    assert (yield from fs.glob("**").exit()) == exit_.fail(error)


@testing.effect
def test_propagates_defects_from_probing_stat():
    """propagates defects from probing stat"""
    fs = _Fake(stat=lambda path: fx.die(RuntimeError("boom")) if path == "." else None)
    assert (yield from fs.glob(".").exit()).has_dies


@pytest.mark.parametrize(
    ("pattern", "root"), [("**", "secret"), ("secret/**", None), ("secret/*.ts", None)]
)
@testing.effect
def test_fails_when_a_named_directory_cannot_be_read(pattern: str, root: str | None):
    """fails when a directory named by $pattern (root: $root) cannot be read"""
    error = _failure("PermissionDenied", "read_directory", "secret")
    fs = _Fake(
        directories=_PERMISSION_TREE,
        read_directory=lambda path: fx.fail(error) if path == "secret" else None,
    )
    assert (yield from fs.glob(pattern, root=root).exit()) == exit_.fail(error)


@testing.effect
def test_fails_when_stat_denies_access_to_a_leading_literal():
    """fails when stat denies access to a leading literal"""
    error = _failure("PermissionDenied", "stat", "a")
    fs = _Fake(stat=lambda path: fx.fail(error) if path == "a" else None)
    assert (yield from fs.glob("a/*.ts").exit()) == exit_.fail(error)


@testing.effect
def test_returns_an_empty_array_when_the_root_is_a_file():
    """returns an empty array when the root is a file"""
    fs = _Fake(
        read_directory=lambda path: (
            fx.fail(_failure("BadResource", "read_directory", path)) if path == "a/x.ts" else None
        )
    )
    assert (yield from fs.glob("**", root="a/x.ts")) == []


@testing.effect
def test_reads_a_literal_prefix_whose_parent_cannot_be_listed():
    """reads a literal prefix whose parent cannot be listed"""
    fs = _Fake(
        directories=_PERMISSION_TREE,
        read_directory=lambda path: (
            fx.fail(_failure("PermissionDenied", "read_directory", path)) if path == "." else None
        ),
    )
    assert (yield from fs.glob("src/*.ts")) == ["src/x.ts"]


@testing.effect
def test_skips_unreadable_directories_reached_through_wildcards():
    """skips unreadable directories reached through wildcards and missing literal prefixes"""
    fs = _Fake(
        directories=_PERMISSION_TREE,
        read_directory=lambda path: (
            fx.fail(_failure("PermissionDenied", "read_directory", path))
            if path == "secret"
            else None
        ),
    )
    assert (yield from fs.glob("*/x.ts")) == ["open/x.ts", "src/x.ts"]
    assert (yield from fs.glob("missing/**")) == []


@testing.live
def test_fails_when_a_directory_read_fails_while_another_read_is_still_pending():
    """fails when a directory read fails while another read is still pending"""
    error = _failure("Busy", "read_directory", "d00")
    fs = _pending_inline(fx.fail(error))
    assert (yield from fs.glob("**").timeout("1 second").exit()) == exit_.fail(error)


@testing.live
def test_is_interrupted_when_a_directory_read_is_interrupted_while_another_read_is_pending():
    """is interrupted when a directory read is interrupted while another read is still pending"""
    fs = _pending_inline(fx.interrupt())
    assert (yield from fs.glob("**").timeout("1 second").exit()).has_interrupts


@testing.live
def test_fails_with_an_inline_read_error_while_forked_reads_are_still_pending():
    """fails with an inline read error while forked reads are still pending"""
    error = _failure("Busy", "read_directory", "d16")
    # `d16` is read inline and fails once the forked reads `d00` to `d15` have all
    # started. Those never finish.
    forked = Latch()
    started = 0

    def start() -> None:
        nonlocal started
        started += 1
        if started == 16:
            forked.open_unsafe()

    def read(path: str) -> Fx[list[str]] | None:
        if path == "d16":
            return forked.wait().and_then(fx.fail(error))
        if path == ".":
            return None
        return fx.sync(start).and_then(fx.never)

    fs = _Fake(directories=_WIDE_TREE, read_directory=read)
    assert (yield from fs.glob("**").timeout("1 second").exit()) == exit_.fail(error)


@testing.effect
def test_propagates_defects_from_read_link():
    """propagates defects from readLink"""
    fs = _Fake(read_link=lambda _: fx.die(RuntimeError("boom")))
    assert (yield from fs.glob("**").exit()).has_dies
