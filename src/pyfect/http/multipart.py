"""Multipart form bodies as streams of parts (Effect's ``Multipart``).

``make_channel(headers)`` parses a body's chunks into ``Field`` and
``File`` parts; ``to_persisted`` writes the files of a part stream into a
scoped temporary directory and collects the form as a ``Persisted``
mapping (a field's value, or the values of a repeated field; a file key's
``PersistedFile`` list). The limits are references the parse reads:
``MaxParts``, ``MaxFieldSize`` (10 MiB), ``MaxFileSize``,
``MaxBodySize`` (``incoming_message``) and ``FieldMimeTypes`` (parts of
these types are fields even with a file name).
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Never, TypedDict, Unpack, cast

from pyfect import byte_size
from pyfect._core import Effect, _WithFiber
from pyfect.byte_size import ByteSize
from pyfect.cause import Cause
from pyfect.channel import Channel, from_transform
from pyfect.context import Context, Reference
from pyfect.effect import catch_tag, fail, fail_cause, gen, succeed, suspend, void
from pyfect.errors import Done, TaggedError
from pyfect.file_system import FileSystem
from pyfect.http import multipart_parser as mp
from pyfect.http.incoming_message import MaxBodySize, Reviver, revive
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.path import Path
from pyfect.platform_error import PlatformError
from pyfect.pull import is_done_cause
from pyfect.schema import (
    Array,
    Bottom,
    Codec,
    SchemaError,
    Struct,
    Unknown,
    ast,
    decode_to,
    decode_unknown_effect,
    from_json_string,
    is_between_length,
)
from pyfect.schema._codec_links import link
from pyfect.schema._declare import instance_of
from pyfect.schema._options import ParseOptions
from pyfect.schema.transformation import transform
from pyfect.scope import Scope
from pyfect.stream import Stream
from pyfect.stream import from_pull as stream_from_pull
from pyfect.stream._base import require_stream

type MultipartErrorTag = Literal[
    "FileTooLarge", "FieldTooLarge", "BodyTooLarge", "TooManyParts", "InternalError", "Parse"
]

_STATUS: Mapping[MultipartErrorTag, int] = {
    "FileTooLarge": 413,
    "FieldTooLarge": 413,
    "BodyTooLarge": 413,
    "TooManyParts": 413,
    "InternalError": 500,
    "Parse": 400,
}


@dataclass(eq=False)
class MultipartErrorReason(TaggedError):
    tag: MultipartErrorTag
    cause: object = None

    @property
    def message(self) -> str:
        return self.tag


@dataclass(eq=False)
class MultipartError(TaggedError):
    """A multipart body could not be read; its response is 413 for a limit,
    400 for a malformed body, 500 otherwise. Error reporters skip it."""

    reason: MultipartErrorReason
    report_ignored: bool = True

    def __post_init__(self) -> None:
        self.cause = self.reason.cause

    @staticmethod
    def from_reason(tag: MultipartErrorTag, cause: object = None) -> MultipartError:
        return MultipartError(MultipartErrorReason(tag, cause))

    @property
    def message(self) -> str:
        return self.reason.tag

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(empty(status=_STATUS[self.reason.tag]))


def is_multipart_error(value: object) -> bool:
    return isinstance(value, MultipartError)


def _to_multipart_error(cause: object) -> MultipartError:
    return (
        cause
        if isinstance(cause, MultipartError)
        else MultipartError.from_reason("InternalError", cause)
    )


@dataclass(frozen=True, slots=True)
class Field:
    key: str
    content_type: str
    value: str
    tag: ClassVar[Literal["Field"]] = "Field"

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "@effect/platform/Multipart/Part",
            "_tag": "Field",
            "key": self.key,
            "contentType": self.content_type,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class File:
    """A file part. ``content`` streams it (once, as the body is read);
    ``content_effect`` collects it."""

    key: str
    name: str
    content_type: str
    content: Stream[bytes, MultipartError]
    tag: ClassVar[Literal["File"]] = "File"

    @property
    def content_effect(self) -> Effect[bytes, MultipartError]:
        return self.content.run_collect().map(b"".join)

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "@effect/platform/Multipart/Part",
            "_tag": "File",
            "key": self.key,
            "name": self.name,
            "contentType": self.content_type,
        }


type Part = Field | File


@dataclass(frozen=True, slots=True)
class PersistedFile:
    """A file part written to ``path``."""

    key: str
    name: str
    content_type: str
    path: str
    tag: ClassVar[Literal["PersistedFile"]] = "PersistedFile"

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "@effect/platform/Multipart/Part",
            "_tag": "PersistedFile",
            "key": self.key,
            "name": self.name,
            "contentType": self.content_type,
            "path": self.path,
        }


type Persisted = Mapping[str, list[PersistedFile] | list[str] | str]


def is_part(value: object) -> bool:
    return isinstance(value, (Field, File, PersistedFile))


def is_stream_part(value: object) -> bool:
    """A part of a parsed stream: a ``Field`` or ``File``, not a
    ``PersistedFile``."""
    return isinstance(value, (Field, File))


def is_field(value: object) -> bool:
    return isinstance(value, Field)


def is_file(value: object) -> bool:
    return isinstance(value, File)


def is_persisted_file(value: object) -> bool:
    return isinstance(value, PersistedFile)


class MaxParts(Reference[int | None]):
    """At most this many parts (``None``: no limit)."""

    @classmethod
    def default(cls) -> int | None:
        return None


class MaxFieldSize(Reference[ByteSize]):
    """At most this many bytes in a field (10 MiB)."""

    @classmethod
    def default(cls) -> ByteSize:
        return byte_size.mebibytes(10)


class MaxFileSize(Reference[ByteSize | None]):
    """At most this many bytes in a file (``None``: no limit)."""

    @classmethod
    def default(cls) -> ByteSize | None:
        return None


class FieldMimeTypes(Reference[tuple[str, ...]]):
    """Parts whose content type contains one of these are fields, even with
    a file name."""

    @classmethod
    def default(cls) -> tuple[str, ...]:
        return ("application/json",)


@dataclass(frozen=True, slots=True)
class Config:
    """What a parse reads from the fiber's references."""

    max_parts: int | None
    max_field_size: ByteSize
    max_part_size: ByteSize | None
    max_total_size: ByteSize | None
    field_mime_types: tuple[str, ...]

    def is_file(self, info: mp.PartInfo) -> bool:
        if any(mime in info.content_type for mime in self.field_mime_types):
            return False
        return mp.default_is_file(info)


