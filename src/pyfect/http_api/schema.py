"""How endpoint schemas meet HTTP (Effect's ``HttpApiSchema``): the status
of a response, its encoding (JSON, form, text, bytes, multipart), empty
responses, streams, upgrades and response headers.

Annotations are read from a schema's node: ``http_api_status`` (the
status), ``http_api_encoding`` (an ``Encoding``) and
``http_api_with_headers`` (``encode_to_with_headers``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Never,
    NotRequired,
    TypedDict,
    TypeIs,
    Unpack,
    cast,
    overload,
)

from pyfect import byte_size
from pyfect.byte_size import ByteSize
from pyfect.http import status as http_status
from pyfect.http.method import HttpMethod, has_body
from pyfect.http.multipart import Limits
from pyfect.http.status import StatusLiteral
from pyfect.schema import (
    Bottom,
    Codec,
    Null,
    Struct,
    Top,
    ast,
    decode_to,
    from_json_string,
    instance_of,
    to_type,
)
from pyfect.schema import transformation as T
from pyfect.socket import SocketService
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.encoding.sse import Retry, SseError
    from pyfect.http.body import FormData
    from pyfect.http.error import HttpClientError
    from pyfect.http.headers import Headers
    from pyfect.http.multipart import MultipartError, Part
    from pyfect.http_api.error import HttpApiPayloadTooLarge, HttpApiSchemaError
    from pyfect.schema import SchemaError

# --- encodings ---------------------------------------------------------------------

type ResponseEncodingTag = Literal["Json", "FormUrlEncoded", "Uint8Array", "Text"]


@dataclass(frozen=True, slots=True)
class ResponseEncoding:
    """A body written as ``tag`` with the ``content_type`` header."""

    tag: ResponseEncodingTag
    content_type: str


@dataclass(frozen=True, slots=True)
class MultipartEncoding:
    """A ``multipart/form-data`` request body, parsed whole (``"buffered"``)
    or handed to the handler as a stream of parts."""

    mode: Literal["buffered", "stream"]
    content_type: str
    limits: Limits | None = None
    tag: Literal["Multipart"] = "Multipart"


type PayloadEncoding = ResponseEncoding | MultipartEncoding

_DEFAULT_CONTENT_TYPES: Mapping[str, str] = {
    "Multipart": "multipart/form-data",
    "Json": "application/json",
    "FormUrlEncoded": "application/x-www-form-urlencoded",
    "Uint8Array": "application/octet-stream",
    "Text": "text/plain",
}

_JSON = ResponseEncoding("Json", "application/json")
_FORM = ResponseEncoding("FormUrlEncoded", "application/x-www-form-urlencoded")


def _annotation(node: ast.AST, key: str) -> object:
    return (node.resolve() or {}).get(key)


def encoding_of(node: ast.AST) -> PayloadEncoding | None:
    """The ``http_api_encoding`` annotation of ``node``."""
    return cast("PayloadEncoding | None", _annotation(node, "http_api_encoding"))


def get_payload_encoding(node: ast.AST, method: HttpMethod) -> PayloadEncoding:
    """A payload's encoding: its annotation, else JSON for a method with a
    body and a query string for one without."""
    encoding = encoding_of(node)
    if encoding is not None:
        return encoding
    return _JSON if has_body(method) else _FORM


def get_response_encoding(node: ast.AST) -> ResponseEncoding:
    """A response's encoding: its annotation, else JSON. Multipart is a
    ``ValueError``."""
    encoding = encoding_of(node) or _JSON
    if isinstance(encoding, MultipartEncoding):
        raise ValueError("Multipart is not supported in response")
    return encoding


class _Annotate:
    """Annotate any schema, keeping its kind (a class becomes its schema)."""

    __slots__ = ("annotations", "key")

    def __init__(self, annotations: Mapping[str, object], *, key: bool = False) -> None:
        self.annotations = annotations
        self.key = key

    @overload
    def __call__[B: Bottom[Any, Any, Any, Any]](self, schema: B, /) -> B: ...
    @overload
    def __call__[A, I, RD, RE](self, schema: Codec[A, I, RD, RE], /) -> Bottom[A, I, RD, RE]: ...
    def __call__(self, schema: Codec[Any, Any, Any, Any], /) -> Bottom[Any, Any, Any, Any]:
        codec = schema.__codec__()
        if self.key:
            return codec.annotate_key(**self.annotations)
        return codec.annotate(**self.annotations)


def _encoding(encoding: PayloadEncoding) -> _Annotate:
    return _Annotate({"http_api_encoding": encoding})


def as_json(*, content_type: str = "application/json") -> _Annotate:
    """Encode the body as JSON (the default). Use with ``.pipe``."""
    return _encoding(ResponseEncoding("Json", content_type))


def as_form_url_encoded(*, content_type: str = "application/x-www-form-urlencoded") -> _Annotate:
    """Encode the body as URL parameters. Use with ``.pipe``."""
    return _encoding(ResponseEncoding("FormUrlEncoded", content_type))


def as_text(*, content_type: str = "text/plain") -> _Annotate:
    """Send the encoded string as the body. Use with ``.pipe``."""
    return _encoding(ResponseEncoding("Text", content_type))


def as_uint8_array(*, content_type: str = "application/octet-stream") -> _Annotate:
    """Send the encoded bytes as the body. Use with ``.pipe``."""
    return _encoding(ResponseEncoding("Uint8Array", content_type))


@dataclass(frozen=True, slots=True, eq=False)
class MultipartSchema[A, RD = Never](Bottom[A, Any, RD, Never]):
    """A payload read from a parsed ``multipart/form-data`` body; the
    client sends a ``FormData``."""

    if TYPE_CHECKING:

        @property
        def http_api_payload(self) -> A: ...
        @property
        def http_api_payload_client(self) -> FormData: ...


@dataclass(frozen=True, slots=True, eq=False)
class MultipartStreamSchema(Bottom[Stream[Any, Any], Any, Never, Never]):
    """A ``multipart/form-data`` payload handed to the handler as a stream
    of parts; the client sends a ``FormData``."""

    if TYPE_CHECKING:

        @property
        def http_api_payload(self) -> Stream[Part, MultipartError]: ...
        @property
        def http_api_payload_client(self) -> FormData: ...


def as_multipart[A, RD](
    schema: Codec[A, Any, RD, Any], /, **limits: Unpack[Limits]
) -> MultipartSchema[A, RD]:
    """``schema`` read from a parsed ``multipart/form-data`` body (files
    persisted first), within ``limits``."""
    encoding = MultipartEncoding("buffered", "multipart/form-data", limits or None)
    return MultipartSchema(schema.__codec__().annotate(http_api_encoding=encoding).ast)


def as_multipart_stream(schema: Top, /, **limits: Unpack[Limits]) -> MultipartStreamSchema:
    """A ``multipart/form-data`` body as a stream of parts, within
    ``limits``; ``schema`` documents the form (its files binary)."""
    encoding = MultipartEncoding("stream", "multipart/form-data", limits or None)
    documented = schema.__codec__().ast
    annotated = _STREAM.annotate(http_api_encoding=encoding, http_api_documented=documented)
    return MultipartStreamSchema(annotated.ast)


def documented_node(node: ast.AST) -> ast.AST:
    """The schema documenting ``node``'s body: the form of a multipart
    stream, otherwise ``node``."""
    documented = (node.annotations or {}).get("http_api_documented")
    return documented if isinstance(documented, ast.AST) else node


def is_multipart_stream(schema: Top) -> bool:
    encoding = encoding_of(schema.__codec__().ast)
    return isinstance(encoding, MultipartEncoding) and encoding.mode == "stream"


# --- status --------------------------------------------------------------------------


def _status_annotations(node: ast.AST | ast.FilterGroup[Any]) -> Mapping[str, object] | None:
    for check in reversed(node.checks or ()):
        if check.annotations and "http_api_status" in check.annotations:
            return check.annotations
        if isinstance(check, ast.FilterGroup):
            found = _status_annotations(check)
            if found is not None:
                return found
    annotations = node.annotations
    return annotations if annotations and "http_api_status" in annotations else None


def resolve_status(node: ast.AST) -> int | None:
    """The ``http_api_status`` of ``node`` or of the key holding it."""
    annotations = _status_annotations(node)
    if annotations is not None:
        return cast("int | None", annotations["http_api_status"])
    return cast("int | None", (node.key_annotations or {}).get("http_api_status"))


def status(code: int | StatusLiteral) -> _Annotate:
    """Respond with ``code`` (a number or a name like ``"Created"``) when
    the schema encodes the value. Use with ``.pipe``."""
    number = http_status.from_literal(code) if isinstance(code, str) else code
    return _StatusAnnotate(number)


class _StatusAnnotate(_Annotate):
    """``status``: on the key when the schema has no status yet, so the
    schema itself is unchanged (Effect annotates the key context)."""

    __slots__ = ()

    def __init__(self, code: int) -> None:
        super().__init__({"http_api_status": code})

    def __call__(self, schema: Codec[Any, Any, Any, Any], /) -> Bottom[Any, Any, Any, Any]:
        codec = schema.__codec__()
        if _status_annotations(codec.ast) is None:
            return codec.annotate_key(**self.annotations)
        return codec.annotate(**self.annotations)


def get_status_success(node: ast.AST) -> int:
    return resolve_status(node) or 200


def get_status_error(node: ast.AST) -> int:
    return resolve_status(node) or 500


def is_with_headers(value: object) -> TypeIs[WithHeadersSchema[Any, Any]]:
    return isinstance(value, WithHeadersSchema)


def is_upgrade(value: object) -> TypeIs[UpgradeSchema[Any]]:
    return isinstance(value, UpgradeSchema)


def body_of(schema: Top) -> Top:
    """The body schema of a ``WithHeaders`` response, else ``schema``."""
    if is_with_headers(schema):
        return schema.schema
    return schema


def get_status_success_schema(schema: Top) -> int:
    """The status a success schema responds with (default 200)."""
    if is_with_headers(schema):
        return resolve_status(schema.ast) or get_status_success(body_of(schema).__codec__().ast)
    return get_status_success(schema.__codec__().ast)


def get_status_error_schema(schema: Top) -> int:
    """The status an error schema responds with (default 500)."""
    if is_with_headers(schema):
        return resolve_status(schema.ast) or get_status_error(body_of(schema).__codec__().ast)
    return get_status_error(schema.__codec__().ast)


def get_response_encoding_schema(schema: Top) -> ResponseEncoding:
    if is_with_headers(schema) and encoding_of(schema.ast) is None:
        return get_response_encoding(body_of(schema).__codec__().ast)
    return get_response_encoding(schema.__codec__().ast)


# --- empty responses -----------------------------------------------------------------

Void: Bottom[None] = Null.annotate(http_api_void=True)
"""No body (Effect's ``Schema.Void``): ``None``, sent as an empty body."""


def _is_void(node: ast.AST) -> bool:
    return (node.annotations or {}).get("http_api_void") is True


def is_no_content(node: ast.AST) -> bool:
    """``node`` is (or is encoded to) ``Void``: the response has no body."""
    if _is_void(node) or _is_void(ast.to_encoded(node)):
        return True
    return node.encoding is not None and _is_void(node.encoding[0].to)


def Empty(code: int) -> Bottom[None]:
    """No body, with status ``code``."""
    return status(code)(Void)


NoContent: Bottom[None] = Empty(204)
Created: Bottom[None] = Empty(201)
Accepted: Bottom[None] = Empty(202)


def as_no_content[A](
    schema: Codec[A, Any, Any, Any], /, *, decode: Callable[[], A]
) -> Bottom[A, None]:
    """``schema``'s values sent as an empty body; a client makes the value
    with ``decode()``."""
    transformation: T.Transformation[A, None] = T.transform(
        decode=lambda _: decode(), encode=lambda _: None
    )
    return Void.pipe(decode_to(to_type(schema), transformation))


# --- streams -------------------------------------------------------------------------

_STREAM = cast("Bottom[Stream[Any, Any]]", instance_of(Stream))

type StreamSseMode = Literal["events", "data"]


@dataclass(frozen=True, slots=True, eq=False)
class StreamSseSchema[A, E = Never](Bottom[Stream[A, E], Stream[A, E], Never, Never]):
    """A ``text/event-stream`` response: the handler returns a stream of
    events (``sse_mode="events"``) or of their data (``"data"``); a
    failure of the stream is sent as an event the client fails with."""

    sse_mode: StreamSseMode = field(kw_only=True)
    content_type: str = field(kw_only=True)
    events: Codec[Any, Mapping[str, object], Any, Any] = field(kw_only=True)
    error: Top = field(kw_only=True)

    if TYPE_CHECKING:

        @property
        def http_api_success_client(
            self,
        ) -> Stream[A, E | HttpClientError | SchemaError | Retry | SseError]: ...


@dataclass(frozen=True, slots=True, eq=False)
class StreamUint8ArraySchema(Bottom[Stream[bytes, Any], Stream[bytes, Any], Never, Never]):
    """A byte stream body; as a payload, at most ``max_bytes``."""

    content_type: str = field(kw_only=True)
    max_bytes: ByteSize | None = field(kw_only=True)

    if TYPE_CHECKING:

        @property
        def http_api_success_client(self) -> Stream[bytes, HttpClientError]: ...
        @property
        def http_api_payload(self) -> Stream[bytes, HttpApiPayloadTooLarge]: ...
        @property
        def http_api_payload_client(self) -> Stream[bytes, Any]: ...


@dataclass(frozen=True, slots=True, eq=False)
class StreamNdjsonSchema[A](Bottom[Stream[A, Any], Stream[A, Any], Never, Never]):
    """A newline-delimited JSON body, one ``schema`` value a line; as a
    payload, at most ``max_bytes`` and ``max_element_bytes`` a line."""

    content_type: str = field(kw_only=True)
    schema: Codec[A, Any, Any, Any] = field(kw_only=True)
    max_bytes: ByteSize | None = field(kw_only=True)
    max_element_bytes: ByteSize = field(kw_only=True)

    if TYPE_CHECKING:

        @property
        def http_api_success_client(self) -> Stream[A, HttpClientError | SchemaError]: ...
        @property
        def http_api_payload(self) -> Stream[A, HttpApiSchemaError | HttpApiPayloadTooLarge]: ...
        @property
        def http_api_payload_client(self) -> Stream[A, Any]: ...


type StreamSchema = StreamSseSchema[Any, Any] | StreamUint8ArraySchema | StreamNdjsonSchema[Any]

_DEFAULT_MAX_ELEMENT_BYTES = byte_size.mebibytes(1)
RESERVED_STREAM_FAILURE_EVENT = "effect/http-api/stream/failure"


def _sizes(value: byte_size.Input | None) -> ByteSize | None:
    return None if value is None else byte_size.from_input_unsafe(value)


@overload
def StreamSse[A, E = Never](
    *,
    events: Codec[A, Mapping[str, object], Any, Any],
    error: Codec[E, Any, Any, Any] | None = None,
    content_type: str = "text/event-stream",
) -> StreamSseSchema[A, E]: ...
@overload
def StreamSse[A, E = Never](
    *,
    data: Codec[A, Any, Any, Any],
    error: Codec[E, Any, Any, Any] | None = None,
    content_type: str = "text/event-stream",
) -> StreamSseSchema[A, E]: ...
def StreamSse(
    *,
    events: Codec[Any, Mapping[str, object], Any, Any] | None = None,
    data: Codec[Any, Any, Any, Any] | None = None,
    error: Codec[Any, Any, Any, Any] | None = None,
    content_type: str = "text/event-stream",
) -> StreamSseSchema[Any, Any]:
    """Server-sent events: each decoded by ``events`` from its fields
    (``event``, ``data``, ``id``), or ``message`` events whose JSON data
    ``data`` decodes (the stream is of the data values). ``error`` encodes
    the stream's failure, sent as a reserved event."""
    if data is not None:
        events = Struct(_SseDataFields, data=from_json_string(data))
    elif events is None:
        raise TypeError("StreamSse needs events or data")
    return StreamSseSchema(
        _STREAM.ast,
        sse_mode="data" if data is not None else "events",
        content_type=content_type,
        events=events,
        error=error if error is not None else _NEVER,
    )


def StreamUint8Array(
    *, content_type: str = "application/octet-stream", max_bytes: byte_size.Input | None = None
) -> StreamUint8ArraySchema:
    """A byte stream body; as a payload, at most ``max_bytes``."""
    return StreamUint8ArraySchema(
        _STREAM.ast, content_type=content_type, max_bytes=_sizes(max_bytes)
    )


def StreamNdjson[A](
    schema: Codec[A, Any, Any, Any],
    *,
    content_type: str = "application/x-ndjson",
    max_bytes: byte_size.Input | None = None,
    max_element_bytes: byte_size.Input | None = None,
) -> StreamNdjsonSchema[A]:
    """Newline-delimited JSON of ``schema`` values; a line is at most
    ``max_element_bytes`` (1 MiB)."""
    return StreamNdjsonSchema(
        _STREAM.ast,
        content_type=content_type,
        schema=schema,
        max_bytes=_sizes(max_bytes),
        max_element_bytes=_sizes(max_element_bytes) or _DEFAULT_MAX_ELEMENT_BYTES,
    )


def is_stream_payload(
    value: object,
) -> TypeIs[StreamUint8ArraySchema | StreamNdjsonSchema[Any]]:
    """A schema of a streamed payload."""
    return isinstance(value, StreamUint8ArraySchema | StreamNdjsonSchema)


def is_stream_schema(value: object) -> TypeIs[StreamSchema]:
    return isinstance(value, StreamSseSchema | StreamUint8ArraySchema | StreamNdjsonSchema)


# --- upgrades ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Upgraded[H]:
    """What a client of an upgrade endpoint gets: the response headers and
    the upgraded connection."""

    headers: H
    socket: SocketService


@dataclass(frozen=True, slots=True, eq=False)
class UpgradeSchema[H](Bottom[SocketService, SocketService, Never, Never]):
    """A ``101 Switching Protocols`` response to ``protocol``: the handler
    returns the socket of ``request.upgrade(...)``. ``headers`` encodes the
    response's extra headers; a client gets ``Upgraded``."""

    protocol: str = field(kw_only=True)
    headers: Codec[H, Any, Never, Never] | None = field(kw_only=True)

    if TYPE_CHECKING:

        @property
        def http_api_success_client(self) -> Upgraded[H]: ...


_UPGRADE: Bottom[SocketService] = status(101)(instance_of(SocketService))


@overload
def Upgrade(protocol: str) -> UpgradeSchema[Headers]: ...
@overload
def Upgrade[H](protocol: str, *, headers: Codec[H, Any, Never, Never]) -> UpgradeSchema[H]: ...
def Upgrade(
    protocol: str, *, headers: Codec[Any, Any, Never, Never] | None = None
) -> UpgradeSchema[Any]:
    """A protocol upgrade (Effect's ``Upgrade``); WebSocket is not one
    (``ValueError``: serve it with a router route)."""
    if protocol.lower() == "websocket":
        raise ValueError("Upgrade does not support WebSocket")
    return UpgradeSchema(_UPGRADE.ast, protocol=protocol, headers=headers)


# --- response headers ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WithHeadersValue[A, H]:
    """A response ``body`` sent with ``headers`` (Effect's ``withHeaders``)."""

    body: A
    headers: H


def with_headers[A, H](body: A, headers: H) -> WithHeadersValue[A, H]:
    return WithHeadersValue(body, headers)


@dataclass(frozen=True, slots=True, eq=False)
class WithHeadersSchema[A, H](
    Bottom[WithHeadersValue[A, H], WithHeadersValue[Any, Any], Never, Never]
):
    """A response of ``schema`` with the headers ``headers`` encodes; the
    handler returns ``with_headers(body, headers)``."""

    schema: Codec[A, Any, Any, Any] = field(kw_only=True)
    headers: Codec[H, Any, Any, Any] = field(kw_only=True)


_WITH_HEADERS = cast("Bottom[WithHeadersValue[Any, Any]]", instance_of(WithHeadersValue))


def WithHeaders[A, H](
    schema: Codec[A, Any, Any, Any], headers: Codec[H, Any, Any, Any]
) -> WithHeadersSchema[A, H]:
    """``schema``'s response sent with ``headers`` (Effect's
    ``WithHeaders``). Nesting and upgrades are ``ValueError``s."""
    if is_with_headers(schema):
        raise ValueError("WithHeaders schemas cannot be nested")
    if is_upgrade(schema):
        raise ValueError("WithHeaders cannot wrap an upgrade")
    return WithHeadersSchema(_WITH_HEADERS.ast, schema=schema, headers=headers)


def rebuild_with_headers(
    self: WithHeadersSchema[Any, Any], schema: Top, headers: Top
) -> WithHeadersSchema[Any, Any]:
    return replace(self, schema=schema, headers=headers)


@dataclass(frozen=True, slots=True)
class WithHeadersAnnotation:
    """What ``encode_to_with_headers`` records: the body and headers schemas
    (and their wire codecs) and the functions between them and the value."""

    body: Top
    headers: Top
    body_codec: Top
    headers_codec: Top
    decode: Callable[[Mapping[str, Any]], object]
    encode: Callable[[Any], Mapping[str, Any]]


def get_with_headers_annotation(node: ast.AST) -> WithHeadersAnnotation | None:
    return cast("WithHeadersAnnotation | None", _annotation(node, "http_api_with_headers"))


class _WithHeadersPair[B, H](TypedDict):
    body: B
    headers: H


def encode_to_with_headers[A, B, H](
    schema: Codec[A, Any, Any, Any],
    /,
    *,
    body: Codec[B, Any, Any, Any],
    headers: Codec[H, Any, Any, Any],
    decode: Callable[[_WithHeadersPair[B, H]], A],
    encode: Callable[[A], _WithHeadersPair[B, H]],
) -> Bottom[A, Mapping[str, object]]:
    """``schema``'s values sent as ``body`` with ``headers``: ``encode``
    splits a value into both, ``decode`` joins them (Effect's
    ``encodeToWithHeaders``). The status and encoding are ``body``'s."""
    if is_upgrade(body):
        raise ValueError("encodeToWithHeaders cannot wrap an upgrade")
    body_node = body.__codec__().ast
    pair = Bottom[Any, Mapping[str, object]](
        ast.Objects(
            (
                ast.PropertySignature("body", body_node),
                ast.PropertySignature("headers", headers.__codec__().ast),
            )
        )
    )
    transformation: T.Transformation[A, Any] = T.transform(decode=decode, encode=encode)
    annotation = WithHeadersAnnotation(
        body, headers, body, headers, cast("Any", decode), cast("Any", encode)
    )
    return pair.pipe(decode_to(to_type(schema), transformation)).annotate(
        http_api_with_headers=annotation,
        http_api_status=resolve_status(body_node),
        http_api_encoding=encoding_of(body_node),
    )


# --- private -------------------------------------------------------------------------


class _SseDataFields(TypedDict):
    event: str
    data: object
    id: NotRequired[str]


_NEVER: Top = Bottom(ast.never)
