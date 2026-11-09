"""Ports of Effect's ``FileSystem.test-utils.ts`` (the suite every platform's
file system runs) and ``NodeFileSystem.test.ts``, against
``file_system.layer``.

Each test's docstring is the Effect test title; an ``it.each`` title is one
parametrized test. Errors name pyfect's methods (``read_file`` where Effect
says ``readFile``). The ``text.txt`` fixture is written to a temporary
directory.

Omitted, with the reason:

- ``rejects stream chunkSize $chunkSize with bytesToRead $bytesToRead`` and
  ``readAlloc(1.5 | NaN | Infinity)``: sizes are ``int``; pyright rejects
  fractions, ``NaN`` and infinities at the call.
- ``NodeFileSystem precision`` (``$method rejects an unsafe position before
  writing``, ``writeAll stops when a partial write advances beyond the safe
  integer limit``, ``$method preserves oversized byte counts``, ``rejects
  unsafe mode metadata``, ``preserves metadata above MAX_SAFE_INTEGER``,
  ``interprets signed identifiers as unsigned 64-bit``, ``preserves numeric
  ownership metadata``, ``omits missing optional metadata``): they mock
  ``node:fs`` to reach JavaScript's 2**53 number limit; Python integers are
  exact, and ``tests/test_platform.py`` pins the unsigned reading of
  device numbers.
"""

import os
import sys
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

import pytest

import pyfect as fx
from pyfect import file_system, stream, testing
from pyfect.file_system import (
    Create,
    FileInfo,
    FileSystem,
    FileSystemService,
    OpenFlag,
    WatchBackend,
    WatchEvent,
)
from pyfect.platform_error import (
    AlreadyExists,
    BadArgument,
    BadResource,
    NotFound,
    PlatformError,
)
from pyfect.testing import Services

fs_layer = testing.layer_fixture(file_system.layer)

TEXT = "lorem ipsum dolar sit amet\n"