def make_config() -> Effect[Config]:
    return _WithFiber(
        lambda fiber: succeed(
            Config(
                fiber.get_ref(MaxParts),
                fiber.get_ref(MaxFieldSize),
                fiber.get_ref(MaxFileSize),
                fiber.get_ref(MaxBodySize),
                fiber.get_ref(FieldMimeTypes),
            )
        )
    )


def _convert_error(error: mp.MultipartError) -> MultipartError:
    if isinstance(error, mp.ReachedLimit):
        tags: Mapping[mp.Limit, MultipartErrorTag] = {
            "MaxParts": "TooManyParts",
            "MaxFieldSize": "FieldTooLarge",
            "MaxPartSize": "FileTooLarge",
            "MaxTotalSize": "BodyTooLarge",
        }
        return MultipartError.from_reason(tags[error.limit], error)
    return MultipartError.from_reason("Parse", error)


type _Pull[A] = Effect[A, Any]


class _State:
    """One parse: the parts and file chunks the parser produced and not yet
    pulled, and how it ended (a failure, or ``Done``)."""

    def __init__(self, headers: Mapping[str, str], config: Config, upstream: _Pull[Any]) -> None:
        self.parts: list[Part] = []
        self.exit: Effect[Never, Any] | None = None
        self.ended = False
        self.upstream = upstream
        self.parser = mp.make(
            headers=headers,
            on_field=self._on_field,
            on_file=self._on_file,
            on_error=self._on_error,
            on_done=self._on_done,
            is_file=config.is_file,
            max_parts=config.max_parts,
            max_field_size=config.max_field_size,
            max_part_size=config.max_part_size,
            max_total_size=config.max_total_size,
        )

    def _on_field(self, info: mp.PartInfo, value: bytes) -> None:
        self.parts.append(Field(info.name, info.content_type, mp.decode_field(info, value)))

    def _on_error(self, error: mp.MultipartError) -> None:
        self.exit = fail(_convert_error(error))

    def _on_done(self) -> None:
        if self.exit is None:
            self.exit = fail(Done())

    def _on_file(self, info: mp.PartInfo) -> mp.OnChunk:
        chunks: list[bytes] = []
        finished = False

        def pull() -> Effect[tuple[bytes, ...], Any]:
            nonlocal chunks
            if not chunks:
                if finished:
                    return fail(Done())
                if self.exit is not None:
                    return self.exit
                return self.pump().flat_map(lambda _: pull())
            taken = tuple(chunks)
            chunks = []
            return succeed(taken)

        content = cast("Stream[bytes, Any]", stream_from_pull(succeed(suspend(pull)))).map_error(
            _to_multipart_error
        )
        self.parts.append(File(info.name, info.filename or info.name, info.content_type, content))

        def on_chunk(chunk: bytes | None) -> None:
            nonlocal finished
            if chunk is None:
                finished = True
            else:
                chunks.append(chunk)

        return on_chunk

    def pump(self) -> Effect[None]:
        def write(chunk: tuple[bytes, ...]) -> Effect[None]:
            for piece in chunk:
                self.parser.write(piece)
            return void

        def on_cause(cause: Cause[Any]) -> Effect[None]:
            if is_done_cause(cause):
                if not self.ended:
                    self.ended = True
                    self.parser.end()
            else:
                self.exit = fail_cause(cause)
            return void

        return self.upstream.flat_map(write).catch_cause(on_cause)

    def pull_parts(self) -> Effect[tuple[Part, ...], Any]:
        if not self.parts:
            if self.exit is not None:
                return self.exit
            return self.pump().flat_map(lambda _: self.pull_parts())
        taken = tuple(self.parts)
        self.parts = []
        return succeed(taken)


