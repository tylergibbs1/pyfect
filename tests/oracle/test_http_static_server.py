"""Ports of Effect's ``http/HttpStaticServer.test.ts``. Each test's
docstring is the Effect test title (with its ``describe`` prefix)."""

import asyncio
import os
import time
from collections.abc import Iterator
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, stream
from pyfect.byte_size import ByteSize
from pyfect.context import Context
from pyfect.file_system import FileInfo, FileSystem, FileType, NoopFileSystem
from pyfect.http import server_response
from pyfect.http import static_server as static
from pyfect.http.platform import Compression, HttpPlatform, HttpPlatformService
from pyfect.http.platform import layer as platform_layer
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web, to_web_handler
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError


def file_info(size: int, type: FileType = "File") -> FileInfo:
    return FileInfo(
        type=type,
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


class StatFileSystem(NoopFileSystem):
    """Every path is a file of ``size`` bytes (``/root/directory`` a
    directory), streaming no bytes."""

    def __init__(self, size: int) -> None:
        self._size = size

    def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
        kind: FileType = "Directory" if path == "/root/directory" else "File"
        return effect.succeed(file_info(self._size, kind))

    def stream(self, path: str, **_options: Any) -> stream.Stream[bytes, PlatformError]:
        return stream.empty


def platform(file_response: Any) -> HttpPlatformService:
    return HttpPlatformService(
        "web",
        Compression(frozenset(), lambda response, _algorithm, _level: effect.succeed(response)),
        file_response,
        lambda *_a, **_k: effect.die(RuntimeError("unused")),
    )


def services(file_system: NoopFileSystem, service: HttpPlatformService) -> fx.Layer[Any]:
    return layer.merge(
        path_layer,
        layer.succeed_context(Context.make(FileSystem, file_system).add(HttpPlatform, service)),
    )


def handle(app_layer: fx.Layer[Any], request: WebRequest) -> tuple[int, dict[str, str]]:
    async def main() -> tuple[int, dict[str, str]]:
        app = await fx.run_async(static.make(root="/root").pipe(fx.provide(app_layer)))
        response = await to_web_handler(app)(request)
        await response.read()
        return response.status, {name.lower(): value for name, value in response.header_lines}

    return asyncio.run(main())


def text_platform(last_modified: str | None = None) -> HttpPlatformService:
    def respond(_path: str, **_options: Any) -> fx.Effect[HttpServerResponse]:
        response = server_response.text("0123456789")
        if last_modified is not None:
            response = response.set_header("Last-Modified", last_modified)
        return effect.succeed(response)

    return platform(respond)


def test_preserves_the_javascript_mime_type_through_to_web_handler() -> None:
    """HttpStaticServer preserves the JavaScript MIME type through toWebHandler"""
    file_system = StatFileSystem(0)
    fs_layer = layer.succeed(FileSystem, file_system)
    app_layer = layer.merge(path_layer, fs_layer).pipe(
        layer.provide_merge(platform_layer.pipe(layer.provide(fs_layer)))
    )
    _status, headers = handle(app_layer, WebRequest("http://localhost/script.js"))
    assert headers["content-type"] == "text/javascript; charset=utf-8"


def test_ignores_range_on_head_requests() -> None:
    """HttpStaticServer ignores Range on HEAD requests"""
    status, headers = handle(
        services(StatFileSystem(10), text_platform()),
        WebRequest("http://localhost/file.txt", method="HEAD", headers={"Range": "bytes=20-24"}),
    )
    assert status == 200
    assert headers["content-length"] == "10"
    assert "content-range" not in headers


@pytest.fixture
def new_york() -> Iterator[None]:
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.usefixtures("new_york")
def test_reads_an_asctime_if_modified_since_as_utc_whatever_the_process_time_zone() -> None:
    """HttpStaticServer conditional requests reads an asctime If-Modified-Since as UTC, whatever the process time zone"""  # noqa: E501
    # 08:49:37 UTC is before the Last-Modified of 10:00:00 UTC, so the file
    # has changed and must be served in full.
    status, _headers = handle(
        services(StatFileSystem(10), text_platform("Sun, 06 Nov 1994 10:00:00 GMT")),
        WebRequest(
            "http://localhost/file.txt", headers={"If-Modified-Since": "Sun Nov  6 08:49:37 1994"}
        ),
    )
    assert status == 200


Call = tuple[str, dict[str, Any]]


def precision(
    size: int, url: str, headers: dict[str, str] | None = None
) -> tuple[HttpServerResponse, list[Call]]:
    calls: list[Call] = []

    def respond(path: str, **options: Any) -> fx.Effect[HttpServerResponse]:
        calls.append((path, options))
        return effect.succeed(server_response.empty(status=options.get("status", 200)))

    request = request_from_web(WebRequest(f"http://localhost{url}", headers=headers))

    @fx.fn
    def program():
        app = yield from static.make(root="/root")
        return (yield from app.pipe(effect.provide_service(HttpServerRequest, request)))

    response = fx.run_sync(
        program().pipe(fx.provide(services(StatFileSystem(size), platform(respond)))).or_die()
    )
    return response, calls


SIZE = 9007199254740993


@pytest.mark.parametrize(
    ("url", "range_", "start", "end"),
    [
        ("/file.bin", "bytes=0-0", 0, 0),
        ("/file.bin", "bytes=-2", SIZE - 2, SIZE - 1),
        ("/directory/", "bytes=1-", 1, SIZE - 1),
    ],
)
def test_preserves_the_range_and_the_exact_total(
    url: str, range_: str, start: int, end: int
) -> None:
    """HttpStaticServer precision preserves ${range} and the exact total for ${url}"""
    response, calls = precision(SIZE, url, {"Range": range_})
    assert response.status == 206
    assert response.headers["content-range"] == f"bytes {start}-{end}/{SIZE}"
    path = "/root/directory/index.html" if url == "/directory/" else "/root/file.bin"
    assert calls == [(path, {"status": 206, "offset": start, "bytes_to_read": end - start + 1})]


def test_preserves_the_exact_total_in_a_416_response() -> None:
    """HttpStaticServer precision preserves the exact total in a 416 response"""
    response, calls = precision(SIZE, "/file.bin", {"Range": "bytes=-0"})
    assert response.status == 416
    assert response.headers["content-range"] == f"bytes */{SIZE}"
    assert calls == []


def test_serves_a_path_with_repeated_leading_slashes_from_the_root() -> None:
    """HttpStaticServer paths serves a path with repeated leading slashes from the root"""
    response, calls = precision(10, "//nested/file.txt")
    assert response.status == 200
    assert [path for path, _options in calls] == ["/root/nested/file.txt"]
