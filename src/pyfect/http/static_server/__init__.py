"""Serving files from a directory (Effect's ``HttpStaticServer``).

``make(root=...)`` is an app serving the files below ``root``: a
directory serves its ``index`` (redirecting to the path with a trailing
``/`` first), byte ranges get ``206`` (``416`` when unsatisfiable),
``If-None-Match`` / ``If-Modified-Since`` get ``304``, and with ``spa``
an extensionless miss that accepts HTML serves the index. ``layer(...)``
adds it to the ``HttpRouter`` as ``GET /*``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Never, NotRequired, TypedDict, Unpack

from pyfect._core import Effect
from pyfect._js import decode_uri_component
from pyfect._url import Url
from pyfect.effect import fail, fn_untraced, succeed
from pyfect.file_system import FileInfo, FileSystem, FileSystemService
from pyfect.http.platform import HttpPlatform, HttpPlatformService
from pyfect.http.router import HttpRouter
from pyfect.http.server_error import HttpServerError, InternalError, RouteNotFound
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_respondable import to_response
from pyfect.http.server_response import HttpServerResponse, empty, redirect
from pyfect.http.static_server import _conditional
from pyfect.http.static_server._mime import DEFAULT_MIME_TYPES, resolve_mime_type
from pyfect.http.static_server._range import ByteRange, parse_range
from pyfect.layer import Layer, effect_discard
from pyfect.path import Path, PathService
from pyfect.platform_error import NotFound, PlatformError

type StaticApp = Effect[HttpServerResponse, HttpServerError, HttpServerRequest]

_LEADING_SLASHES = re.compile(r"/+")
_LEADING_SEPARATORS = re.compile(r"[/\\]+")


class Options(TypedDict):
    """``index`` (default ``"index.html"``; ``None``: directories are not
    served), ``spa``, ``cache_control`` and extra ``mime_types`` (by
    extension, without the dot)."""

    root: str
    index: NotRequired[str | None]
    spa: NotRequired[bool]
    cache_control: NotRequired[str]
    mime_types: NotRequired[Mapping[str, str]]


class LayerOptions(Options):
    prefix: NotRequired[str]


def _not_found(request: ServerRequest) -> HttpServerError:
    return HttpServerError(RouteNotFound(request))


def _internal(request: ServerRequest, cause: object) -> HttpServerError:
    return HttpServerError(InternalError(request, cause=cause))


def _platform_error(request: ServerRequest, error: PlatformError) -> HttpServerError:
    return _not_found(request) if isinstance(error.reason, NotFound) else _internal(request, error)


def _strip_query(url: str) -> str:
    return url.partition("?")[0]


def _resolve_file_path(path: PathService, root: str, url: str) -> str | None:
    try:
        decoded = decode_uri_component(_strip_query(url))
    except ValueError:
        return None
    if "\x00" in decoded:
        return None
    # Every leading separator is part of the URL, not a filesystem root.
    leading = _LEADING_SEPARATORS if path.sep == "\\" else _LEADING_SLASHES
    return path.resolve_within(root, leading.sub("", decoded, count=1))


def _accepts_html(accept: str | None) -> bool:
    return accept is not None and "text/html" in accept.lower()


@dataclass(frozen=True, slots=True)
class _Server:
    file_system: FileSystemService
    path: PathService
    platform: HttpPlatformService
    root: str
    index: str | None
    spa: bool
    cache_control: str | None
    mime_types: Mapping[str, str]

    def _with_file_headers(
        self, response: HttpServerResponse, file_path: str
    ) -> HttpServerResponse:
        response = response.set_headers(
            {
                "Content-Type": resolve_mime_type(self.path, file_path, self.mime_types),
                "Accept-Ranges": "bytes",
            }
        )
        if self.cache_control is not None:
            response = response.set_header("Cache-Control", self.cache_control)
        return response

    def _file_response(
        self, request: ServerRequest, file_path: str, **file_options: Any
    ) -> Effect[HttpServerResponse, HttpServerError]:
        made: Effect[HttpServerResponse, PlatformError] = self.platform.file_response(
            file_path, **file_options
        )
        return made.map_error(lambda error: _platform_error(request, error)).map(
            lambda response: self._with_file_headers(response, file_path)
        )

    def _serve_range(
        self, request: ServerRequest, file_path: str, file_size: int, header: str
    ) -> Effect[HttpServerResponse, HttpServerError]:
        parsed = parse_range(header, file_size)
        if parsed is None:
            return self._file_response(request, file_path)
        if parsed == "unsatisfiable":
            return succeed(empty(status=416, headers={"Content-Range": f"bytes */{file_size}"}))
        byte_range: ByteRange = parsed
        content_range = f"bytes {byte_range.start}-{byte_range.end}/{file_size}"
        return self._file_response(
            request,
            file_path,
            status=206,
            offset=byte_range.start,
            bytes_to_read=byte_range.end - byte_range.start + 1,
        ).map(lambda response: response.set_header("Content-Range", content_range))

    @fn_untraced
    def serve_file(self, request: ServerRequest, file_path: str, file_size: int | None = None):
        range_header = request.headers.get("range") if request.method == "GET" else None
        full: HttpServerResponse | None = None
        headers = request.headers
        if headers.get("if-none-match") is not None or headers.get("if-modified-since") is not None:
            full = yield from self._file_response(request, file_path)
            not_modified = _conditional.evaluate(request, full)
            if not_modified is not None:
                return not_modified
        if range_header is None:
            return (
                full if full is not None else (yield from self._file_response(request, file_path))
            )
        if_range = headers.get("if-range")
        if if_range is not None:
            if full is None:
                full = yield from self._file_response(request, file_path)
            if not _conditional.matches_if_range(if_range, full.headers.get("etag")):
                return full
        if file_size is None:
            info = yield from self.file_system.stat(file_path).map_error(
                lambda error: _platform_error(request, error)
            )
            file_size = int(info.size)
        if full is not None and parse_range(range_header, file_size) is None:
            return full
        return (yield from self._serve_range(request, file_path, file_size, range_header))

    def _serve_directory(
        self, request: ServerRequest, directory: str, index: str
    ) -> Effect[HttpServerResponse, HttpServerError]:
        original_url = request.original_url
        if not original_url.startswith("/"):
            url = Url(original_url)
            original_url = url.pathname + url.search
        pathname = _strip_query(original_url)
        if not pathname.endswith("/"):
            # Keep the redirect local even when the path starts with several slashes.
            location = _LEADING_SLASHES.sub("/", pathname, count=1).replace("\\", "%5C")
            return succeed(redirect(f"{location}/{original_url[len(pathname) :]}", status=301))
        return self.serve_file(request, self.path.join(directory, index))

    def _on_stat_error(
        self, request: ServerRequest, resolved: str, error: PlatformError
    ) -> Effect[HttpServerResponse, HttpServerError]:
        if not isinstance(error.reason, NotFound):
            return fail(_internal(request, error))
        if (
            self.spa
            and self.index is not None
            and self.path.extname(resolved) == ""
            and _accepts_html(request.headers.get("accept"))
        ):
            return self.serve_file(request, self.path.join(self.root, self.index))
        return fail(_not_found(request))

    def _on_info(
        self, request: ServerRequest, resolved: str, info: FileInfo
    ) -> Effect[HttpServerResponse, HttpServerError]:
        if info.type == "File":
            return self.serve_file(request, resolved, int(info.size))
        if info.type == "Directory" and self.index is not None:
            return self._serve_directory(request, resolved, self.index)
        return fail(_not_found(request))

    def handle(self, request: ServerRequest) -> Effect[HttpServerResponse, HttpServerError]:
        resolved = _resolve_file_path(self.path, self.root, request.url)
        if resolved is None:
            return fail(_not_found(request))
        found = resolved
        return self.file_system.stat(found).match_effect(
            on_failure=lambda error: self._on_stat_error(request, found, error),
            on_success=lambda info: self._on_info(request, found, info),
        )


@fn_untraced
def make(**options: Unpack[Options]):
    """The app serving ``options["root"]`` (see the module docs)."""
    file_system = yield from FileSystem()
    path = yield from Path()
    platform = yield from HttpPlatform()
    server = _Server(
        file_system,
        path,
        platform,
        path.resolve(options["root"]),
        options.get("index", "index.html"),
        options.get("spa", False),
        options.get("cache_control"),
        {**DEFAULT_MIME_TYPES, **options.get("mime_types", {})},
    )
    app: StaticApp = HttpServerRequest().flat_map(server.handle)
    return app


def layer(
    **options: Unpack[LayerOptions],
) -> Layer[Never, PlatformError, HttpRouter | FileSystem | Path | HttpPlatform]:
    """``make(...)`` added to the ``HttpRouter`` as ``GET /*`` (under
    ``prefix`` when given), its errors answered as their responses."""
    prefix = options.pop("prefix", None)

    @fn_untraced
    def build():
        router = yield from HttpRouter()
        app: StaticApp = yield from make(**options)
        handler = app.catch_all(to_response)
        target = router if prefix is None else router.prefixed(prefix)
        yield from target.add("GET", "/*", handler)

    return effect_discard(build())


__all__ = ["LayerOptions", "Options", "StaticApp", "layer", "make"]