@pytest.fixture(scope="module")
def text_file(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("fixtures") / "text.txt"
    path.write_text(TEXT)
    return str(path)


def _fs() -> fx.Effect[FileSystemService, Any, FileSystem]:
    return FileSystem()


def _text(eff: fx.Effect[bytes | None, PlatformError]) -> fx.Effect[str, Any]:
    return eff.flat_map(fx.from_optional).map(bytes.decode)


def _posix(path: str) -> str:
    return path.replace("\\", "/")


@testing.effect
def test_read_file(fs_layer: Services[FileSystem], text_file: str):
    """readFile"""
    fs = yield from _fs()
    data = yield from fs.read_file(text_file)
    assert data.decode().strip() == "lorem ipsum dolar sit amet"


@testing.effect
def test_make_temp_directory(fs_layer: Services[FileSystem]):
    """makeTempDirectory"""
    fs = yield from _fs()

    @fx.fn
    def make():
        directory = yield from fs.make_temp_directory()
        assert (yield from fs.stat(directory)).type == "Directory"
        return directory

    directory = yield from fx.scoped(make())
    assert (yield from fs.stat(directory)).type == "Directory"
    yield from fs.remove(directory, recursive=True)


@testing.effect
def test_make_temp_directory_scoped(fs_layer: Services[FileSystem]):
    """makeTempDirectoryScoped"""
    fs = yield from _fs()

    @fx.fn
    def make():
        directory = yield from fs.make_temp_directory_scoped()
        assert (yield from fs.stat(directory)).type == "Directory"
        return directory

    directory = yield from fx.scoped(make())
    error = yield from fs.stat(directory).flip()
    assert isinstance(error.reason, NotFound)


@testing.effect
def test_lstat_does_not_follow_symbolic_links(fs_layer: Services[FileSystem]):
    """lstat does not follow symbolic links"""
    fs = yield from _fs()
    directory = yield from fs.make_temp_directory_scoped()
    link = f"{directory}/link"
    yield from fs.write_file_string(f"{directory}/target", "")
    yield from fs.symlink(f"{directory}/target", link)
    assert (yield from fs.stat(link)).type == "File"
    assert (yield from fs.lstat(link)).type == "SymbolicLink"


@testing.effect
def test_access_on_a_writable_directory(fs_layer: Services[FileSystem]):
    """access on a writable directory"""
    fs = yield from _fs()
    directory = yield from fs.make_temp_directory_scoped()
    yield from fs.access(directory, writable=True)


@testing.effect
def test_make_temp_file_scoped_cleans_up(fs_layer: Services[FileSystem]):
    """makeTempFileScoped cleans up"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()

    @fx.fn
    def make():
        file = yield from fs.make_temp_file_scoped(directory=root)
        directory = os.path.dirname(file)
        assert directory
        assert (yield from fs.stat(directory)).type == "Directory"
        return file, directory

    file, directory = yield from fx.scoped(make())
    assert isinstance((yield from fs.stat(file).flip()).reason, NotFound)
    assert isinstance((yield from fs.stat(directory).flip()).reason, NotFound)


@testing.effect
def test_truncate(fs_layer: Services[FileSystem]):
    """truncate"""
    fs = yield from _fs()
    file = yield from fs.make_temp_file()
    yield from fs.write_file(file, b"hello world")
    assert (yield from fs.read_file_string(file)) == "hello world"

    yield from fs.truncate(file, 5)
    assert (yield from fs.read_file_string(file)) == "hello"

    yield from fs.truncate(file)
    assert (yield from fs.read_file_string(file)) == ""
    yield from fs.remove(os.path.dirname(file), recursive=True)


@testing.effect
def test_write_file_with_r_plus_overwrites_without_truncating(fs_layer: Services[FileSystem]):
    """writeFile with r+ overwrites without truncating"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    yield from fs.write_file_string(path, "abcdef")
    yield from fs.write_file_string(path, "xy", flag="r+")
    assert (yield from fs.read_file_string(path)) == "xycdef"


@testing.effect
def test_write_file_with_empty_data_honors_the_flag(fs_layer: Services[FileSystem]):
    """writeFile with empty data honors the flag"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()

    yield from fs.write_file_string(path, "abc")
    yield from fs.write_file_string(path, "")
    assert (yield from fs.read_file_string(path)) == ""

    yield from fs.write_file_string(path, "abc")
    yield from fs.write_file_string(path, "", flag="r+")
    assert (yield from fs.read_file_string(path)) == "abc"


@testing.effect
def test_write_file_with_r_rejects_writes(fs_layer: Services[FileSystem]):
    """writeFile with r rejects writes"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()

    error = yield from fs.write_file_string(path, "data", flag="r").flip()

    assert not isinstance(error.reason, BadArgument)
    assert error.reason.method == "write_file"
    assert error.reason.path_or_descriptor == path
    assert (yield from fs.read_file_string(path)) == ""


@testing.effect
def test_write_file_with_a_appends(fs_layer: Services[FileSystem]):
    """writeFile with a appends"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    yield from fs.write_file_string(path, "abc")
    yield from fs.write_file_string(path, "def", flag="a")
    assert (yield from fs.read_file_string(path)) == "abcdef"


@testing.effect
def test_write_file_with_wx_exclusively_creates(fs_layer: Services[FileSystem]):
    """writeFile with wx exclusively creates"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    path = f"{root}/file.txt"

    yield from fs.write_file_string(path, "first", flag="wx")
    yield from fs.write_file_string(path, "second", flag="wx").flip()

    assert (yield from fs.read_file_string(path)) == "first"


@testing.effect
def test_copy_with_overwrite_false_preserves_an_existing_destination(
    fs_layer: Services[FileSystem],
):
    """copy with overwrite false preserves an existing destination"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    source = f"{root}/source.txt"
    destination = f"{root}/destination.txt"
    yield from fs.write_file_string(source, "source")
    yield from fs.write_file_string(destination, "destination")

    result = yield from fs.copy(source, destination, overwrite=False).result()

    if isinstance(result, fx.Err):
        assert isinstance(result.error.reason, AlreadyExists)
        assert result.error.reason.method == "copy"
        assert result.error.reason.path_or_descriptor == source
    assert (yield from fs.read_file_string(source)) == "source"
    assert (yield from fs.read_file_string(destination)) == "destination"


@testing.effect
def test_should_track_the_cursor_position_when_reading(
    fs_layer: Services[FileSystem], text_file: str
):
    """should track the cursor position when reading"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)

    assert (yield from _text(file.read_alloc(5))) == "lorem"
    yield from file.seek(7, "current")
    assert (yield from _text(file.read_alloc(5))) == "dolar"
    yield from file.seek(1, "current")
    assert (yield from _text(file.read_alloc(8))) == "sit amet"
    yield from file.seek(0, "start")
    assert (yield from _text(file.read_alloc(11))) == "lorem ipsum"

    chunks = yield from fs.stream(text_file, offset=6, bytes_to_read=5).run_collect()
    assert b"".join(chunks).decode() == "ipsum"


@testing.effect
def test_should_return_a_numeric_byte_count_when_reading(
    fs_layer: Services[FileSystem], text_file: str
):
    """should return a numeric byte count when reading"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    buffer = bytearray(5)

    assert (yield from file.read(buffer)) == 5
    assert buffer.decode() == "lorem"


@testing.effect
def test_should_read_from_a_backwards_seek(fs_layer: Services[FileSystem], text_file: str):
    """should read from a backwards seek"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)

    assert (yield from _text(file.read_alloc(5))) == "lorem"
    yield from file.seek(-3, "current")
    assert (yield from _text(file.read_alloc(3))) == "rem"


@pytest.mark.parametrize(
    ("offset", "whence"), [(-1, "start"), (-3, "start"), (-6, "current"), (-8, "current")]
)
@testing.effect
def test_should_reject_seeks_before_the_start_of_the_file(
    fs_layer: Services[FileSystem],
    text_file: str,
    offset: int,
    whence: Literal["start", "current"],
):
    """should reject seeks before the start of the file ($offset from $from)"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    buffer = bytearray(5)
    assert (yield from file.read(buffer)) == 5
    assert buffer.decode() == "lorem"

    error = yield from file.seek(offset, whence).flip()
    assert isinstance(error.reason, BadArgument)
    assert (error.reason.module, error.reason.method) == ("FileSystem", "seek")

    assert (yield from file.seek(0, "current")) == 5
    assert (yield from file.read(buffer)) == 5
    assert buffer.decode() == " ipsu"
    assert (yield from file.seek(0, "current")) == 10

    assert (yield from file.seek(-10, "current")) == 0
    assert (yield from file.read(buffer)) == 5
    assert buffer.decode() == "lorem"


@pytest.mark.parametrize("size", [-1, int(sys.float_info.max)], ids=["-1", "MAX_VALUE"])
@testing.effect
def test_read_alloc_fails_with_bad_argument_without_moving_the_cursor(
    fs_layer: Services[FileSystem], text_file: str, size: int
):
    """readAlloc(%s) fails with BadArgument without moving the cursor"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    assert (yield from _text(file.read_alloc(6))) == "lorem "

    error = yield from file.read_alloc(size).flip()
    position = yield from file.seek(0, "current")
    following = yield from _text(file.read_alloc(5))

    assert position == 6
    assert following == "ipsum"
    assert isinstance(error.reason, BadArgument)
    assert (error.reason.module, error.reason.method) == ("FileSystem", "read_alloc")


@testing.effect
def test_read_alloc_0_returns_none_without_moving_the_cursor(
    fs_layer: Services[FileSystem], text_file: str
):
    """readAlloc(0) returns None without moving the cursor"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    assert (yield from _text(file.read_alloc(6))) == "lorem "

    assert (yield from file.read_alloc(0)) is None
    assert (yield from file.seek(0, "current")) == 6
    assert (yield from _text(file.read_alloc(5))) == "ipsum"


@testing.effect
def test_should_read_sequentially_without_an_intervening_seek(
    fs_layer: Services[FileSystem], text_file: str
):
    """should read sequentially without an intervening seek"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    assert (yield from _text(file.read_alloc(5))) == "lorem"
    assert (yield from _text(file.read_alloc(6))) == " ipsum"


@testing.effect
def test_should_track_the_cursor_position_when_writing(fs_layer: Services[FileSystem]):
    """should track the cursor position when writing"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="w+")

    assert (yield from file.write(b"lorem ipsum")) == 11
    yield from file.write(b" ")
    yield from file.write(b"dolor sit amet")
    assert (yield from fs.read_file_string(path)) == "lorem ipsum dolor sit amet"

    yield from file.seek(-4, "current")
    yield from file.write(b"hello world")
    assert (yield from fs.read_file_string(path)) == "lorem ipsum dolor sit hello world"

    yield from file.seek(6, "start")
    yield from file.write(b"blabl")
    assert (yield from fs.read_file_string(path)) == "lorem blabl dolor sit hello world"


@testing.effect
def test_should_maintain_a_read_cursor_in_append_mode(fs_layer: Services[FileSystem]):
    """should maintain a read cursor in append mode"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="a+")

    yield from file.write(b"foo")
    yield from file.seek(0, "start")
    yield from file.write(b"bar")
    assert (yield from fs.read_file_string(path)) == "foobar"

    assert (yield from _text(file.read_alloc(3))) == "foo"
    yield from file.write(b"baz")
    assert (yield from fs.read_file_string(path)) == "foobarbaz"
    assert (yield from _text(file.read_alloc(6))) == "barbaz"


@testing.effect
def test_should_restore_the_read_cursor_after_an_append_write(fs_layer: Services[FileSystem]):
    """should restore the read cursor after an append write"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="a+")

    yield from file.write(b"foo")
    yield from file.seek(0, "start")
    assert (yield from _text(file.read_alloc(1))) == "f"
    yield from file.write(b"bar")
    assert (yield from _text(file.read_alloc(2))) == "oo"


@testing.effect
def test_should_keep_the_current_cursor_if_truncating_doesnt_affect_it(
    fs_layer: Services[FileSystem],
):
    """should keep the current cursor if truncating doesn't affect it"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="w+")

    yield from file.write(b"lorem ipsum dolor sit amet")
    yield from file.seek(6, "start")
    yield from file.truncate(11)
    assert (yield from file.seek(0, "current")) == 6


@testing.effect
def test_should_update_the_current_cursor_if_truncating_affects_it(
    fs_layer: Services[FileSystem],
):
    """should update the current cursor if truncating affects it"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="w+")

    yield from file.write(b"lorem ipsum dolor sit amet")
    yield from file.truncate(11)
    assert (yield from file.seek(0, "current")) == 11


@testing.effect
def test_should_read_from_the_clamped_cursor_after_truncating(fs_layer: Services[FileSystem]):
    """should read from the clamped cursor after truncating"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="w+")

    yield from file.write(b"abcdefghij")
    yield from file.truncate(5)
    yield from fs.write_file(path, b"xyz", flag="a")
    assert (yield from _text(file.read_alloc(3))) == "xyz"


@testing.effect
def test_no_follow_rejects_symlinks_or_fails_explicitly_when_unsupported(
    fs_layer: Services[FileSystem],
):
    """noFollow rejects symlinks or fails explicitly when unsupported"""
    fs = yield from _fs()
    directory = yield from fs.make_temp_directory_scoped()
    path = f"{directory}/target"
    yield from fs.write_file_string(path, "target")
    supported = os.name != "nt"
    if supported:
        yield from fs.open(path, no_follow=True)
        yield from fs.symlink(path, f"{directory}/link")
    error = yield from fs.open(
        path if not supported else f"{directory}/link", no_follow=True
    ).flip()
    assert isinstance(error.reason, BadResource if supported else BadArgument)


@testing.effect
def test_concurrent_positional_reads_preserve_the_cursor(
    fs_layer: Services[FileSystem], text_file: str
):
    """concurrent positional reads preserve the cursor"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    yield from file.seek(6, "start")
    buffer = bytearray(5)
    count, allocated = yield from fx.all(
        file.read(buffer, position=12),
        _text(file.read_alloc(4, position=18)),
        concurrency="unbounded",
    )
    assert count == 5
    assert buffer.decode() == "dolar"
    assert allocated == "sit "
    assert (yield from _text(file.read_alloc(5))) == "ipsum"


@pytest.mark.parametrize("method", ["read", "read_alloc"])
@testing.effect
def test_rejects_a_negative_position(
    fs_layer: Services[FileSystem], text_file: str, method: Literal["read", "read_alloc"]
):
    """%s rejects a negative position"""
    fs = yield from _fs()
    file = yield from fs.open(text_file)
    attempt = (
        file.read(bytearray(1), position=-1).as_(None)
        if method == "read"
        else file.read_alloc(1, position=-1).as_(None)
    )
    error = yield from attempt.flip()
    assert isinstance(error.reason, BadArgument)
    assert error.reason.method == method


@testing.effect
def test_make_directory_requires_parents_unless_recursive(fs_layer: Services[FileSystem]):
    """makeDirectory requires parents unless recursive"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    directory = f"{root}/a/b"
    file = f"{root}/file"

    error = yield from fs.make_directory(directory).flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("make_directory", directory)
    yield from fs.make_directory(directory, recursive=True)
    yield from fs.make_directory(directory, recursive=True)
    error = yield from fs.make_directory(directory).flip()
    assert isinstance(error.reason, AlreadyExists)
    assert error.reason.path_or_descriptor == directory

    yield from fs.write_file_string(file, "content")
    error = yield from fs.make_directory(file, recursive=True).flip()
    assert isinstance(error.reason, AlreadyExists)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("make_directory", file)


@testing.effect
def test_remove_requires_recursive_for_non_empty_directories_and_force_for_missing_paths(
    fs_layer: Services[FileSystem],
):
    """remove requires recursive for non-empty directories and force for missing paths"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    directory = f"{root}/directory"
    file = f"{root}/file"
    yield from fs.make_directory(directory)
    yield from fs.write_file_string(f"{directory}/file", "content")
    yield from fs.write_file_string(file, "content")

    error = yield from fs.remove(directory).flip()
    assert not isinstance(error.reason, BadArgument)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("remove", directory)
    yield from fs.remove(f"{directory}/", recursive=True)
    assert not (yield from fs.exists(directory))

    error = yield from fs.remove(directory).flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("remove", directory)
    yield from fs.remove(directory, force=True)

    yield from fs.remove(f"{file}/").flip()
    assert (yield from fs.read_file_string(file)) == "content"


@testing.effect
def test_copy_duplicates_directory_trees_and_replaces_files_when_overwrite_is_true(
    fs_layer: Services[FileSystem],
):
    """copy duplicates directory trees and replaces files when overwrite is true"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    source = f"{root}/source"
    destination = f"{root}/destination.txt"
    yield from fs.make_directory(f"{source}/nested", recursive=True)
    yield from fs.write_file_string(f"{source}/nested/file.txt", "source")
    yield from fs.write_file_string(destination, "destination")

    yield from fs.copy(source, f"{root}/copy/")
    yield from fs.copy(f"{source}/nested/file.txt", destination, overwrite=True)
    yield from fs.write_file_string(f"{source}/nested/file.txt", "changed")

    assert (yield from fs.read_file_string(f"{root}/copy/nested/file.txt")) == "source"
    assert (yield from fs.read_file_string(destination)) == "source"

    missing = f"{root}/missing"
    error = yield from fs.copy(missing, destination, overwrite=True).flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("copy", missing)
    assert (yield from fs.read_file_string(destination)) == "source"


@testing.effect
def test_rename_moves_directories_and_replaces_existing_files(fs_layer: Services[FileSystem]):
    """rename moves directories and replaces existing files"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    yield from fs.make_directory(f"{root}/source")
    yield from fs.write_file_string(f"{root}/source/file.txt", "content")
    yield from fs.write_file_string(f"{root}/existing.txt", "existing")

    yield from fs.rename(f"{root}/source/", f"{root}/moved/")
    yield from fs.rename(f"{root}/moved/file.txt", f"{root}/existing.txt")

    assert not (yield from fs.exists(f"{root}/source"))
    assert not (yield from fs.exists(f"{root}/moved/file.txt"))
    assert (yield from fs.read_file_string(f"{root}/existing.txt")) == "content"

    missing = f"{root}/missing"
    error = yield from fs.rename(missing, f"{root}/existing.txt").flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("rename", missing)
    assert (yield from fs.read_file_string(f"{root}/existing.txt")) == "content"


class _FlagCase(NamedTuple):
    flag: OpenFlag
    initial: str | None
    creates: bool
    readable: bool
    writable: bool
    expected: str


_FLAGS = [
    _FlagCase("r", "seed", False, True, False, "seed"),
    _FlagCase("r+", "seed", False, True, True, "xeed"),
    _FlagCase("w", "", True, False, True, "x"),
    _FlagCase("wx", None, True, False, True, "x"),
    _FlagCase("w+", "", True, True, True, "x"),
    _FlagCase("wx+", None, True, True, True, "x"),
    _FlagCase("a", "seed", True, False, True, "seedx"),
    _FlagCase("ax", None, True, False, True, "x"),
    _FlagCase("a+", "seed", True, True, True, "seedx"),
    _FlagCase("ax+", None, True, True, True, "x"),
]


@pytest.mark.parametrize("case", _FLAGS, ids=[case.flag for case in _FLAGS])
@testing.effect
def test_open_with_the_flag(fs_layer: Services[FileSystem], case: _FlagCase):
    """open with the $flag flag"""
    flag, initial, creates, readable, writable, expected = case
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    existing = f"{root}/existing"
    missing = f"{root}/missing"
    yield from fs.write_file_string(existing, "seed")

    if initial is None:
        error = yield from fs.open(existing, flag=flag).flip()
        assert isinstance(error.reason, AlreadyExists)
        assert (error.reason.method, error.reason.path_or_descriptor) == ("open", existing)
    if not creates:
        error = yield from fs.open(missing, flag=flag).flip()
        assert isinstance(error.reason, NotFound)
        assert (error.reason.method, error.reason.path_or_descriptor) == ("open", missing)

    path = missing if initial is None else existing
    file = yield from fs.open(path, flag=flag)
    assert (yield from fs.read_file_string(path)) == (initial or "")

    write = yield from file.write_all(b"x").result()
    assert isinstance(write, fx.Ok) == writable
    assert (yield from fs.read_file_string(path)) == expected

    yield from file.seek(0, "start")
    read = yield from file.read_alloc(1).result()
    assert isinstance(read, fx.Ok) == readable


@testing.effect
def test_normalizes_not_found_errors_for_missing_paths(fs_layer: Services[FileSystem]):
    """normalizes NotFound errors for missing paths"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    missing = f"{root}/missing"
    destination = f"{root}/destination"
    operations: dict[str, fx.Effect[object, PlatformError]] = {
        "access": fs.access(missing),
        "chmod": fs.chmod(missing, 0o600),
        "chown": fs.chown(missing, 0, 0),
        "copy": fs.copy(missing, destination),
        "copy_file": fs.copy_file(missing, destination),
        "link": fs.link(missing, destination),
        "read_directory": fs.read_directory(missing),
        "read_file": fs.read_file(missing),
        "read_link": fs.read_link(missing),
        "real_path": fs.real_path(missing),
        "stat": fs.stat(missing),
        "truncate": fs.truncate(missing),
    }
    for method, operation in operations.items():
        error = yield from operation.flip()
        assert isinstance(error.reason, NotFound), method
        assert (error.reason.method, error.reason.path_or_descriptor) == (method, missing)


@testing.effect
def test_reports_bad_resource_when_a_file_is_used_as_a_directory(fs_layer: Services[FileSystem]):
    """reports BadResource when a file is used as a directory"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    file = f"{root}/file"
    child = f"{file}/child"
    yield from fs.write_file_string(file, "content")

    cases: list[tuple[str, str, fx.Effect[object, PlatformError]]] = [
        ("read_directory", file, fs.read_directory(file)),
        ("write_file", child, fs.write_file_string(child, "child")),
        ("stat", child, fs.stat(child)),
    ]
    for method, path, operation in cases:
        error = yield from operation.flip()
        assert isinstance(error.reason, BadResource), method
        assert (error.reason.method, error.reason.path_or_descriptor) == (method, path)
    assert (yield from fs.read_file_string(file)) == "content"


@testing.effect
def test_zero_fills_files_extended_by_truncate_or_writes_past_the_end(
    fs_layer: Services[FileSystem],
):
    """zero-fills files extended by truncate or writes past the end"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    yield from fs.write_file_string(path, "abc")

    yield from fs.truncate(path, 4)
    assert (yield from fs.read_file(path)) == b"abc\0"

    file = yield from fs.open(path, flag="r+")
    yield from file.truncate(5)
    assert (yield from fs.read_file(path)) == b"abc\0\0"

    yield from file.seek(6, "start")
    yield from file.write_all(bytes([42]))
    assert (yield from fs.read_file(path)) == b"abc\0\0\0*"


@testing.effect
def test_scoped_temporary_resources_honor_prefixes_and_are_removed_when_the_scope_fails(
    fs_layer: Services[FileSystem],
):
    """scoped temporary resources honor prefixes and are removed when the scope fails"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    made: dict[str, str] = {}

    @fx.fn
    def failing():
        made["directory"] = yield from fs.make_temp_directory_scoped(
            directory=root, prefix="directory-"
        )
        made["file"] = yield from fs.make_temp_file_scoped(
            directory=root, prefix="file-", suffix=".txt"
        )
        yield from fs.write_file_string(f"{made['directory']}/file.txt", "content")
        return (yield from fx.fail("boom"))

    error = yield from fx.scoped(failing()).flip()

    assert error == "boom"
    assert _posix(made["directory"]).startswith(f"{_posix(root)}/directory-")
    assert _posix(made["file"]).startswith(f"{_posix(root)}/file-")
    assert made["file"].endswith(".txt")
    assert not (yield from fs.exists(made["directory"]))
    assert not (yield from fs.exists(made["file"]))


@testing.effect
def test_stream_emits_nothing_past_the_end_and_reports_open_failures(
    fs_layer: Services[FileSystem],
):
    """stream emits nothing past the end and reports open failures"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    empty = f"{root}/empty"
    populated = f"{root}/populated"
    missing = f"{root}/missing"
    yield from fs.write_file_string(empty, "")
    yield from fs.write_file_string(populated, "content")

    assert (yield from fs.stream(empty).run_collect()) == []
    assert (yield from fs.stream(populated, offset=20).run_collect()) == []
    error = yield from fs.stream(missing).run_drain().flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("open", missing)


@testing.effect
def test_sink_truncates_by_default_and_appends_with_the_a_flag(fs_layer: Services[FileSystem]):
    """sink truncates by default and appends with the a flag"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    yield from fs.write_file_string(path, "old content")

    yield from stream.make(b"new").run(fs.sink(path))
    assert (yield from fs.read_file_string(path)) == "new"

    yield from stream.make(b" appended").run(fs.sink(path, flag="a"))
    assert (yield from fs.read_file_string(path)) == "new appended"


@testing.effect
def test_link_and_symlink_resolve_to_the_target_file(fs_layer: Services[FileSystem]):
    """link and symlink resolve to the target file"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    target = f"{root}/target"
    hard = f"{root}/hard"
    relative = f"{root}/relative"
    absolute = f"{root}/absolute"
    loop = f"{root}/loop-a"
    yield from fs.write_file_string(target, "content")

    yield from fs.link(target, hard)
    yield from fs.write_file_string(hard, "linked")
    assert (yield from fs.read_file_string(target)) == "linked"

    yield from fs.symlink("target", relative)
    yield from fs.symlink(target, absolute)
    assert (yield from fs.read_link(relative)) == "target"
    assert (yield from fs.read_link(absolute)) == target
    assert (yield from fs.real_path(relative)) == (yield from fs.real_path(target))
    assert (yield from fs.real_path(absolute)) == (yield from fs.real_path(target))
    assert (yield from fs.read_file_string(relative)) == "linked"

    yield from fs.symlink("loop-b", loop)
    yield from fs.symlink("loop-a", f"{root}/loop-b")
    error = yield from fs.real_path(loop).flip()
    assert not isinstance(error.reason, BadArgument)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("real_path", loop)


@testing.effect
def test_utimes_sets_timestamps_and_copy_with_preserve_timestamps_keeps_mtime(
    fs_layer: Services[FileSystem],
):
    """utimes sets timestamps and copy with preserveTimestamps keeps mtime"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    source = f"{root}/source"
    destination = f"{root}/destination"
    atime = datetime(2001, 2, 3, 4, 5, 6, tzinfo=UTC)
    mtime = datetime(2002, 3, 4, 5, 6, 7, tzinfo=UTC)
    yield from fs.write_file_string(source, "content")

    yield from fs.utimes(source, atime, mtime)
    info = yield from fs.stat(source)
    assert info.atime == atime
    assert info.mtime == mtime

    yield from fs.copy(source, destination, preserve_timestamps=True)
    assert (yield from fs.stat(destination)).mtime == mtime


@testing.effect
def test_glob_honors_exclude_patterns(fs_layer: Services[FileSystem]):
    """glob honors exclude patterns"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    yield from fs.make_directory(f"{root}/src")
    yield from fs.write_file_string(f"{root}/src/index.ts", "")
    yield from fs.write_file_string(f"{root}/src/index.test.ts", "")
    yield from fs.write_file_string(f"{root}/src/readme.md", "")

    matches = yield from fs.glob("**/*.ts", root=root, exclude=("**/*.test.ts",))

    assert len(matches) == 1
    assert _posix(matches[0]).endswith("src/index.ts")


# --- NodeFileSystem.test.ts -------------------------------------------------------------

_READY = ".watch-ready"


def _start_watch(
    fs: FileSystemService, root: str, watch: fx.Stream[WatchEvent, PlatformError]
) -> fx.Effect[fx.Fiber[WatchEvent, Any], Any]:
    """Run ``watch`` until its first event after the watcher is seen to be
    live (it reports a marker file written every 10ms)."""

    @fx.fn
    def start():
        ready = yield from fx.Deferred[None].make()
        fiber = yield from (
            watch.tap(lambda event: ready.succeed(None) if event.path == _READY else fx.void)
            .drop_until(lambda event: event.path == _READY)
            .filter(lambda event: event.path != _READY)
            .run_head()
            .flat_map(fx.from_option)
            .fork()
        )
        signal = yield from testing.with_live(
            fx.sleep("10 millis").and_then(fs.write_file_string(f"{root}/{_READY}", "")).forever()
        ).fork()
        yield from ready.wait().race_first(fiber.join().as_(None)).ensuring(signal.interrupt())
        return fiber

    return start()


@testing.effect
def test_real_path_resolves_a_directory_alias_to_its_physical_target(
    fs_layer: Services[FileSystem],
):
    """realPath resolves a directory alias to its physical target"""
    fs = yield from _fs()
    root = yield from fs.real_path((yield from fs.make_temp_directory_scoped()))
    target = os.path.join(root, "target")
    alias = os.path.join(root, "alias")
    yield from fs.make_directory(target)
    os.symlink(target, alias, target_is_directory=True)
    assert (yield from fs.real_path(alias)) == target


@testing.effect
def test_write_all_accepts_an_empty_buffer(fs_layer: Services[FileSystem]):
    """writeAll accepts an empty buffer"""
    fs = yield from _fs()
    path = yield from fs.make_temp_file_scoped()
    file = yield from fs.open(path, flag="r+")
    yield from file.write_all(b"")


@testing.effect
def test_watch_reports_create_for_a_new_file_outside_the_current_directory(
    fs_layer: Services[FileSystem],
):
    """watch reports Create for a new file outside the current directory"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    name = "created.txt"
    path = f"{root}/{name}"
    assert not (yield from fs.exists(name))

    fiber = yield from _start_watch(fs, root, fs.watch(root))
    yield from fs.write_file_string(path, "")

    event = yield from fiber.join()
    assert (yield from fs.exists(path))
    assert event == Create(name)


@testing.effect
def test_watch_does_not_report_nested_changes_when_recursive_is_false(
    fs_layer: Services[FileSystem],
):
    """watch does not report nested changes when recursive is false"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    nested = f"{root}/nested"
    yield from fs.make_directory(nested)

    fiber = yield from _start_watch(fs, root, fs.watch(root, recursive=False))
    yield from fs.write_file_string(f"{nested}/nested.txt", "")
    yield from fs.write_file_string(f"{root}/direct.txt", "")

    assert (yield from fiber.join()).path == "direct.txt"


@testing.effect
def test_watch_is_non_recursive_when_options_are_omitted(fs_layer: Services[FileSystem]):
    """watch is non-recursive when options are omitted"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    nested = f"{root}/nested"
    yield from fs.make_directory(nested)

    fiber = yield from _start_watch(fs, root, fs.watch(root))
    yield from fs.write_file_string(f"{nested}/nested.txt", "")
    yield from fs.write_file_string(f"{root}/direct.txt", "")

    assert (yield from fiber.join()).path == "direct.txt"


class _Backend:
    def __init__(self, event: WatchEvent) -> None:
        self.event = event

    def register(
        self, path: str, info: FileInfo, *, recursive: bool, on_ready: object
    ) -> fx.Stream[WatchEvent, PlatformError]:
        return stream.make(self.event)


@testing.effect
def test_watch_uses_a_watch_backend_provided_after_the_layer_is_built(
    fs_layer: Services[FileSystem],
):
    """watch uses a WatchBackend provided after the layer is built"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    backend_event = Create("from-backend")
    event = yield from testing.with_live(
        fs.watch(root)
        .run_head()
        .pipe(fx.provide_service(WatchBackend, _Backend(backend_event)))
        .timeout("1 second")
    )
    assert event == fx.Some(backend_event)


def test_watch_prefers_the_caller_watch_backend_over_the_construction_backend(tmp_path: Path):
    """watch prefers the caller WatchBackend over the construction backend"""
    caller_event = Create("from-caller")

    @fx.fn
    def program() -> Generator[fx.Effect[Any, Any, Any], Any, Any]:
        fs = yield from _fs()
        return (
            yield from fs.watch(str(tmp_path))
            .run_head()
            .pipe(fx.provide_service(WatchBackend, _Backend(caller_event)))
        )

    construction = _Backend(Create("from-construction"))
    event = fx.run_blocking(
        program()
        .pipe(fx.provide(file_system.layer))
        .pipe(fx.provide_service(WatchBackend, construction))
    )
    assert event == fx.Some(caller_event)


@testing.effect
def test_watch_reports_nested_changes_when_recursive_is_true(fs_layer: Services[FileSystem]):
    """watch reports nested changes when recursive is true"""
    fs = yield from _fs()
    root = yield from fs.make_temp_directory_scoped()
    nested = f"{root}/nested"
    yield from fs.make_directory(nested)

    fiber = yield from _start_watch(fs, root, fs.watch(root, recursive=True))
    yield from fs.write_file_string(f"{nested}/nested.txt", "")

    assert (yield from fiber.join()).path.endswith("nested.txt")
