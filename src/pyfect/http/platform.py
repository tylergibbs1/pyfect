"""What a server platform provides responses with (Effect's
``HttpPlatform``): file responses with an ETag and ``last-modified``, and
response compression.

``layer`` serves files through ``FileSystem`` and compresses with the
standard library: gzip and deflate (``zlib``), and zstd where
``compression.zstd`` exists (Python 3.14). ``layer_live`` adds brotli with
the ``brotli`` extra.
"""

from __future__ import annotations

import importlib
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Literal, Never, Protocol, Self, TypedDict, Unpack, cast

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect._service_copy import replaced
from pyfect.byte_size import ByteSize
from pyfect.byte_size import Input as ByteSizeInput
from pyfect.byte_size import from_input as byte_size_from_input
from pyfect.context import Tag
from pyfect.effect import blocking, fail, fn_untraced, succeed
from pyfect.file_system import FileSystem
from pyfect.file_system import layer as file_system_layer
from pyfect.http import body as _body
from pyfect.http import mime
from pyfect.http._vary import vary_with
from pyfect.http.etag import Generator
from pyfect.http.etag import layer as etag_layer
from pyfect.http.etag import layer_weak as etag_layer_weak
from pyfect.http.etag import to_string as etag_to_string
from pyfect.http.file_like import FileLike
from pyfect.http.headers import EMPTY, Headers, format_http_date
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.headers import from_input as headers_from_input
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.server_response import stream as stream_response
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.platform_error import PlatformError, bad_argument
from pyfect.stream import Stream, from_async_iterable
from pyfect.stream import empty as empty_stream
from pyfect.stream import from_effect as stream_from_effect
from pyfect.stream import succeed as stream_succeed
from pyfect.stream import suspend as suspend_stream
from pyfect.stream import sync as sync_stream

type CompressionAlgorithm = Literal["gzip", "deflate", "br", "zstd"]
type PlatformName = Literal["deno", "node", "bun", "web"]

_MAX_SAFE = 2**53 - 1


class CompressResponse(Protocol):
    def __call__(
        self, response: HttpServerResponse, algorithm: CompressionAlgorithm, level: int | None, /
    ) -> Effect[HttpServerResponse]: ...


@dataclass(frozen=True, slots=True)
class Compression:
    """The algorithms a platform compresses with, and how it compresses a
    response's body (headers are its caller's business)."""

    algorithms: frozenset[CompressionAlgorithm]
    compress_response: CompressResponse


class FileOptions(TypedDict, total=False):
    status: int
    status_text: str
    headers: HeadersInput
    content_type: str
    bytes_to_read: ByteSizeInput
    chunk_size: int
    offset: ByteSizeInput


class FileWebOptions(TypedDict, total=False):
    status: int
    status_text: str
    headers: HeadersInput
    content_type: str
    bytes_to_read: int
    chunk_size: int
    offset: int


class HttpPlatformService:
    """The ``HttpPlatform`` service: ``make`` builds it, and
    ``HttpPlatformService(platform, compression, file_response,
    file_web_response)`` makes one of functions (a test double, say)."""

    __slots__ = ("_file_response", "_file_web_response", "compression", "platform")

    platform: PlatformName
    compression: Compression

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        platform: PlatformName,
        compression: Compression,
        file_response: Callable[..., Effect[HttpServerResponse, PlatformError]],
        file_web_response: Callable[..., Effect[HttpServerResponse]],
    ) -> None:
        self.platform = platform
        self.compression = compression
        self._file_response = file_response
        self._file_web_response = file_web_response

    def file_response(
        self, path: str, **options: Unpack[FileOptions]
    ) -> Effect[HttpServerResponse, PlatformError]:
        """A response streaming the file at ``path``, with an ``etag``
        and a ``last-modified`` header from its ``stat``. ``offset`` and
        ``bytes_to_read`` pick a range (clamped to the file); ``status``,
        ``status_text``, ``headers`` and ``content_type`` go on the
        response. Fails with a ``PlatformError`` when the file cannot be
        stat'ed, or ``offset`` or ``bytes_to_read`` is invalid."""
        return self._file_response(path, **options)

    def file_web_response(
        self, file: FileLike, **options: Unpack[FileWebOptions]
    ) -> Effect[HttpServerResponse]:
        """A response streaming the file-like ``file``, with an ``etag``
        and a ``last-modified`` header; ``offset``, ``bytes_to_read`` and
        ``chunk_size`` pick the range and its chunks, and the other options
        go on the response. Never fails."""
        return self._file_web_response(file, **options)


