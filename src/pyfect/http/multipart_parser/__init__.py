"""A streaming ``multipart/form-data`` parser (Effect's
``MultipartParser``): write the body's chunks, and it calls back with each
field's value, each file's chunks, errors, and the end.

``make(...)`` takes the request's headers (for the boundary), the
callbacks, and limits (``max_parts``, ``max_total_size``,
``max_part_size``, ``max_field_size``; 1 MiB for fields by default).
"""

from __future__ import annotations

import codecs
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Literal, Protocol

from pyfect import byte_size
from pyfect.http.multipart_parser import _content_type as ct
from pyfect.http.multipart_parser._headers import Failure, HeadersParser, Parsed, PartHeaders
from pyfect.http.multipart_parser._search import Search


@dataclass(frozen=True, slots=True)
class PartInfo:
    name: str
    filename: str | None
    content_type: str
    content_type_parameters: Mapping[str, str]
    content_disposition: str
    content_disposition_parameters: Mapping[str, str]
    headers: PartHeaders


@dataclass(frozen=True, slots=True)
class InvalidBoundary:
    tag: ClassVar[Literal["InvalidBoundary"]] = "InvalidBoundary"


@dataclass(frozen=True, slots=True)
class BadHeaders:
    error: Failure
    tag: ClassVar[Literal["BadHeaders"]] = "BadHeaders"


@dataclass(frozen=True, slots=True)
class InvalidDisposition:
    tag: ClassVar[Literal["InvalidDisposition"]] = "InvalidDisposition"


type Limit = Literal["MaxParts", "MaxTotalSize", "MaxPartSize", "MaxFieldSize"]


@dataclass(frozen=True, slots=True)
class ReachedLimit:
    limit: Limit
    tag: ClassVar[Literal["ReachedLimit"]] = "ReachedLimit"


@dataclass(frozen=True, slots=True)
class EndNotReached:
    tag: ClassVar[Literal["EndNotReached"]] = "EndNotReached"


type MultipartError = (
    InvalidBoundary | BadHeaders | InvalidDisposition | ReachedLimit | EndNotReached
)

type OnChunk = Callable[[bytes | None], None]
"""A file's chunks, then ``None`` at its end."""


class Parser(Protocol):
    def write(self, chunk: bytes) -> None: ...
    def end(self) -> None: ...


def default_is_file(info: PartInfo) -> bool:
    """A part is a file when it has a file name or is
    ``application/octet-stream``."""
    return info.filename is not None or info.content_type == "application/octet-stream"


def _limit(value: byte_size.Input | None, default: float) -> float:
    if value is None:
        return default
    if value == math.inf:
        return math.inf
    return int(byte_size.from_input_unsafe(value))


def _no_chunk(_chunk: bytes | None) -> None:
    pass


class _Noop:
    def write(self, chunk: bytes) -> None:
        pass

    def end(self) -> None:
        pass


_HEADERS, _BODY = 0, 1
_CRLF = b"\r\n"
"""The seed of the boundary search: the body's first boundary has no CRLF
before it."""


