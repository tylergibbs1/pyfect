"""The transport options of ``@clickhouse/client`` a ``ClickhouseClientConfig``
takes, under their ``createClient`` names: ``compression``, ``keep_alive``,
``tls``, ``log`` and ``json`` (with ``max_open_connections``,
``use_multipart_params`` and ``use_multipart_params_auto``, plain fields of
the config). Each is checked when the config is made and parsed here into
what the driver and the httpx client use.

- ``compression``: ``{"response": True}`` asks the server for a gzip
  response (``enable_http_compression=1``, ``Accept-Encoding``);
  ``{"response": {"codec": "zstd"}}`` names the codec. ``{"request": True}``
  gzips the bodies of inserts, commands and ``exec``;
  ``{"request": {"codec": "br", "quality": 4}}`` picks the codec and its
  level (``level`` for gzip and zstd, ``quality`` for Brotli, 4 by default).
  A zstd request body needs Python 3.14 (``compression.zstd``), Brotli the
  ``brotli`` extra; on the httpx client ``make`` creates, a zstd response
  needs ``zstandard`` and a Brotli one the ``brotli`` extra.
- ``keep_alive``: ``enabled`` (``True``) and ``idle_socket_ttl``, how long
  an idle connection is kept (2500 ms; ``0`` keeps it until the server
  closes it).
- ``tls``: ``{"ca_cert": pem}`` to trust a CA, with ``cert`` and ``key`` for
  a client certificate; on an ``https`` URL the credentials then go in
  ``X-ClickHouse-User`` / ``X-ClickHouse-Key`` (and
  ``X-ClickHouse-SSL-Certificate-Auth: on`` with a certificate).
- ``log``: ``{"level": "WARN"}``, the least severe of the client's own
  logs that are written, through the fiber's loggers.
- ``json``: ``{"parse": ..., "stringify": ...}`` read result rows and write
  inserted rows.

``keep_alive``, ``max_open_connections`` and ``tls`` configure the httpx
client ``make`` creates, and have no effect on an ``http_client`` given in
the config (as on ``@clickhouse/client``'s ``http_agent``).
"""

from __future__ import annotations

import os
import ssl
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast

from pyfect import _json_text
from pyfect._js import text_encode
from pyfect.duration import Input as DurationInput

type CompressionCodec = Literal["gzip", "zstd", "br"]
"""A codec ``@clickhouse/client`` compresses with."""

_CODECS: tuple[CompressionCodec, ...] = ("gzip", "zstd", "br")


class ResponseCompression(TypedDict):
    codec: CompressionCodec


class GzipRequestCompression(TypedDict):
    codec: Literal["gzip"]
    level: NotRequired[int]


class ZstdRequestCompression(TypedDict):
    codec: Literal["zstd"]
    level: NotRequired[int]


class BrotliRequestCompression(TypedDict):
    codec: Literal["br"]
    quality: NotRequired[int]


type RequestCompression = GzipRequestCompression | ZstdRequestCompression | BrotliRequestCompression


class Compression(TypedDict, total=False):
    """``@clickhouse/client``'s ``compression`` (see the module)."""

    response: bool | ResponseCompression
    request: bool | RequestCompression


class KeepAlive(TypedDict, total=False):
    """``@clickhouse/client``'s ``keep_alive``; ``idle_socket_ttl`` is a
    duration (a bare number is milliseconds)."""

    enabled: bool
    idle_socket_ttl: DurationInput


class BasicTls(TypedDict):
    """A CA certificate (PEM) to trust."""

    ca_cert: bytes


class MutualTls(TypedDict):
    """A CA certificate and the client's certificate and key (PEM)."""

    ca_cert: bytes
    cert: bytes
    key: bytes


type Tls = BasicTls | MutualTls

type LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "OFF"]

LOG_LEVELS: dict[LogLevel, int] = {
    "TRACE": 0,
    "DEBUG": 1,
    "INFO": 2,
    "WARN": 3,
    "ERROR": 4,
    "OFF": 127,
}
"""``ClickHouseLogLevel``'s values."""