class HttpPlatform(Tag[HttpPlatformService], key="effect/http/HttpPlatform"):
    """The server platform."""


# --- compression ----------------------------------------------------------------


def _with_encoding(
    response: HttpServerResponse, compressed: HttpServerResponse, algorithm: str
) -> HttpServerResponse:
    if compressed is response:
        return response
    headers = {
        "content-encoding": algorithm,
        "vary": vary_with(compressed.headers, "Accept-Encoding"),
    }
    etag = compressed.headers.get("etag")
    if etag is not None and not etag.startswith("W/"):
        headers["etag"] = f"W/{etag}"
    return compressed.set_headers(headers)


def wrap_compression(impl: Compression) -> Compression:
    """``impl``, setting ``content-encoding`` and ``vary`` on what it
    compressed, and weakening a strong ETag."""

    def compress(
        response: HttpServerResponse, algorithm: CompressionAlgorithm, level: int | None
    ) -> Effect[HttpServerResponse]:
        return impl.compress_response(response, algorithm, level).map(
            lambda compressed: _with_encoding(response, compressed, algorithm)
        )

    return Compression(impl.algorithms, compress)


type Transform = Callable[
    [CompressionAlgorithm, int | None, Stream[bytes, Any]], Stream[bytes, Any]
]


def make_compression_stream(
    algorithms: Iterable[CompressionAlgorithm], transform: Transform
) -> Compression:
    """A compression transforming the bytes of bytes, stream and raw
    (``bytes``, ``str``, async iterable or ``WebResponse``) bodies; it
    leaves other bodies alone (Effect's ``makeCompressionWeb``)."""
    from pyfect.http.web import WebResponse

    def compressed(
        response: HttpServerResponse,
        chunks: Stream[bytes, Any],
        content_type: str | None,
        algorithm: CompressionAlgorithm,
        level: int | None,
    ) -> HttpServerResponse:
        body = _body.stream(transform(algorithm, level, chunks), content_type)
        return response.set_body(body).remove_header("content-length")

    def compress(
        response: HttpServerResponse, algorithm: CompressionAlgorithm, level: int | None
    ) -> Effect[HttpServerResponse]:
        body = response.body
        content_type = response.headers.get("content-type", body.content_type)
        match body:
            case _body.Bytes():
                chunks: Stream[bytes, Any] = stream_succeed(body.body)
            case _body.Stream():
                chunks = body.stream
            case _body.Raw():
                raw = body.body
                if isinstance(raw, WebResponse):
                    raw = raw.body
                if raw is None:
                    return succeed(response)
                if isinstance(raw, str):
                    raw = text_encode(raw)
                if isinstance(raw, (bytes, bytearray)):
                    chunks = stream_succeed(bytes(raw))
                elif hasattr(raw, "__aiter__"):
                    chunks = from_async_iterable(cast("Any", raw), lambda error: error)
                else:
                    return succeed(response)
            case _:
                return succeed(response)
        return succeed(compressed(response, chunks, content_type, algorithm, level))

    return Compression(frozenset(algorithms), compress)


def _zstd_available() -> bool:
    try:
        importlib.import_module("compression.zstd")
    except ImportError:
        return False
    return True


def _brotli_available() -> bool:
    return find_spec("brotlicffi") is not None


class _Compressor(Protocol):
    def chunk(self, data: bytes, /) -> bytes:
        """``data`` compressed and flushed, so a slow stream is sent as it
        is made."""
        ...

    def finish(self) -> bytes: ...