class _Parser:
    def __init__(  # noqa: PLR0917
        self,
        boundary: str,
        on_file: Callable[[PartInfo], OnChunk],
        on_field: Callable[[PartInfo, bytes], None],
        on_error: Callable[[MultipartError], None],
        on_done: Callable[[], None],
        is_file: Callable[[PartInfo], bool],
        max_parts: float,
        max_total_size: float,
        max_part_size: float,
        max_field_size: float,
    ) -> None:
        self._on_file = on_file
        self._on_field = on_field
        self._on_error = on_error
        self._on_done = on_done
        self._is_file = is_file
        self._max_parts = max_parts
        self._max_total_size = max_total_size
        self._max_part_size = max_part_size
        self._max_field_size = max_field_size
        self._header_parser = HeadersParser()
        self._split = Search(f"\r\n--{boundary}".encode(), self._on_split, _CRLF, 2)
        self._reset()

    def _reset(self) -> None:
        self._state = _HEADERS
        self._index = 0
        self._parts = 0
        self._on_chunk: OnChunk = _no_chunk
        self._info: PartInfo | None = None
        self._header_skip = 0
        self._part_size = 0
        self._total_size = 0
        self._file = False
        self._field_chunks: list[bytes] = []
        self._field_size = 0
        self._done = False
        self._stopped = False

    def _skip_body(self) -> None:
        self._state = _BODY
        self._file = True
        self._on_chunk = _no_chunk

    def _stop(self, error: MultipartError) -> None:
        self._stopped = True
        if self._state == _BODY and self._file:
            self._on_chunk(None)
        self._on_error(error)

    def _on_split(self, index: int, chunk: bytes) -> None:  # noqa: PLR0911, PLR0912, PLR0915
        if self._stopped:
            return
        if index == 0:
            # data before the first boundary
            self._skip_body()
            return
        if index != self._index:
            if self._index > 0:
                if self._file:
                    self._on_chunk(None)
                else:
                    assert self._info is not None
                    fields = self._field_chunks
                    self._on_field(self._info, fields[0] if len(fields) == 1 else b"".join(fields))
                    self._field_size = 0
                    self._field_chunks = []
            self._part_size = 0
            self._state = _HEADERS
            self._index = index
            self._header_skip = 2  # skip the first \r\n
            if chunk[:2] == b"--":
                self._done = True
                self._on_done()
                return
            self._parts += 1
            if self._parts > self._max_parts:
                self._stop(ReachedLimit("MaxParts"))
                return

        self._part_size += len(chunk)
        if self._part_size > self._max_part_size:
            self._stop(ReachedLimit("MaxPartSize"))
            return

        if self._state == _HEADERS:
            result = self._header_parser.write(chunk, self._header_skip)
            self._header_skip = 0
            if isinstance(result, Failure):
                self._skip_body()
                self._on_error(BadHeaders(result))
                return
            if not isinstance(result, Parsed):
                return
            raw_type = result.headers.get("content-type")
            content_type = ct.parse(raw_type if isinstance(raw_type, str) else None)
            disposition = ct.parse_disposition(result.headers.get("content-disposition"))
            if disposition is None or (
                disposition.value == "form-data" and "name" not in disposition.parameters
            ):
                self._skip_body()
                self._on_error(InvalidDisposition())
                return
            if content_type.value:
                part_type = content_type.value
            elif disposition.filename is not None:
                part_type = "application/octet-stream"
            else:
                part_type = "text/plain"
            info = PartInfo(
                name=disposition.parameters.get("name", ""),
                filename=disposition.filename,
                content_type=part_type,
                content_type_parameters=content_type.parameters,
                content_disposition=disposition.value,
                content_disposition_parameters=disposition.parameters,
                headers=result.headers,
            )
            self._info = info
            self._state = _BODY
            self._file = self._is_file(info)
            if self._file:
                self._on_chunk = self._on_file(info)
            if result.end_position < len(chunk):
                rest = chunk[result.end_position :]
                if self._file:
                    self._on_chunk(rest)
                else:
                    self._field_size += len(rest)
                    if self._field_size > self._max_field_size:
                        self._stop(ReachedLimit("MaxFieldSize"))
                        return
                    self._field_chunks.append(rest)
        elif self._file:
            self._on_chunk(chunk)
        else:
            self._field_size += len(chunk)
            if self._field_size > self._max_field_size:
                self._stop(ReachedLimit("MaxFieldSize"))
                return
            self._field_chunks.append(chunk)

    def write(self, chunk: bytes) -> None:
        if self._stopped:
            return
        self._total_size += len(chunk)
        if self._total_size > self._max_total_size:
            self._stop(ReachedLimit("MaxTotalSize"))
            return
        self._split.write(chunk)

    def end(self) -> None:
        self._split.end()
        if not self._done and not self._stopped:
            self._stop(EndNotReached())
        self._reset()


def make(
    *,
    headers: Mapping[str, str],
    on_file: Callable[[PartInfo], OnChunk],
    on_field: Callable[[PartInfo, bytes], None],
    on_error: Callable[[MultipartError], None],
    on_done: Callable[[], None],
    is_file: Callable[[PartInfo], bool] = default_is_file,
    max_parts: float | None = None,
    max_total_size: byte_size.Input | None = None,
    max_part_size: byte_size.Input | None = None,
    max_field_size: byte_size.Input | None = None,
) -> Parser:
    """A parser of the body ``headers`` describe. Without a boundary in
    the content type, or with one RFC 2046 does not allow (1 to 70
    characters; Effect takes any), it reports ``InvalidBoundary`` at once
    and ignores every write."""
    boundary = ct.parse(headers.get("content-type")).parameters.get("boundary")
    if boundary is None or not _BOUNDARY.fullmatch(boundary):
        on_error(InvalidBoundary())
        return _Noop()
    return _Parser(
        boundary,
        on_file,
        on_field,
        on_error,
        on_done,
        is_file,
        math.inf if max_parts is None else max_parts,
        _limit(max_total_size, math.inf),
        _limit(max_part_size, math.inf),
        _limit(max_field_size, 1024 * 1024),
    )


_BOUNDARY = re.compile(r"[0-9A-Za-z'()+_,\-./:=? ]{0,69}[0-9A-Za-z'()+_,\-./:=?]")
"""RFC 2046 §5.1.1: ``bchars``, at most 70, not ending in a space. The
search for it costs its length on every write, so the bound matters."""

_WINDOWS_1252 = frozenset({"iso-8859-1", "latin1", "latin-1", "l1", "ascii", "us-ascii"})


def _codec(charset: str) -> str:
    label = charset.strip().lower()
    if label in ("", "utf-8", "utf8"):
        return "utf-8"
    if label in _WINDOWS_1252:
        # The Encoding Standard reads these labels as windows-1252.
        return "cp1252"
    try:
        return codecs.lookup(label).name
    except LookupError:
        return "utf-8"


def decode_field(info: PartInfo, value: bytes) -> str:
    """A field's value decoded by its ``charset`` (UTF-8 by default or for
    an unknown one)."""
    return value.decode(_codec(info.content_type_parameters.get("charset", "utf-8")), "replace")


__all__ = [
    "BadHeaders",
    "EndNotReached",
    "InvalidBoundary",
    "InvalidDisposition",
    "Limit",
    "MultipartError",
    "OnChunk",
    "Parser",
    "PartInfo",
    "ReachedLimit",
    "decode_field",
    "default_is_file",
    "make",
]
