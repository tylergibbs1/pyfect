"""Ports of Effect's ``http/HttpPlatform.test.ts``.

Each test's docstring is the Effect test title. Effect's ``bigint`` sizes
are ints; the safe-integer checks keep Effect's bounds (2**53 - 1).
"""

from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect.byte_size import ByteSize
from pyfect.file_system import FileInfo, NoopFileSystem, layer_noop
from pyfect.http import body, platform
from pyfect.http.file_like import BytesFile
from pyfect.http.platform import HttpPlatform
from pyfect.http.server_response import HttpServerResponse
from pyfect.platform_error import BadArgument, PlatformError
from pyfect.stream import Stream
from pyfect.stream import empty as empty_stream

OVERSIZED = 9007199254740993
MAX_SAFE = 2**53 - 1


class _Oversized(NoopFileSystem):
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
        self,
        path: str,
        *,
        offset: int = 0,
        bytes_to_read: int | None = None,
        chunk_size: int = 65536,
    ) -> Stream[bytes, PlatformError]:
        del path, offset, bytes_to_read, chunk_size
        return empty_stream


_LAYER = platform.layer.pipe(layer.provide(layer_noop(_Oversized())))
_WEB_LAYER = platform.layer.pipe(layer.provide(layer_noop()))


def _run[A](
    eff: fx.Effect[A, Any, Any], provided: fx.Layer[HttpPlatform, Never, Never] = _LAYER
) -> A:
    provide: Any = fx.provide(provided)
    return fx.run_blocking(provide(eff).or_die())


def _file_response(path: str, **options: Any) -> fx.Effect[HttpServerResponse, PlatformError, Any]:
    return HttpPlatform().flat_map(lambda service: service.file_response(path, **options))


def _file_web_response(file: Any, **options: Any) -> fx.Effect[HttpServerResponse, Any, Any]:
    return HttpPlatform().flat_map(lambda service: service.file_web_response(file, **options))


def test_file_response_infers_the_content_type_from_the_extension() -> None:
    """fileResponse infers the content type from the extension"""
    response = _run(_file_response("script.js"))
    assert response.headers["content-type"] == "text/javascript"


def test_file_response_honors_content_type_over_a_conflicting_header() -> None:
    """fileResponse honors contentType over a conflicting header"""
    response = _run(
        _file_response(
            "script.js",
            content_type="application/custom",
            headers={"content-type": "application/header"},
        )
    )
    assert response.headers["content-type"] == "application/custom"


def test_file_web_response_honors_content_type_over_the_file_type() -> None:
    """fileWebResponse honors contentType over the file type"""
    file = BytesFile(b"", "script.js", "text/plain")
    response = _run(_file_web_response(file, content_type="text/javascript"))
    assert response.headers["content-type"] == "text/javascript"


def test_serves_a_whole_oversized_file_with_an_exact_content_length_header() -> None:
    """serves a whole oversized file with an exact content-length header"""
    response = _run(_file_response("file.bin"))
    assert response.headers["content-length"] == str(OVERSIZED)


@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("unsafe bigint offset", {"offset": OVERSIZED}),
        ("unsafe end from safe bounds", {"offset": MAX_SAFE, "bytes_to_read": 2}),
        ("unsafe number offset", {"offset": MAX_SAFE + 1}),
        ("unsafe number byte count", {"bytes_to_read": MAX_SAFE + 1}),
    ],
)
def test_rejects_with_bad_argument(name: str, options: dict[str, Any]) -> None:
    """rejects ${name} with BadArgument"""
    del name
    error = _run(_file_response("file.bin", **options).flip())
    assert isinstance(error.reason, BadArgument)


_FILE = BytesFile(bytes([1, 2, 3, 4]), "file.bin", "application/octet-stream")


def _body_of(response: HttpServerResponse) -> body.Stream:
    assert isinstance(response.body, body.Stream)
    return response.body


def test_honors_web_file_offset_and_byte_count() -> None:
    """honors Web file offset and byte count"""
    response = _run(_file_web_response(_FILE, offset=1, bytes_to_read=2), _WEB_LAYER)
    streamed = _body_of(response)
    assert streamed.content_length == 2
    assert b"".join(_run(streamed.stream.run_collect(), _WEB_LAYER)) == bytes([2, 3])


@pytest.mark.parametrize(
    ("name", "offset", "bytes_to_read", "expected"),
    [
        ("clamps bytesToRead beyond EOF", 1, 10, [2, 3, 4]),
        ("returns an empty body at EOF", 4, None, []),
        ("returns an empty body past EOF", 9, None, []),
        ("clamps bytesToRead at EOF", 4, 10, []),
        ("clamps bytesToRead past EOF", 9, 10, []),
    ],
)
def test_file_web_response(
    name: str, offset: int, bytes_to_read: int | None, expected: list[int]
) -> None:
    """fileWebResponse ${name}"""
    del name
    options: dict[str, Any] = {"offset": offset}
    if bytes_to_read is not None:
        options["bytes_to_read"] = bytes_to_read
    response = _run(_file_web_response(_FILE, **options), _WEB_LAYER)
    streamed = _body_of(response)
    data = b"".join(_run(streamed.stream.run_collect(), _WEB_LAYER))
    assert (streamed.content_length, response.headers["content-length"], list(data)) == (
        len(expected),
        str(len(expected)),
        expected,
    )


def test_honors_web_file_chunk_size() -> None:
    """honors Web file chunk size"""
    response = _run(_file_web_response(_FILE, offset=0, bytes_to_read=4, chunk_size=2), _WEB_LAYER)
    streamed = _body_of(response)
    assert streamed.content_length == 4
    chunks = _run(streamed.stream.run_collect(), _WEB_LAYER)
    assert [list(chunk) for chunk in chunks] == [[1, 2], [3, 4]]


def test_keeps_the_source_chunking_by_default() -> None:
    """keeps the source chunking by default"""
    response = _run(_file_web_response(_FILE), _WEB_LAYER)
    chunks = _run(_body_of(response).stream.run_collect(), _WEB_LAYER)
    assert [list(chunk) for chunk in chunks] == [[1, 2, 3, 4]]
