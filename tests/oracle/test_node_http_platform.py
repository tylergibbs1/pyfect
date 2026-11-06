"""Ports of platform-node's ``NodeHttpPlatform.test.ts`` against
``http.platform.layer_live`` (the live file system, strong ETags). Each
test's docstring is the Effect test title. The precision cases record
the file system's ``stream`` calls where Node mocks ``createReadStream``."""

from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect.byte_size import ByteSize
from pyfect.file_system import FileInfo, NoopFileSystem, layer_noop
from pyfect.http import platform
from pyfect.http.file_like import BytesFile
from pyfect.http.platform import HttpPlatform
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.wire import to_wire
from pyfect.platform_error import PlatformError
from pyfect.stream import Stream
from pyfect.stream import empty as empty_stream

TEXT = str(Path(__file__).parent / "fixtures" / "node-http-server" / "text.txt")
OVERSIZED = 9007199254740993
MAX_SAFE = 2**53 - 1


def _read(response: HttpServerResponse) -> fx.Effect[str, Any]:
    body = to_wire(response).body
    if body is None:
        return effect.succeed("")
    if isinstance(body, bytes):
        return effect.succeed(body.decode())
    return body.run_collect().map(lambda chunks: b"".join(chunks).decode())


def _run[A](
    eff: fx.Effect[A, Any, Any], provided: fx.Layer[Any, Any, Any] = platform.layer_live
) -> A:
    provide: Any = fx.provide(provided)
    return fx.run_blocking(provide(eff).or_die())


def _file(path: str, **options: Any) -> fx.Effect[HttpServerResponse, PlatformError, Any]:
    return HttpPlatform().flat_map(lambda service: service.file_response(path, **options))


def _file_web(file: Any) -> fx.Effect[HttpServerResponse, Any, Any]:
    return HttpPlatform().flat_map(lambda service: service.file_web_response(file))


def test_file_web_response_prefers_file_type_over_the_extension() -> None:
    """fileWebResponse prefers File.type over the extension"""
    response = _run(_file_web(BytesFile(b"", "script.js", "application/custom")))
    assert response.headers["content-type"] == "application/custom"


def test_file_response_reads_exact_bytes_to_read() -> None:
    """fileResponse reads exact bytesToRead"""

    @fx.fn
    def program():
        response = yield from _file(TEXT, offset=ByteSize(6), bytes_to_read=ByteSize(5))
        return response, (yield from _read(response))

    response, text = _run(program())
    assert response.headers["content-length"] == "5"
    assert response.headers["content-type"] == "text/plain"
    assert text == "ipsum"


@pytest.mark.parametrize(
    ("name", "offset", "bytes_to_read", "expected"),
    [
        ("clamps bytesToRead beyond EOF", 22, 100, "amet\n"),
        ("returns an empty body at EOF", 27, None, ""),
        ("returns an empty body past EOF", 50, None, ""),
        ("clamps bytesToRead at EOF", 27, 100, ""),
        ("clamps bytesToRead past EOF", 50, 100, ""),
    ],
)
def test_file_response(name: str, offset: int, bytes_to_read: int | None, expected: str) -> None:
    """fileResponse ${name}"""
    options: dict[str, Any] = {"offset": ByteSize(offset)}
    if bytes_to_read is not None:
        options["bytes_to_read"] = ByteSize(bytes_to_read)

    @fx.fn
    def program():
        response = yield from _file(TEXT, **options)
        return response.headers["content-length"], (yield from _read(response))

    assert _run(program()) == (str(len(expected)), expected)


def test_file_response_supports_zero_bytes_to_read() -> None:
    """fileResponse supports zero bytesToRead"""

    @fx.fn
    def program():
        response = yield from _file(TEXT, offset=ByteSize(6), bytes_to_read=ByteSize(0))
        return response.headers["content-length"], (yield from _read(response))

    assert _run(program()) == ("0", "")


def test_file_web_response_looks_up_content_types_case_insensitively() -> None:
    """fileWebResponse looks up content types case-insensitively"""
    response = _run(_file_web(BytesFile(b"<h1>Effect</h1>", "INDEX.HTML")))
    assert response.headers["content-type"] == "text/html"


class _Recording(NoopFileSystem):
    """Every file is ``OVERSIZED`` bytes; ``stream`` calls are recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int | None]] = []

    def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
        del path
        return effect.succeed(
            FileInfo(
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
                size=ByteSize(OVERSIZED),
                blksize=None,
                blocks=None,
            )
        )

    def stream(
        self, path: str, *, offset: int = 0, bytes_to_read: int | None = None, **_options: Any
    ) -> Stream[bytes, PlatformError]:
        end = None if bytes_to_read is None else offset + bytes_to_read - 1
        self.calls.append((path, offset, end))
        return empty_stream


def _precision_layer(file_system: _Recording) -> Any:
    return platform.layer_strong.pipe(layer.provide(layer_noop(file_system)))


def test_passes_a_safe_range_to_the_runtime_with_the_correct_end_bound() -> None:
    """NodeHttpPlatform precision passes a safe range to the runtime with the correct end bound"""
    file_system = _Recording()
    response = _run(
        _file("precision.bin", offset=MAX_SAFE - 1, bytes_to_read=1),
        _precision_layer(file_system),
    )
    _run(_read(response))
    assert file_system.calls == [("precision.bin", MAX_SAFE - 1, MAX_SAFE - 1)]


def test_serves_a_whole_oversized_file_with_an_exact_content_length_and_no_end_offset() -> None:
    """NodeHttpPlatform precision serves a whole oversized file with an exact content length and no end offset"""  # noqa: E501
    file_system = _Recording()
    response = _run(_file("precision.bin"), _precision_layer(file_system))
    assert response.status == 200
    assert response.headers["content-length"] == str(OVERSIZED)
    _run(_read(response))
    assert file_system.calls == [("precision.bin", 0, None)]