class _Zlib:
    __slots__ = ("_zlib",)

    def __init__(self, algorithm: CompressionAlgorithm, level: int | None) -> None:
        wbits = 31 if algorithm == "gzip" else 15
        self._zlib = zlib.compressobj(-1 if level is None else level, zlib.DEFLATED, wbits)

    def chunk(self, data: bytes) -> bytes:
        return self._zlib.compress(data) + self._zlib.flush(zlib.Z_SYNC_FLUSH)

    def finish(self) -> bytes:
        return self._zlib.flush()


class _Zstd:
    __slots__ = ("_zstd",)

    def __init__(self, level: int | None) -> None:
        # By name: Python 3.13 has no ``compression``, and pyright checks on 3.13 and 3.14.
        zstd: Any = importlib.import_module("compression.zstd")
        self._zstd: Any = zstd.ZstdCompressor(level=level)

    def chunk(self, data: bytes) -> bytes:
        return self._zstd.compress(data, self._zstd.FLUSH_BLOCK)

    def finish(self) -> bytes:
        return self._zstd.flush()


def _compressor(algorithm: CompressionAlgorithm, level: int | None) -> _Compressor:
    match algorithm:
        case "zstd":
            return _Zstd(level)
        case "br":
            from pyfect.http._brotli import Brotli

            return Brotli(level)
        case "gzip" | "deflate":
            return _Zlib(algorithm, level)


def _transform(
    algorithm: CompressionAlgorithm, level: int | None, chunks: Stream[bytes, Any]
) -> Stream[bytes, Any]:
    def make() -> Stream[bytes, Any]:
        compressor = _compressor(algorithm, level)
        out = chunks.map(compressor.chunk).concat(sync_stream(compressor.finish))
        return out.filter(lambda chunk: len(chunk) > 0)

    return suspend_stream(make)


def _transform_off_thread(
    algorithm: CompressionAlgorithm, level: int | None, chunks: Stream[bytes, Any]
) -> Stream[bytes, Any]:
    """``_transform`` as ``node:zlib``'s streams run: brotli's default quality takes
    seconds per megabyte, which a server's thread cannot spend."""

    def make() -> Stream[bytes, Any]:
        compressor = _compressor(algorithm, level)
        compressed = chunks.map_effect(lambda data: blocking(lambda: compressor.chunk(data)))
        out = compressed.concat(stream_from_effect(blocking(compressor.finish)))
        return out.filter(lambda chunk: len(chunk) > 0)

    return suspend_stream(make)


def _compress_whole(data: bytes, algorithm: CompressionAlgorithm, level: int | None) -> bytes:
    if algorithm in {"zstd", "br"}:
        compressor = _compressor(algorithm, level)
        return compressor.chunk(data) + compressor.finish()
    wbits = 31 if algorithm == "gzip" else 15
    return zlib.compress(data, -1 if level is None else level, wbits)


def compression_one_shot(fallback: Compression) -> Compression:
    """Bytes bodies compressed whole, off the fiber's thread, with an exact
    ``content-length``; other bodies by ``fallback`` (Node's
    ``NodeHttpCompression.make``)."""

    def compress(
        response: HttpServerResponse, algorithm: CompressionAlgorithm, level: int | None
    ) -> Effect[HttpServerResponse]:
        body = response.body
        if not isinstance(body, _body.Bytes):
            return fallback.compress_response(response, algorithm, level)
        content_type = response.headers.get("content-type", body.content_type)
        data = body.body

        def compressed(result: bytes) -> HttpServerResponse:
            return response.set_body(_body.bytes_(result, content_type)).set_header(
                "content-length", str(len(result))
            )

        return blocking(lambda: _compress_whole(data, algorithm, level)).map(compressed)

    return Compression(fallback.algorithms, compress)


_STDLIB_ALGORITHMS: tuple[CompressionAlgorithm, ...] = (
    ("gzip", "deflate", "zstd") if _zstd_available() else ("gzip", "deflate")
)

compression_stdlib: Compression = make_compression_stream(_STDLIB_ALGORITHMS, _transform)
"""gzip and deflate, and zstd on Python 3.14."""