def make_channel[IE = Never](
    headers: Mapping[str, str],
) -> Channel[tuple[Part, ...], MultipartError | IE, None, tuple[bytes, ...], IE, None]:
    """A channel parsing the body chunks of a request with ``headers``
    into parts. A file's content must be read before the next part is
    pulled, or it is lost."""

    def transform(upstream: Any, _scope: object) -> Effect[Any, Never]:
        return make_config().map(
            lambda config: suspend(_State(headers, config, upstream).pull_parts)
        )

    return cast("Any", from_transform(cast("Any", transform)))


def collect_bytes(content: Stream[bytes, MultipartError]) -> Effect[bytes, MultipartError]:
    require_stream(content, "content")
    return content.run_collect().map(b"".join)


_MAX_PERSISTED_FILE_NAME_BYTES = 128


def persisted_file_name(base_name: str) -> str:
    """The trailing 128 UTF-8 bytes of ``base_name``, whole code points;
    an empty or dot name is ``"file"``."""
    out: list[str] = []
    size = 0
    for char in reversed(base_name):
        size += len(char.encode("utf-8", "surrogatepass"))
        if size > _MAX_PERSISTED_FILE_NAME_BYTES:
            break
        out.append(char)
    name = "".join(reversed(out))
    return "file" if name in ("", ".", "..") else name


type WriteFile = Callable[[str, File], Effect[None, MultipartError, FileSystem]]


def default_write_file(path: str, file: File) -> Effect[None, MultipartError, FileSystem]:
    def write(fs: Any) -> Effect[None, MultipartError]:
        return file.content.run(fs.sink(path)).map_error(_to_multipart_error)

    return FileSystem().flat_map(write)


def to_persisted(
    stream: Stream[Part, MultipartError], write_file: WriteFile = default_write_file
) -> Effect[Persisted, MultipartError, FileSystem | Path | Scope]:
    """Write the file parts of ``stream`` into a temporary directory (removed
    with the scope) and collect the form. Files with an empty name are
    skipped; equal names get a numbered prefix."""
    require_stream(stream, "stream")

    def body():
        fs = yield from FileSystem()
        path_ = yield from Path()
        directory = yield from fs.make_temp_directory_scoped()
        persisted: dict[str, list[PersistedFile] | list[str] | str] = {}
        used: set[str] = set()
        index = 0

        def each(part: Part) -> Effect[None, MultipartError, FileSystem]:
            nonlocal index
            if isinstance(part, Field):
                current = persisted.get(part.key)
                if current is None:
                    persisted[part.key] = part.value
                elif isinstance(current, str):
                    persisted[part.key] = [current, part.value]
                else:
                    cast("list[str]", current).append(part.value)
                return void
            if part.name == "":
                return void
            name = persisted_file_name(path_.basename(part.name))
            path = path_.join(directory, name)
            while path in used:
                path = path_.join(directory, f"{index}-{name}")
                index += 1
            used.add(path)
            file = PersistedFile(part.key, part.name, part.content_type, path)
            current = persisted.get(part.key)
            if isinstance(current, list):
                cast("list[PersistedFile]", current).append(file)
            else:
                persisted[part.key] = [file]
            return write_file(path, part)

        yield from stream.run_for_each(each)
        return cast("Persisted", persisted)

    def on_platform_error(error: object) -> Effect[Never, MultipartError]:
        return fail(MultipartError.from_reason("InternalError", error))

    eff: Effect[Persisted, MultipartError | PlatformError, FileSystem | Path | Scope] = gen(body)
    return eff.pipe(catch_tag(PlatformError, on_platform_error))