class Log(TypedDict, total=False):
    """``@clickhouse/client``'s ``log``: the least severe level written
    (``WARN`` by default)."""

    level: LogLevel


class JsonHandling(TypedDict, total=False):
    """``@clickhouse/client``'s ``json``: how rows are read and written."""

    parse: Callable[[str], object]
    stringify: Callable[[object], str]


@dataclass(frozen=True, slots=True)
class Json:
    """The ``json`` option with its defaults (``JSON.parse`` /
    ``JSON.stringify``)."""

    parse: Callable[[str], object] = _json_text.parse
    stringify: Callable[[object], str] | None = None
    """``None``: pyfect's own encoding of rows (dates, decimals, UUIDs)."""


def json_handling(given: JsonHandling | None) -> Json:
    given = given or {}
    return Json(given.get("parse", _json_text.parse), given.get("stringify"))


@dataclass(frozen=True, slots=True)
class RequestCodec:
    """How request bodies are compressed: a codec and its level (Brotli's
    quality)."""

    codec: CompressionCodec
    level: int | None = None

    def compressor(self) -> Compressor:
        """A new compressor for one body."""
        match self.codec:
            case "gzip":
                return _Zlib(self.level)
            case "zstd":
                return _Zstd(self.level)
            case "br":
                return _Brotli(4 if self.level is None else self.level)


class Compressor(Protocol):
    def compress(self, data: bytes) -> bytes: ...
    def flush(self) -> bytes: ...


class _Zlib:
    __slots__ = ("_compressor",)

    def __init__(self, level: int | None) -> None:
        self._compressor = zlib.compressobj(-1 if level is None else level, wbits=31)

    def compress(self, data: bytes) -> bytes:
        return self._compressor.compress(data)

    def flush(self) -> bytes:
        return self._compressor.flush()


class _Zstd:
    __slots__ = ("_compressor",)

    def __init__(self, level: int | None) -> None:
        import importlib

        # ``compression.zstd`` is Python 3.14's; ``request_codec`` checks it.
        zstd: Any = importlib.import_module("compression.zstd")
        self._compressor: Any = zstd.ZstdCompressor(level)

    def compress(self, data: bytes) -> bytes:
        return self._compressor.compress(data)

    def flush(self) -> bytes:
        return self._compressor.flush()


class _Brotli:
    __slots__ = ("_compressor",)

    def __init__(self, quality: int) -> None:
        from pyfect.http._brotli import Brotli

        self._compressor = Brotli(quality)

    def compress(self, data: bytes) -> bytes:
        return self._compressor.chunk(data)

    def flush(self) -> bytes:
        return self._compressor.finish()


def _unknown_codec(value: object, direction: str) -> ValueError:
    return ValueError(
        f'Unknown {direction} compression codec "{value}". Supported codecs: gzip, zstd, br.'
    )


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


def _zstd_unsupported(needs: str) -> ValueError:
    return ValueError(
        f"zstd compression is not supported here: {needs}. Use gzip compression instead."
    )


def request_codec(value: bool | RequestCompression | None) -> RequestCodec | None:
    """``normalizeRequestCompression`` and ``ensureRequestCodecSupported``."""
    if not value:
        return None
    if value is True:
        return RequestCodec("gzip")
    codec = cast("object", value.get("codec"))
    match codec:
        case "gzip" | "zstd":
            found = RequestCodec(
                "gzip" if codec == "gzip" else "zstd", cast("int | None", value.get("level"))
            )
        case "br":
            found = RequestCodec("br", cast("int | None", value.get("quality")))
        case _:
            raise _unknown_codec(codec, "request")
    if found.codec == "zstd" and not _has_module("compression.zstd"):
        raise _zstd_unsupported("compressing needs Python 3.14 (`compression.zstd`)")
    if found.codec == "br":
        import pyfect.http._brotli  # noqa: F401  # pyright: ignore[reportUnusedImport]
    return found