compression_live: Compression = compression_one_shot(
    make_compression_stream(
        (*_STDLIB_ALGORITHMS, *(("br",) if _brotli_available() else ())), _transform_off_thread
    )
)
"""What a live server offers (Node's ``NodeHttpCompression``): ``compression_stdlib``'s and
brotli with the ``brotli`` extra, one-shot bodies compressed whole off the fiber's thread."""


# --- file responses ---------------------------------------------------------------


class FileResponseImpl(Protocol):
    def __call__(  # noqa: PLR0917
        self,
        path: str,
        status: int,
        status_text: str | None,
        headers: Headers,
        start: int,
        end: int | None,
        content_length: int,
        /,
    ) -> HttpServerResponse: ...


class FileWebResponseImpl(Protocol):
    def __call__(
        self,
        file: FileLike,
        status: int,
        status_text: str | None,
        headers: Headers,
        options: FileWebOptions,
        /,
    ) -> HttpServerResponse: ...


def _option_headers(options: FileOptions | FileWebOptions) -> Headers:
    given = options.get("headers")
    headers = EMPTY if given is None else headers_from_input(given)
    content_type = options.get("content_type")
    return headers if not content_type else headers.set("content-type", content_type)


def _size(value: ByteSizeInput, field: str) -> Effect[ByteSize, PlatformError]:
    size = byte_size_from_input(value)
    if size is None:
        return fail(
            bad_argument(
                module="HttpPlatform",
                method="fileResponse",
                description=f"Invalid {field}: {value}",
            )
        )
    return succeed(size)


def _safe(value: int, field: str) -> Effect[int, PlatformError]:
    if value > _MAX_SAFE:
        description = f"{field} exceeds the safe integer range: {value}"
        return fail(
            bad_argument(module="HttpPlatform", method="fileResponse", description=description)
        )
    return succeed(value)


def make(
    *,
    platform: PlatformName,
    compression: Compression,
    file_response: FileResponseImpl,
    file_web_response: FileWebResponseImpl,
) -> Effect[HttpPlatformService, Never, Generator | FileSystem]:
    """A platform from its file responses (given the clamped range and the
    ETag and ``last-modified`` headers) and its compression."""

    @fn_untraced
    def build():
        fs = yield from FileSystem()
        etags = yield from Generator()

        @fn_untraced
        def respond_file(path: str, **options: Unpack[FileOptions]):
            info = yield from fs.stat(path)
            etag = yield from etags.from_file_info(info)
            given_offset = options.get("offset")
            requested = 0 if given_offset is None else (yield from _size(given_offset, "offset"))
            offset = min(requested, info.size)
            available = info.size - offset
            given_count = options.get("bytes_to_read")
            count = None if given_count is None else (yield from _size(given_count, "bytesToRead"))
            content_length = available if count is None or count > available else count
            limit = None if count is None else offset + content_length
            start = yield from _safe(offset, "offset")
            end = None if limit is None else (yield from _safe(limit, "end"))
            headers = _option_headers(options).set("etag", etag_to_string(etag))
            if info.mtime is not None:
                headers = headers.set("last-modified", format_http_date(info.mtime))
            return file_response(
                path,
                options.get("status", 200),
                options.get("status_text"),
                headers,
                start,
                end,
                content_length,
            )

        def respond_file_web(
            file: FileLike, **options: Unpack[FileWebOptions]
        ) -> Effect[HttpServerResponse]:
            def respond(etag: Any) -> HttpServerResponse:
                headers = _option_headers(options).merge(
                    Headers(
                        {
                            "etag": etag_to_string(etag),
                            "last-modified": format_http_date(file.last_modified),
                        }
                    )
                )
                return file_web_response(
                    file, options.get("status", 200), options.get("status_text"), headers, options
                )

            return etags.from_file_web(file).map(respond)

        return HttpPlatformService(
            platform, wrap_compression(compression), respond_file, respond_file_web
        )

    return build()


def _mime_type(path: str) -> str:
    return mime.get_type(path) or "application/octet-stream"


