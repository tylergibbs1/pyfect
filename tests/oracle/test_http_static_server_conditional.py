"""Ports of platform-node's ``HttpStaticServerConditional.test.ts``. Each
test's docstring is the Effect test title."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pyfect as fx
from pyfect import effect, layer
from pyfect.byte_size import ByteSize
from pyfect.exit import Failure
from pyfect.file_system import FileInfo, FileSystem, NoopFileSystem
from pyfect.http import router, server_response
from pyfect.http import static_server as static
from pyfect.http.platform import Compression, HttpPlatform, HttpPlatformService
from pyfect.http.server_error import HttpServerError, InternalError, RouteNotFound
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import request_from_web, to_web_handler
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError, system_error

ROOT = "/root"
FILE_PATH = f"{ROOT}/file.txt"
FILE_BODY = "hello static"
LAST_MODIFIED = "Wed, 01 Jan 2025 00:00:00 GMT"

FILE_INFO = FileInfo(
    type="File",
    mtime=datetime(2025, 1, 1, tzinfo=UTC),
    atime=None,
    birthtime=None,
    dev=0,
    ino=None,
    mode=0,
    nlink=None,
    uid=None,
    gid=None,
    rdev=None,
    size=ByteSize(len(FILE_BODY)),
    blksize=None,
    blocks=None,
)


def _not_found(path: str) -> PlatformError:
    return system_error(
        "NotFound",
        module="FileSystem",
        method="stat",
        description="No such file or directory",
        path_or_descriptor=path,
    )


def _permission_denied(path: str) -> PlatformError:
    return system_error(
        "PermissionDenied",
        module="FileSystem",
        method="stat",
        description="Operation not permitted",
        path_or_descriptor=path,
    )


class _FileSystem(NoopFileSystem):
    def __init__(self, stat_error: PlatformError | None = None) -> None:
        self._stat_error = stat_error

    def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
        if self._stat_error is not None:
            return effect.fail(self._stat_error)
        return effect.succeed(FILE_INFO) if path == FILE_PATH else effect.fail(_not_found(path))


def _platform(
    file_response_error: PlatformError | None = None, *, validators: bool = True
) -> HttpPlatformService:
    def respond(_path: str, **options: Any) -> fx.Effect[HttpServerResponse, PlatformError]:
        if file_response_error is not None:
            return effect.fail(file_response_error)
        headers = {"ETag": '"etag-value"', "Last-Modified": LAST_MODIFIED} if validators else {}
        return effect.succeed(
            server_response.text(FILE_BODY, status=options.get("status", 200), headers=headers)
        )

    return HttpPlatformService(
        "node",
        Compression(frozenset(), lambda response, _algorithm, _level: effect.succeed(response)),
        respond,
        lambda *_a, **_k: effect.die(RuntimeError("not implemented")),
    )


def _app(
    file_system: NoopFileSystem, platform: HttpPlatformService, **options: Any
) -> static.StaticApp:
    return fx.run_blocking(
        static.make(root=ROOT, **options)
        .pipe(fx.provide(path_layer))
        .pipe(effect.provide_service(FileSystem, file_system))
        .pipe(effect.provide_service(HttpPlatform, platform))
    )


def _fetch_all(app: static.StaticApp, requests: list[WebRequest]) -> list[WebResponse]:
    async def main() -> list[WebResponse]:
        handler = to_web_handler(app)
        return [await handler(request) for request in requests]

    return asyncio.run(main())


def _get(headers: dict[str, str] | None = None) -> WebRequest:
    return WebRequest("http://localhost/file.txt", headers=headers)


def _handler_app() -> static.StaticApp:
    return _app(_FileSystem(), _platform(), cache_control="public, max-age=60")


def test_304_with_if_none_match_exact_weak_and_wildcard() -> None:
    """304 with If-None-Match exact, weak, and wildcard"""
    etag = '"etag-value"'
    warmup, exact, weak, listed, any_ = _fetch_all(
        _handler_app(),
        [
            _get(),
            _get({"If-None-Match": etag}),
            _get({"If-None-Match": f"W/{etag}"}),
            _get({"If-None-Match": f'"other", W/{etag}'}),
            _get({"If-None-Match": "*"}),
        ],
    )
    assert warmup.get("etag") == etag
    assert [exact.status, weak.status, listed.status, any_.status] == [304, 304, 304, 304]
    assert exact.get("etag") == etag
    assert exact.get("cache-control") == "public, max-age=60"
    assert exact.get("last-modified") == LAST_MODIFIED
    assert exact.get("content-type") is None
    assert exact.get("content-length") is None


def test_304_with_if_modified_since_and_no_if_none_match() -> None:
    """304 with If-Modified-Since and no If-None-Match"""
    not_modified, modified, invalid_date = _fetch_all(
        _handler_app(),
        [
            _get({"If-Modified-Since": LAST_MODIFIED}),
            _get({"If-Modified-Since": "Tue, 31 Dec 2024 23:59:59 GMT"}),
            _get({"If-Modified-Since": "not-a-date"}),
        ],
    )
    assert [not_modified.status, modified.status, invalid_date.status] == [304, 200, 200]


def test_if_none_match_takes_precedence_over_if_modified_since() -> None:
    """If-None-Match takes precedence over If-Modified-Since"""
    [response] = _fetch_all(
        _handler_app(),
        [
            _get(
                {
                    "If-None-Match": '"different"',
                    "If-Modified-Since": "Thu, 02 Jan 2025 00:00:00 GMT",
                }
            )
        ],
    )
    assert response.status == 200


def test_matched_if_none_match_takes_precedence_over_range() -> None:
    """matched If-None-Match takes precedence over Range"""
    [response] = _fetch_all(
        _handler_app(),
        [
            _get(
                {
                    "If-None-Match": '"etag-value"',
                    "If-Range": '"stale"',
                    "Range": "bytes=1000-1001",
                }
            )
        ],
    )
    assert response.status == 304
    assert response.get("etag") == '"etag-value"'
    assert response.get("cache-control") == "public, max-age=60"
    assert response.get("last-modified") == LAST_MODIFIED
    for name in ("content-range", "accept-ranges", "content-type", "content-length"):
        assert response.get(name) is None


def _error(app: static.StaticApp, url: str) -> object:
    request = request_from_web(WebRequest(url))
    exit = fx.run_blocking_exit(app.pipe(effect.provide_service(HttpServerRequest, request)))
    assert isinstance(exit, Failure)
    return exit.cause.squash()


def test_wraps_missing_routes_as_http_server_error_route_not_found() -> None:
    """wraps missing routes as HttpServerError RouteNotFound"""
    error = _error(_app(_FileSystem(), _platform()), "http://localhost/missing.txt")
    assert isinstance(error, HttpServerError)
    assert isinstance(error.reason, RouteNotFound)


def test_maps_non_not_found_platform_failures_to_http_server_error_internal_error() -> None:
    """maps non-NotFound platform failures to HttpServerError InternalError"""
    stat_error = _permission_denied(FILE_PATH)
    error = _error(_app(_FileSystem(stat_error), _platform()), "http://localhost/file.txt")
    assert isinstance(error, HttpServerError)
    assert isinstance(error.reason, InternalError)
    assert error.reason.cause is stat_error


def test_layer_renders_internal_error_responses_as_500() -> None:
    """layer renders InternalError responses as 500"""
    dependencies = layer.merge(
        path_layer,
        layer.succeed_context(
            fx.Context.make(FileSystem, _FileSystem()).add(
                HttpPlatform, _platform(_permission_denied(FILE_PATH), validators=False)
            )
        ),
    )
    app = static.layer(root=ROOT).pipe(layer.provide_merge(dependencies))

    async def main() -> int:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            return (await made.handler(_get())).status
        finally:
            await made.dispose()

    assert asyncio.run(main()) == 500