def response_codec(
    value: bool | ResponseCompression | None, *, default_client: bool
) -> CompressionCodec | None:
    """``normalizeResponseCompression`` and ``ensureResponseCodecSupported``:
    on the httpx client ``make`` creates, the codec must be one httpx can
    decode."""
    if not value:
        return None
    if value is True:
        return "gzip"
    codec = cast("object", value.get("codec"))
    if codec not in _CODECS:
        raise _unknown_codec(codec, "response")
    found: CompressionCodec = codec
    if default_client and found == "zstd" and not _has_module("zstandard"):
        raise _zstd_unsupported("httpx decompresses zstd with the `zstandard` package")
    if (
        default_client
        and found == "br"
        and not _has_module("brotlicffi")
        and not _has_module("brotli")
    ):
        raise ImportError(
            "Brotli responses need the 'brotli' extra for httpx to decompress them: "
            "pip install 'pyfect-dev[brotli]'"
        )
    return found


@dataclass(frozen=True, slots=True)
class TlsContext:
    """The ``tls`` option: the SSL context of the httpx client ``make``
    creates, and whether a client certificate authenticates."""

    context: ssl.SSLContext
    mutual: bool


def tls_context(tls: Tls) -> TlsContext:
    """An SSL context trusting ``ca_cert`` (only it, as Node's ``ca``), with
    the client certificate when ``cert`` and ``key`` are given."""
    context = ssl.create_default_context(cadata=tls["ca_cert"].decode("ascii"))
    cert, key = tls.get("cert"), tls.get("key")
    mutual = cert is not None and key is not None
    if mutual:
        # ``ssl`` loads a certificate chain only from files.
        with tempfile.TemporaryDirectory() as directory:
            cert_path = os.path.join(directory, "cert.pem")
            key_path = os.path.join(directory, "key.pem")
            for path, data in ((cert_path, cert), (key_path, key)):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as file:
                    file.write(cast("bytes", data))
            context.load_cert_chain(cert_path, key_path)
    return TlsContext(context, mutual)


def url_boolean(key: str, value: str) -> bool:
    """``booleanConfigURLValue``."""
    trimmed = value.strip()
    if trimmed in ("true", "1"):
        return True
    if trimmed in ("false", "0"):
        return False
    raise ValueError(
        f'"{key}" has invalid boolean value: {trimmed}. Expected one of: 0, 1, true, false.'
    )


def url_number(key: str, value: str, minimum: float) -> float:
    """``numberConfigURLValue``: read as JavaScript's ``Number``."""
    import math

    from pyfect.schema.getter._coerce import to_number

    trimmed = value.strip()
    number = to_number(trimmed)
    if math.isnan(number):
        raise ValueError(f'"{key}" has invalid numeric value: {trimmed}')
    if number < minimum:
        raise ValueError(f'"{key}" value {trimmed} is less than min allowed {minimum:g}')
    return number


def url_log_level(key: str, value: str) -> LogLevel:
    """``enumConfigURLValue`` over ``ClickHouseLogLevel``."""
    trimmed = value.strip()
    if trimmed not in LOG_LEVELS:
        raise ValueError(
            f'"{key}" has invalid value: {trimmed}. Expected one of: {", ".join(LOG_LEVELS)}.'
        )
    return trimmed


_SAFE_FORM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*-._ ")


def form_encoded_length(entries: list[tuple[str, str]]) -> int:
    """``new URLSearchParams(entries).toString().length``."""
    total = max(len(entries) - 1, 0)
    for name, value in entries:
        for text in (name, value):
            total += sum(1 if c in _SAFE_FORM else 3 * len(text_encode(c)) for c in text)
        total += 1
    return total


__all__ = [
    "LOG_LEVELS",
    "BasicTls",
    "BrotliRequestCompression",
    "Compression",
    "CompressionCodec",
    "Compressor",
    "GzipRequestCompression",
    "Json",
    "JsonHandling",
    "KeepAlive",
    "Log",
    "LogLevel",
    "MutualTls",
    "RequestCodec",
    "RequestCompression",
    "ResponseCompression",
    "Tls",
    "TlsContext",
    "ZstdRequestCompression",
    "form_encoded_length",
    "json_handling",
    "request_codec",
    "response_codec",
    "tls_context",
    "url_boolean",
    "url_log_level",
    "url_number",
]