class Limits(TypedDict, total=False):
    max_parts: int
    max_field_size: byte_size.Input
    max_file_size: byte_size.Input
    max_total_size: byte_size.Input
    field_mime_types: Sequence[str]


def limits_context(**options: Unpack[Limits]) -> Context[Never]:
    """The references of the limits given (Effect's ``limitsServices``)."""
    ctx: Context[Any] = Context.empty()
    if "max_parts" in options:
        ctx = ctx.add(MaxParts, options["max_parts"])
    if "max_field_size" in options:
        ctx = ctx.add(MaxFieldSize, byte_size.from_input_unsafe(options["max_field_size"]))
    if "max_file_size" in options:
        ctx = ctx.add(MaxFileSize, byte_size.from_input_unsafe(options["max_file_size"]))
    if "max_total_size" in options:
        ctx = ctx.add(MaxBodySize, byte_size.from_input_unsafe(options["max_total_size"]))
    if "field_mime_types" in options:
        ctx = ctx.add(FieldMimeTypes, tuple(options["field_mime_types"]))
    return ctx


def schema_persisted[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Callable[[object], Effect[T, SchemaError, RD]]:
    """A decoder of a ``Persisted`` form by ``schema``."""
    return decode_unknown_effect(schema, **options)


def schema_json[T, RD](
    schema: Codec[T, Any, RD, Any],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> Callable[[Persisted, str], Effect[T, SchemaError, RD]]:
    """A decoder of the JSON text in a form's ``field`` by ``schema``; with a
    ``reviver`` the text is parsed with it."""
    from_json: Any = from_json_string(schema if reviver is None else Unknown)
    then = decode_unknown_effect(schema, **options)

    def decode(persisted: Persisted, field: str) -> Effect[T, SchemaError, RD]:
        fields: Any = cast("Any", TypedDict)("Fields", {field: object})
        struct: Any = Struct(fields, **{field: from_json})
        decoded = decode_unknown_effect(struct, **options)(persisted)
        if reviver is None:
            return decoded.map(lambda record: record[field])
        revive_with = reviver
        return decoded.flat_map(lambda record: then(revive(record[field], revive_with)))

    return decode


def _persisted_file_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    encoded = ast.Objects(
        (
            ast.PropertySignature("key", ast.string),
            ast.PropertySignature("name", ast.string),
            ast.PropertySignature(
                "contentType", ast.annotate(ast.string, {"content_encoding": "binary"})
            ),
            ast.PropertySignature("path", ast.string),
        )
    )

    def decode(value: Mapping[str, str]) -> PersistedFile:
        return PersistedFile(value["key"], value["name"], value["contentType"], value["path"])

    def encode(file: PersistedFile) -> Mapping[str, str]:
        return {
            "key": file.key,
            "name": file.name,
            "contentType": file.content_type,
            "path": file.path,
        }

    return link(encoded, decode=decode, encode=encode)


PersistedFileSchema: Bottom[PersistedFile] = instance_of(
    PersistedFile, expected="PersistedFile", to_codec_json=_persisted_file_codec
)
"""A ``PersistedFile``; as JSON, its ``key``, ``name``, ``contentType``
and ``path``."""

FilesSchema = Array(PersistedFileSchema)
"""The files of a field."""


def _single(files: tuple[PersistedFile, ...]) -> PersistedFile:
    return files[0]


def _one(file: PersistedFile) -> tuple[PersistedFile, ...]:
    return (file,)


SingleFileSchema = FilesSchema.check(is_between_length(1, 1)).pipe(
    decode_to(PersistedFileSchema, transform(decode=_single, encode=_one))
)
"""Exactly one file: a one-element file array, decoded to the file."""


__all__ = [
    "Config",
    "Field",
    "FieldMimeTypes",
    "File",
    "FilesSchema",
    "Limits",
    "MaxFieldSize",
    "MaxFileSize",
    "MaxParts",
    "MultipartError",
    "MultipartErrorReason",
    "MultipartErrorTag",
    "Part",
    "Persisted",
    "PersistedFile",
    "PersistedFileSchema",
    "SingleFileSchema",
    "WriteFile",
    "collect_bytes",
    "default_write_file",
    "is_field",
    "is_file",
    "is_multipart_error",
    "is_part",
    "is_persisted_file",
    "is_stream_part",
    "limits_context",
    "make_channel",
    "make_config",
    "persisted_file_name",
    "schema_json",
    "schema_persisted",
    "to_persisted",
]