def _web_file_chunks(
    file: FileLike, offset: int, end: int, chunk_size: int | None
) -> Stream[bytes, Any]:
    if end <= offset:
        return empty_stream

    def cut(position: int, data: bytes) -> tuple[int, list[tuple[bytes, bool]]]:
        following = position + len(data)
        start = min(max(offset - position, 0), len(data))
        stop = min(max(end - position, 0), len(data))
        step = chunk_size or max(stop - start, 1)
        pieces = [
            (data[index : min(index + step, stop)], following >= end and index + step >= stop)
            for index in range(start, stop, step)
        ]
        return following, pieces

    # The file is opened when the body is read, not when the response is
    # made (a HEAD response never reads it).
    return suspend_stream(
        lambda: (
            file.stream()
            .map_accum(lambda: 0, cut)
            .take_until(lambda piece: piece[1])
            .map(lambda piece: piece[0])
        )
    )


def _layer_build(
    fs: Any, compression: Compression = compression_stdlib
) -> Effect[HttpPlatformService, Any, Generator | FileSystem]:
    def file_response(  # noqa: PLR0917
        path: str,
        status: int,
        status_text: str | None,
        headers: Headers,
        start: int,
        end: int | None,
        content_length: int,
    ) -> HttpServerResponse:
        chunks = fs.stream(path, offset=start, bytes_to_read=None if end is None else end - start)
        options: dict[str, Any] = {
            "content_type": headers.get("content-type") or _mime_type(path),
            "headers": headers.set("content-length", str(content_length)),
            "status": status,
        }
        if content_length <= _MAX_SAFE:
            options["content_length"] = content_length
        if status_text is not None:
            options["status_text"] = status_text
        return stream_response(chunks, **options)

    def file_web_response(
        file: FileLike,
        status: int,
        status_text: str | None,
        headers: Headers,
        options: FileWebOptions,
    ) -> HttpServerResponse:
        offset = min(max(options.get("offset", 0), 0), file.size)
        available = file.size - offset
        count = options.get("bytes_to_read")
        content_length = available if count is None else min(max(count, 0), available)
        chunk_size = options.get("chunk_size")
        chunks = _web_file_chunks(
            file,
            offset,
            offset + content_length,
            None if chunk_size is None else max(1, chunk_size),
        )
        content_type = headers.get("content-type") or file.content_type or _mime_type(file.name)
        extra: dict[str, Any] = {} if status_text is None else {"status_text": status_text}
        return stream_response(
            chunks,
            content_type=content_type,
            content_length=content_length,
            headers=headers,
            status=status,
            **extra,
        )

    return make(
        platform="web",
        compression=compression,
        file_response=file_response,
        file_web_response=file_web_response,
    )


layer: Layer[HttpPlatform, Never, FileSystem] = layer_effect(
    HttpPlatform, FileSystem().flat_map(_layer_build)
).pipe(layer_provide(etag_layer_weak))
"""Files streamed from ``FileSystem``; the standard library's
compression; weak ETags."""

layer_strong: Layer[HttpPlatform, Never, FileSystem] = layer_effect(
    HttpPlatform, FileSystem().flat_map(_layer_build)
).pipe(layer_provide(etag_layer))
"""``layer`` with strong ETags."""

layer_live: Layer[HttpPlatform] = (
    layer_effect(
        HttpPlatform,
        FileSystem().flat_map(lambda fs: _layer_build(fs, compression_live)),
    )
    .pipe(layer_provide(etag_layer))
    .pipe(layer_provide(file_system_layer))
)
"""The platform of the live server (Effect's ``NodeHttpPlatform.layer``):
``layer_strong`` over the host's file system, compressing bytes bodies
whole."""


__all__ = [
    "CompressResponse",
    "Compression",
    "CompressionAlgorithm",
    "FileOptions",
    "FileResponseImpl",
    "FileWebOptions",
    "FileWebResponseImpl",
    "HttpPlatform",
    "HttpPlatformService",
    "PlatformError",
    "PlatformName",
    "Transform",
    "compression_live",
    "compression_one_shot",
    "compression_stdlib",
    "layer",
    "layer_live",
    "layer_strong",
    "make",
    "make_compression_stream",
    "wrap_compression",
]
