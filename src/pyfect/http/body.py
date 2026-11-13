"""Request bodies (Effect's ``HttpBody``).

A body is one of ``Empty``, ``Raw`` (anything the client sends as is),
``Bytes`` (bytes with a content type and length), ``FormData`` (a multipart
form) or ``Stream`` (a byte stream, sent as it is pulled)::

    body.text("hello")                    # text/plain
    body.json_unsafe({"id": 1})           # application/json
    body.stream(chunks, "text/csv")       # streamed
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Literal, Unpack, cast, final

from pyfect import byte_size
from pyfect._js import js_number, text_encode
from pyfect._json_text import STRINGIFY_ERRORS, stringify
from pyfect.effect import Effect, fail, succeed, suspend
from pyfect.errors import TaggedError
from pyfect.file_system import FileInfo, FileSystem, FileSystemService
from pyfect.http import url_params as _url_params
from pyfect.http.headers import Headers
from pyfect.platform_error import PlatformError, bad_argument
from pyfect.schema import Codec, SchemaError, encode_unknown_effect, to_codec_json
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import Issue
from pyfect.stream import Stream as Stream_
from pyfect.stream._base import require_stream


@final
@dataclass(frozen=True, slots=True)
class Empty:
    tag: ClassVar[Literal["Empty"]] = "Empty"
    content_type: ClassVar[None] = None
    content_length: ClassVar[None] = None

    def to_json(self) -> dict[str, object]:
        return {"_id": "effect/HttpBody", "_tag": "Empty"}


@final
@dataclass(frozen=True, slots=True)
class Raw:
    """A body the client hands to its transport as is (bytes, ``str``, an
    iterable of bytes)."""

    body: object
    content_type: str | None = None
    content_length: int | None = None
    tag: ClassVar[Literal["Raw"]] = "Raw"

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "effect/HttpBody",
            "_tag": "Raw",
            "body": self.body,
            "content_type": self.content_type,
            "content_length": self.content_length,
        }


@final
@dataclass(frozen=True, slots=True, eq=False)
class Bytes:
    """Bytes with their content type and length (Effect's ``Uint8Array``
    body). ``text`` is the text they were encoded from, if any."""

    body: bytes
    content_type: str
    content_length: int
    text: str | None = None
    tag: ClassVar[Literal["Bytes"]] = "Bytes"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Bytes):
            return NotImplemented
        return (self.body, self.content_type) == (other.body, other.content_type)

    def __hash__(self) -> int:
        return hash((self.body, self.content_type))

    def to_json(self) -> dict[str, object]:
        readable = self.content_type.startswith("text/") or self.content_type.endswith("json")
        return {
            "_id": "effect/HttpBody",
            "_tag": "Bytes",
            "body": self.body.decode("utf-8", "replace")
            if readable
            else f"bytes({len(self.body)})",
            "content_type": self.content_type,
            "content_length": self.content_length,
        }


type FileContent = bytes | Callable[[], Stream_[bytes, object]]
"""A form file's bytes, or a function opening a stream of them each time the
form is sent (a web ``File``'s ``stream()``): read on demand, as the
connection takes them."""


@dataclass(eq=False)
class FileSourceError(TaggedError):
    """A form file's stream could not be opened, or failed while read.
    A client fails the request with a ``TransportError`` caused by
    ``cause``."""

    cause: object


@final
@dataclass(frozen=True, slots=True)
class File:
    """A file part of a form: its content, file name and content type."""

    content: FileContent
    name: str = "blob"
    content_type: str = "application/octet-stream"

    def stream(self) -> Stream_[bytes, FileSourceError]:
        """The content; a source is opened when the stream runs, and its
        raise or failure is a ``FileSourceError``."""
        from pyfect import stream as _stream

        content = self.content
        if isinstance(content, bytes):
            return _stream.succeed(content)
        source = content

        def open_source() -> Stream_[bytes, FileSourceError]:
            try:
                opened = source()
            except Exception as error:
                return _stream.fail(FileSourceError(error))
            return opened.map_error(FileSourceError)

        return _stream.suspend(open_source)


type FormDataValue = str | File


@final
@dataclass(frozen=True, slots=True)
class FormData:
    """A multipart form: ``(name, value)`` entries in order. The client
    writes the ``multipart/form-data`` content type with its boundary."""

    entries: tuple[tuple[str, FormDataValue], ...] = ()
    tag: ClassVar[Literal["FormData"]] = "FormData"
    content_type: ClassVar[None] = None
    content_length: ClassVar[None] = None

    def append(self, name: str, value: FormDataValue) -> FormData:
        return FormData((*self.entries, (name, value)))

    def get_all(self, name: str) -> list[FormDataValue]:
        return [v for k, v in self.entries if k == name]

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "effect/HttpBody",
            "_tag": "FormData",
            "entries": [k for k, _ in self.entries],
        }


@final
@dataclass(frozen=True, slots=True)
class Stream:
    """A byte stream, sent as it is pulled. Its failure fails the request
    with an ``EncodeError``."""

    stream: Stream_[bytes, object]
    content_type: str = "application/octet-stream"
    content_length: int | None = None
    tag: ClassVar[Literal["Stream"]] = "Stream"

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "effect/HttpBody",
            "_tag": "Stream",
            "content_type": self.content_type,
            "content_length": self.content_length,
        }


type HttpBody = Empty | Raw | Bytes | FormData | Stream

EMPTY: Empty = Empty()


@final
@dataclass(frozen=True, slots=True)
class JsonError:
    tag: ClassVar[Literal["JsonError"]] = "JsonError"


@final
@dataclass(frozen=True, slots=True)
class SchemaErrorReason:
    issue: Issue
    tag: ClassVar[Literal["SchemaError"]] = "SchemaError"


@dataclass(eq=False)
class HttpBodyError(TaggedError):
    """A body could not be encoded: the value has no JSON form, or a schema
    rejected it."""

    reason: JsonError | SchemaErrorReason
    cause: object = field(default=None)

    @property
    def message(self) -> str:
        return self.reason.tag


def raw(body: object, *, content_type: str | None = None, content_length: int | None = None) -> Raw:
    return Raw(body, content_type, content_length)


def bytes_(body: bytes, content_type: str | None = None) -> Bytes:
    """Bytes, ``application/octet-stream`` unless ``content_type`` says
    otherwise (Effect's ``uint8Array``)."""
    return Bytes(body, content_type or "application/octet-stream", len(body))


def text(body: str, content_type: str | None = None) -> Bytes:
    """UTF-8 text (a lone surrogate becomes U+FFFD), ``text/plain`` by
    default."""
    encoded = text_encode(body)
    return Bytes(encoded, content_type or "text/plain", len(encoded), body)


def json_unsafe(body: object, content_type: str | None = None) -> Bytes:
    """``body`` as ``JSON.stringify`` writes it (``NaN`` as ``null``);
    raises when it has no JSON form."""
    return text(stringify(body), content_type or "application/json")


def json(body: object, content_type: str | None = None) -> Effect[Bytes, HttpBodyError]:
    """``body`` as JSON, failing with a ``JsonError`` when it has no JSON
    form."""

    def encode() -> Effect[Bytes, HttpBodyError]:
        try:
            return succeed(json_unsafe(body, content_type))
        except STRINGIFY_ERRORS as cause:
            return fail(HttpBodyError(JsonError(), cause))

    return suspend(encode)


def json_schema[T, RE](
    schema: Codec[T, object, object, RE], **options: Unpack[ParseOptions]
) -> Callable[[T, str | None], Effect[Bytes, HttpBodyError, RE]]:
    """An encoder of ``schema``'s values to JSON bodies; a value the schema
    rejects fails with a ``SchemaError`` reason."""
    encode = encode_unknown_effect(to_codec_json(schema), **options)

    def to_error(error: SchemaError) -> HttpBodyError:
        return HttpBodyError(SchemaErrorReason(error.issue), error.issue)

    def encode_body(value: T, content_type: str | None = None) -> Effect[Bytes, HttpBodyError, RE]:
        return (
            encode(value).map_error(to_error).flat_map(lambda encoded: json(encoded, content_type))
        )

    return encode_body


def url_params(input: _url_params.Input, content_type: str | None = None) -> Bytes:
    """The parameters form-encoded, ``application/x-www-form-urlencoded`` by
    default."""
    return text(_url_params.to_string(input), content_type or "application/x-www-form-urlencoded")


def form_data(body: FormData) -> FormData:
    return body


type FormDataCoercible = str | int | float | bool | File | None
type FormDataInput = Mapping[str, FormDataCoercible | Sequence[FormDataCoercible]]


def _form_value(value: object) -> FormDataValue:
    """``FormData.append``: a generated multipart type's object field is
    stringified as JavaScript does."""
    match value:
        case str() | File():
            return value
        case bool():
            return "true" if value else "false"
        case int() | float():
            return js_number(value)
        case _:
            return "[object Object]"


def form_data_record(entries: FormDataInput) -> FormData:
    """A form from a mapping; a sequence value adds one entry per item and
    ``None`` adds none."""
    out: list[tuple[str, FormDataValue]] = []
    for key, value in entries.items():
        values = (
            cast("Sequence[FormDataCoercible]", value)
            if isinstance(value, (list, tuple))
            else (cast("FormDataCoercible", value),)
        )
        out.extend((key, _form_value(v)) for v in values if v is not None)
    return FormData(tuple(out))


def stream(
    body: Stream_[bytes, object], content_type: str | None = None, content_length: int | None = None
) -> Stream:
    require_stream(body, "body")
    return Stream(body, content_type or "application/octet-stream", content_length)


_MAX_SAFE_INTEGER = 2**53 - 1
"""Content lengths stay exact JavaScript numbers, as in Effect."""


def _range_size(
    value: byte_size.Input | None, name: str, method: str
) -> Effect[int | None, PlatformError]:
    if value is None:
        return succeed(None)
    size = byte_size.from_input(value)
    if size is None:
        return fail(
            bad_argument(module="HttpBody", method=method, description=f"Invalid {name}: {value}")
        )
    return succeed(int(size))


def _file_body(
    fs: FileSystemService,
    path: str,
    size: int,
    method: str,
    *,
    bytes_to_read: byte_size.Input | None,
    chunk_size: int | None,
    offset: byte_size.Input | None,
    content_type: str | None,
) -> Effect[Stream, PlatformError]:
    def make(start: int, most: int | None) -> Effect[Stream, PlatformError]:
        available = max(size - start, 0)
        length = available if most is None or most > available else most
        if length > _MAX_SAFE_INTEGER:
            return fail(
                bad_argument(
                    module="HttpBody",
                    method=method,
                    description=f"Content length exceeds Number.MAX_SAFE_INTEGER: {length}",
                )
            )
        chunks = (
            fs.stream(path, offset=start, bytes_to_read=most)
            if chunk_size is None
            else fs.stream(path, offset=start, bytes_to_read=most, chunk_size=chunk_size)
        )
        return succeed(stream(chunks, content_type, length))

    return _range_size(offset, "offset", method).flat_map(
        lambda start: _range_size(bytes_to_read, "bytesToRead", method).flat_map(
            lambda most: make(start or 0, most)
        )
    )


def file_from_info(
    path: str,
    info: FileInfo,
    *,
    bytes_to_read: byte_size.Input | None = None,
    chunk_size: int | None = None,
    offset: byte_size.Input | None = None,
    content_type: str | None = None,
) -> Effect[Stream, PlatformError, FileSystem]:
    """A stream body of the file at ``path`` whose ``info`` is known."""
    return FileSystem().flat_map(
        lambda fs: _file_body(
            fs,
            path,
            int(info.size),
            "fileFromInfo",
            bytes_to_read=bytes_to_read,
            chunk_size=chunk_size,
            offset=offset,
            content_type=content_type,
        )
    )


def file(
    path: str,
    *,
    bytes_to_read: byte_size.Input | None = None,
    chunk_size: int | None = None,
    offset: byte_size.Input | None = None,
    content_type: str | None = None,
) -> Effect[Stream, PlatformError, FileSystem]:
    """A stream body of the file at ``path``, its length from ``stat``."""
    return FileSystem().flat_map(
        lambda fs: fs.stat(path).flat_map(
            lambda info: _file_body(
                fs,
                path,
                int(info.size),
                "file",
                bytes_to_read=bytes_to_read,
                chunk_size=chunk_size,
                offset=offset,
                content_type=content_type,
            )
        )
    )


def update_headers(headers: Headers, body: HttpBody) -> Headers:
    """``headers`` with ``content-type`` / ``content-length`` matching
    ``body`` (removed for ``Empty`` and ``FormData``)."""
    if isinstance(body, (Empty, FormData)):
        return headers.remove_many(("content-type", "content-length"))
    headers = (
        headers.remove("content-type")
        if body.content_type is None
        else headers.set("content-type", body.content_type)
    )
    return update_content_length(headers, body)


def update_content_length(headers: Headers, body: HttpBody) -> Headers:
    """``headers`` with ``content-length`` matching ``body`` (removed for
    ``Empty``, ``FormData`` and a body of unknown length)."""
    length = None if isinstance(body, (Empty, FormData)) else body.content_length
    if length is None:
        return headers.remove("content-length")
    return headers.set("content-length", str(length))


__all__ = [
    "EMPTY",
    "Bytes",
    "Empty",
    "File",
    "FileContent",
    "FileSourceError",
    "FormData",
    "FormDataCoercible",
    "FormDataInput",
    "FormDataValue",
    "HttpBody",
    "HttpBodyError",
    "JsonError",
    "PlatformError",
    "Raw",
    "SchemaErrorReason",
    "Stream",
    "bytes_",
    "file",
    "file_from_info",
    "form_data",
    "form_data_record",
    "json",
    "json_schema",
    "json_unsafe",
    "raw",
    "stream",
    "text",
    "update_content_length",
    "update_headers",
    "url_params",
]
