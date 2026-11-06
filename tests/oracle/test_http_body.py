"""Ports of Effect's ``http/HttpBody.test.ts``.

Each test's docstring is the Effect test title. Range options are keyword
arguments; ``NoopFileSystem`` subclasses stand in for
``FileSystem.makeNoop``.

Omitted, with the reason:

- ``identifies HTTP body errors``: ``isinstance(e, HttpBodyError)`` is the
  guard.
"""

import math
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream as stream_
from pyfect.byte_size import ByteSize
from pyfect.file_system import FileInfo, FileSystem, NoopFileSystem
from pyfect.http import body
from pyfect.platform_error import PlatformError
from pyfect.stream import Stream


def _run[A](eff: fx.Effect[A, object]) -> A:
    return fx.run_blocking(eff.or_die())


MAX_SAFE = 2**53 - 1
OVERSIZED = 9007199254740993


def _info(size: int) -> FileInfo:
    return FileInfo(
        type="File",
        mtime=None,
        atime=None,
        birthtime=None,
        dev=0,
        ino=None,
        mode=0o644,
        nlink=None,
        uid=None,
        gid=None,
        rdev=None,
        size=ByteSize(size),
        blksize=None,
        blocks=None,
    )


class _EmptyStreams(NoopFileSystem):
    def stream(
        self,
        path: str,
        *,
        offset: int = 0,
        bytes_to_read: int | None = None,
        chunk_size: int = 65536,
    ) -> Stream[bytes, PlatformError]:
        return stream_.empty


def _from_info(size: int, **options: Any) -> fx.Effect[body.Stream, PlatformError]:
    return body.file_from_info("x", _info(size), **options).pipe(
        fx.provide_service(FileSystem, _EmptyStreams())
    )


@pytest.mark.parametrize(
    ("size", "options", "expected"),
    [
        pytest.param(OVERSIZED, {"offset": 2}, MAX_SAFE, id="maximum safe final length"),
        pytest.param(
            OVERSIZED + 3,
            {"offset": OVERSIZED, "bytes_to_read": 4},
            3,
            id="exact subtraction before clamping",
        ),
        pytest.param(OVERSIZED, {"bytes_to_read": 2}, 2, id="safe byte count on an oversized file"),
        pytest.param(
            6, {"bytes_to_read": OVERSIZED}, 6, id="oversized byte count clamped to a small file"
        ),
        pytest.param(6, {"offset": 6}, 0, id="offset at EOF"),
        pytest.param(6, {"offset": 7, "bytes_to_read": 2}, 0, id="offset past EOF"),
        pytest.param(OVERSIZED, {"bytes_to_read": 0}, 0, id="zero byte count"),
    ],
)
def test_file_from_info_handles(size: int, options: dict[str, Any], expected: int) -> None:
    """fileFromInfo handles $name"""
    assert _run(_from_info(size, **options)).content_length == expected


@pytest.mark.parametrize(
    ("size", "options"),
    [
        pytest.param(MAX_SAFE + 1, {}, id="first unsafe final length"),
        pytest.param(
            OVERSIZED + 3,
            {"offset": 1, "bytes_to_read": OVERSIZED},
            id="unsafe length after applying both bounds",
        ),
        pytest.param(6, {"bytes_to_read": "garbage"}, id="malformed byte count"),
        pytest.param(
            6, {"offset": -1, "bytes_to_read": 0}, id="negative offset with zero bytes requested"
        ),
        pytest.param(6, {"offset": 6, "bytes_to_read": -1}, id="negative byte count at EOF"),
        pytest.param(6, {"offset": 1.5}, id="fractional offset"),
        pytest.param(6, {"bytes_to_read": math.inf}, id="non-finite byte count"),
        pytest.param(6, {"offset": float(MAX_SAFE + 1)}, id="unsafe numeric offset"),
        pytest.param(6, {"bytes_to_read": float(MAX_SAFE + 1)}, id="unsafe numeric byte count"),
    ],
)
def test_file_from_info_rejects(size: int, options: dict[str, Any]) -> None:
    """fileFromInfo rejects $name with typed BadArgument"""
    error = _run(_from_info(size, **options).flip())
    assert error.reason.tag == "BadArgument"
    assert error.reason.method == "fileFromInfo"


@pytest.mark.parametrize("constructor", ["file", "fileFromInfo"])
def test_defers_validation(constructor: str) -> None:
    """${constructor} defers range validation and filesystem access until evaluation"""
    stat_calls = 0
    info = _info(6)

    class Fs(NoopFileSystem):
        def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
            nonlocal stat_calls
            stat_calls += 1
            return fx.succeed(info)

        def stream(
            self,
            path: str,
            *,
            offset: int = 0,
            bytes_to_read: int | None = None,
            chunk_size: int = 65536,
        ) -> Stream[bytes, PlatformError]:
            pytest.fail("invalid ranges must fail before creating a stream")

    made = (
        body.file("x", offset="garbage")
        if constructor == "file"
        else body.file_from_info("x", info, offset="garbage")
    )
    assert stat_calls == 0
    error = _run(made.pipe(fx.provide_service(FileSystem, Fs())).flip())
    assert error.reason.tag == "BadArgument"
    assert error.reason.method == constructor
    assert stat_calls == (1 if constructor == "file" else 0)


def test_file_from_info_small_range() -> None:
    """fileFromInfo preserves a small selected range and stream options"""

    class Fs(NoopFileSystem):
        def stream(
            self,
            path: str,
            *,
            offset: int = 0,
            bytes_to_read: int | None = None,
            chunk_size: int = 65536,
        ) -> Stream[bytes, PlatformError]:
            assert (path, offset, bytes_to_read, chunk_size) == ("x", 2, 2, 2)
            return stream_.succeed(bytes([3, 4]))

    made = body.file_from_info(
        "x",
        _info(6),
        offset="2 B",
        bytes_to_read=ByteSize(2),
        content_type="text/plain",
        chunk_size=2,
    ).pipe(fx.provide_service(FileSystem, Fs()))
    result = _run(made)
    data = b"".join(_run(result.stream.run_collect()))
    assert list(data) == [3, 4]
    assert result.content_length == len(data)
    assert result.content_type == "text/plain"
