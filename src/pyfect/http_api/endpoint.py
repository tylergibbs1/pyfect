"""HTTP API endpoints (Effect's ``HttpApiEndpoint``): a method, a path and
the schemas of a request and its responses.

``get("getUser", "/users/:id", params=..., success=..., error=...)``
makes one. An endpoint is ``HttpApiEndpoint[P, Q, B, CB, H, S, CS, E, M]``:
the decoded params, query, payload (as the handler gets it and as a client
sends it), headers, success (as the handler returns it and as a client
gets it), errors and middleware classes (a last parameter repeats ``M``
so that the builder can read both the middleware and what it provides;
leave it out). A slot the endpoint does not declare is ``None``. Declared
on a group class, an endpoint read from the class is the endpoint; read
from a client's group it is the client method.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from functools import cache
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, Protocol, Self, TypeVar, overload

from pyfect.context import Context, TagLike
from pyfect.http.method import has_body
from pyfect.http.router import prefix_path
from pyfect.http_api import _media_type as media_type
from pyfect.http_api import schema as api_schema
from pyfect.http_api._client_method import EndpointClient
from pyfect.http_api.middleware import AnyMiddleware, HttpApiMiddleware
from pyfect.schema import Bottom, Codec, Top, ast, to_codec_json, to_codec_string_tree

if TYPE_CHECKING:
    from pyfect.http_api.group import HttpApiGroup

P_co = TypeVar("P_co", covariant=True)
Q_co = TypeVar("Q_co", covariant=True)
B_co = TypeVar("B_co", covariant=True)
CB_co = TypeVar("CB_co", covariant=True)
H_co = TypeVar("H_co", covariant=True)
S = TypeVar("S")
CS_co = TypeVar("CS_co", covariant=True)
E = TypeVar("E")
M_co = TypeVar("M_co", covariant=True, default=Never)
MT_co = TypeVar("MT_co", covariant=True, default=M_co)


type HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "QUERY", "HEAD"]
"""The methods of endpoints."""


@dataclass(frozen=True, slots=True)
class BufferedPayload:
    """Payload schemas read whole with ``encoding``."""

    encoding: api_schema.PayloadEncoding
    schemas: tuple[Top, ...]


@dataclass(frozen=True, slots=True)
class StreamPayload:
    """A payload streamed to the handler."""

    content_type: str
    schema: api_schema.StreamUint8ArraySchema | api_schema.StreamNdjsonSchema[Any]


type PayloadEntry = BufferedPayload | StreamPayload
type PayloadMap = Mapping[str, PayloadEntry]
"""The payload schemas by normalized content type."""


class _Success[T, C](Protocol):
    """A success schema whose client gets a ``C`` (a stream, an upgrade)."""

    def __codec__(self) -> Bottom[T, Any, Any, Any]: ...
    @property
    def http_api_success_client(self) -> C: ...


class _Payload[T, C](Protocol):
    """A payload schema the handler gets as ``T`` and a client sends as
    ``C`` (a stream, multipart)."""

    def __codec__(self) -> Bottom[Any, Any, Any, Any]: ...
    @property
    def http_api_payload(self) -> T: ...
    @property
    def http_api_payload_client(self) -> C: ...


@dataclass(frozen=True, slots=True, eq=False)
class HttpApiEndpoint(Generic[P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, M_co, MT_co]):
    """An endpoint. ``params``, ``query`` and ``headers`` are the string
    tree codecs of their schemas, ``payload`` the payload schemas by
    content type, ``success`` and ``error`` the response schemas (their
    JSON codecs unless ``disable_codecs``)."""

    identifier: str
    method: HttpMethod
    path: str
    params: Top | None = None
    query: Top | None = None
    headers: Top | None = None
    payload: PayloadMap = field(default_factory=dict[str, PayloadEntry])
    success: tuple[Top, ...] = ()
    error: tuple[Top, ...] = ()
    annotations: Context[Any] = field(default_factory=Context.empty)
    middlewares: tuple[AnyMiddleware, ...] = ()
    disable_codecs: bool = False

    @overload
    def __get__(self, instance: None, owner: type[object], /) -> Self: ...
    @overload
    def __get__(
        self: HttpApiEndpoint[P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, Never],
        instance: HttpApiGroup[Never],
        owner: type[object],
        /,
    ) -> EndpointClient[P_co, Q_co, CB_co, H_co, CS_co, E]: ...
    @overload
    def __get__[GE](
        self: HttpApiEndpoint[P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, Never],
        instance: HttpApiGroup[HttpApiMiddleware[Any, GE, Any]],
        owner: type[object],
        /,
    ) -> EndpointClient[P_co, Q_co, CB_co, H_co, CS_co, E, GE]: ...
    @overload
    def __get__[ME](
        self: HttpApiEndpoint[
            P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, HttpApiMiddleware[Any, ME, Any]
        ],
        instance: HttpApiGroup[Never],
        owner: type[object],
        /,
    ) -> EndpointClient[P_co, Q_co, CB_co, H_co, CS_co, E, ME]: ...
    @overload
    def __get__[ME, GE](
        self: HttpApiEndpoint[
            P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, HttpApiMiddleware[Any, ME, Any]
        ],
        instance: HttpApiGroup[HttpApiMiddleware[Any, GE, Any]],
        owner: type[object],
        /,
    ) -> EndpointClient[P_co, Q_co, CB_co, H_co, CS_co, E, ME | GE]: ...
    @overload
    def __get__(self, instance: object, owner: type[object], /) -> Self: ...
    def __get__(self, instance: object, owner: type[object], /) -> Any:
        methods: Mapping[str, object] | None = getattr(instance, "_http_api_client", None)
        return self if methods is None else methods[self.identifier]

    def prefix(self, prefix: str) -> Self:
        """This endpoint under ``prefix``."""
        return replace(self, path=prefix_path(self.path, prefix))

    def middleware[T: HttpApiMiddleware[Any, Any, Any]](
        self, middleware: type[T], /
    ) -> HttpApiEndpoint[P_co, Q_co, B_co, CB_co, H_co, S, CS_co, E, M_co | T, MT_co | T]:
        """This endpoint wrapped by ``middleware``: its handler may fail
        with the middleware's errors, a client too, and the services it
        provides are the handler's. The group layer needs the middleware."""
        if middleware in self.middlewares:
            return self
        return replace(self, middlewares=(*self.middlewares, middleware))

    def annotate[A, T](self, tag: TagLike[A, T], value: A) -> Self:
        """This endpoint with an annotation (``OpenApi.Summary``, ...)."""
        return replace(self, annotations=self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Self:
        return replace(self, annotations=self.annotations.merge(annotations))

    def pipe[A](self, f: Callable[[Self], A], /) -> A:
        return f(self)


type AnyEndpoint = HttpApiEndpoint[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any]


# --- schemas of an endpoint ----------------------------------------------------------


def success_schemas(endpoint: AnyEndpoint) -> tuple[Top, ...]:
    """The success schemas; ``NoContent`` when none were declared."""
    return endpoint.success or (api_schema.NoContent,)


def error_schemas(endpoint: AnyEndpoint) -> tuple[Top, ...]:
    """The error schemas, the middleware's included."""
    schemas: dict[int, Top] = {id(s): s for s in endpoint.error}
    for middleware in endpoint.middlewares:
        for schema in middleware.errors():
            transformed = schema if endpoint.disable_codecs else transform_response(schema)
            schemas.setdefault(id(transformed), transformed)
    return tuple(schemas.values())


def payload_schemas(endpoint: AnyEndpoint) -> tuple[Top, ...]:
    out: list[Top] = []
    for entry in endpoint.payload.values():
        out.extend(entry.schemas if isinstance(entry, BufferedPayload) else (entry.schema,))
    return tuple(out)


# --- making endpoints ----------------------------------------------------------------


def make(
    method: HttpMethod,
    identifier: str,
    path: str,
    *,
    params: Top | None = None,
    query: Top | None = None,
    headers: Top | None = None,
    payload: Top | tuple[Top, ...] | None = None,
    success: Top | tuple[Top, ...] | None = None,
    error: Top | tuple[Top, ...] | None = None,
    disable_codecs: bool = False,
) -> AnyEndpoint:
    """An endpoint; the schemas are checked here (``ValueError``): a
    stream is a success or payload of a method with a body, an upgrade the
    only success, response headers once per status, ..."""
    properties: Callable[[Top], Top] = _same if disable_codecs else to_codec_http_properties
    payload_map = _payload(payload, method, disable_codecs)
    return HttpApiEndpoint(
        identifier,
        method,
        path,
        params=None if params is None else properties(params),
        query=None if query is None else properties(query),
        headers=None if headers is None else properties(headers),
        payload=payload_map,
        success=_success(success, method, payload_map, disable_codecs),
        error=_error(error, disable_codecs),
        disable_codecs=disable_codecs,
    )


def _same(schema: Top) -> Top:
    return schema


def _tuple(schemas: Top | tuple[Top, ...]) -> tuple[Top, ...]:
    return schemas if isinstance(schemas, tuple) else (schemas,)


def to_codec_http_properties(schema: Top) -> Top:
    """``schema`` read from strings: a URL's params and query, headers."""
    return to_codec_string_tree(schema)


def _payload(
    payload: Top | tuple[Top, ...] | None, method: HttpMethod, disable_codecs: bool
) -> PayloadMap:
    result: dict[str, PayloadEntry] = {}
    if payload is None:
        return result
    has_stream = False
    for schema in _tuple(payload):
        if isinstance(schema, api_schema.StreamSseSchema):
            raise ValueError("StreamSse is response-only and cannot be used as a payload")
        if api_schema.is_stream_payload(schema):
            if not has_body(method):
                raise ValueError(f"{method} endpoints cannot declare a streaming payload")
            if has_stream:
                raise ValueError("Multiple streaming payloads are not supported")
            has_stream = True
            content_type = media_type.normalize(schema.content_type)
            if content_type in result:
                raise ValueError(
                    "Cannot combine buffered and streaming payloads for content-type: "
                    + schema.content_type
                )
            result[content_type] = StreamPayload(schema.content_type, schema)
            continue
        encoding = api_schema.get_payload_encoding(schema.__codec__().ast, method)
        content_type = media_type.normalize(encoding.content_type)
        transformed = schema if disable_codecs else _transform_payload(schema, method)
        existing = result.get(content_type)
        if existing is None:
            result[content_type] = BufferedPayload(encoding, (transformed,))
            continue
        if isinstance(existing, StreamPayload):
            raise ValueError(
                "Cannot combine buffered and streaming payloads for content-type: "
                + encoding.content_type
            )
        if existing.encoding.tag != encoding.tag:
            raise ValueError(
                f"Multiple payload encodings for content-type: {encoding.content_type}"
            )
        if existing.encoding.tag == "Multipart":
            raise ValueError(
                f"Multiple multipart payloads for content-type: {encoding.content_type}"
            )
        result[content_type] = BufferedPayload(existing.encoding, (*existing.schemas, transformed))
    return result


def _transform_payload(schema: Top, method: HttpMethod) -> Top:
    if not has_body(method):
        return to_codec_http_properties(schema)
    encoding = api_schema.get_payload_encoding(schema.__codec__().ast, method)
    match encoding.tag:
        case "Json":
            return to_codec_json(schema)
        case "FormUrlEncoded":
            return to_codec_string_tree(schema)
        case _:
            return schema


@cache
def transform_response(schema: Top) -> Top:
    """A response schema with its wire codec: JSON or string tree by its
    encoding, its headers read from strings. The same schema always gives
    the same codec, so an error a middleware repeats is one response."""
    if api_schema.is_stream_schema(schema):
        return schema
    if api_schema.is_upgrade(schema):
        if schema.headers is None:
            return schema
        return replace(schema, headers=to_codec_http_properties(schema.headers))
    if api_schema.is_with_headers(schema):
        inner = schema.schema
        if not api_schema.is_stream_schema(inner):
            inner = _apply_encoding(inner, api_schema.get_response_encoding_schema(schema))
        return api_schema.rebuild_with_headers(
            schema, inner, to_codec_http_properties(schema.headers)
        )
    node = schema.__codec__().ast
    encoding = api_schema.get_response_encoding(node)
    annotation = api_schema.get_with_headers_annotation(node)
    if annotation is None:
        return _apply_encoding(schema, encoding)
    return schema.__codec__().annotate(
        http_api_with_headers=replace(
            annotation,
            body_codec=_apply_encoding(annotation.body, encoding),
            headers_codec=to_codec_http_properties(annotation.headers),
        )
    )


def _apply_encoding(schema: Top, encoding: api_schema.ResponseEncoding) -> Top:
    match encoding.tag:
        case "Json":
            return _in_context(schema, _json_codec)
        case "FormUrlEncoded":
            return _in_context(schema, _string_tree_codec)
        case _:
            return schema


@cache
def _json_codec(node: ast.AST) -> ast.AST:
    return to_codec_json(Bottom[Any, Any](node)).ast


@cache
def _string_tree_codec(node: ast.AST) -> ast.AST:
    return to_codec_string_tree(Bottom[Any, Any](node)).ast


def _in_context(schema: Top, derive: Callable[[ast.AST], ast.AST]) -> Top:
    """``schema``'s codec made by ``derive`` once for its body: copies that
    differ only in key context (a status) share it, so they are one
    OpenAPI component."""
    node = schema.__codec__().ast
    owner = node.owner()
    derived = derive(owner)
    if owner is not node:
        derived = ast.replace_context(
            derived, key_annotations=node.key_annotations, optional_key=node.optional_key
        )
    return Bottom(derived)


def _success(
    success: Top | tuple[Top, ...] | None,
    method: HttpMethod,
    payload: PayloadMap,
    disable_codecs: bool,
) -> tuple[Top, ...]:
    if success is None:
        return ()
    schemas = _tuple(success)
    _validate_success(schemas, method, payload)
    return schemas if disable_codecs else tuple(transform_response(s) for s in schemas)


def _error(error: Top | tuple[Top, ...] | None, disable_codecs: bool) -> tuple[Top, ...]:
    if error is None:
        return ()
    schemas = _tuple(error)
    for schema in schemas:
        body = api_schema.body_of(schema)
        if api_schema.is_stream_schema(body):
            raise ValueError("Streaming schemas are not supported in error responses")
        if api_schema.is_upgrade(body):
            raise ValueError("Upgrade schemas are not supported in error responses")
    _validate_exclusivity(schemas, api_schema.get_status_error_schema)
    return schemas if disable_codecs else tuple(transform_response(s) for s in schemas)


@dataclass(slots=True)
class _StatusEntry:
    stream: api_schema.StreamSchema | None = None
    buffered: set[str] = field(default_factory=set[str])
    no_content: bool = False


def _validate_success(schemas: tuple[Top, ...], method: HttpMethod, payload: PayloadMap) -> None:
    if any(api_schema.is_upgrade(s) for s in schemas):
        _validate_upgrade(schemas, method, payload)
        return
    has_stream = False
    statuses: dict[int, _StatusEntry] = {}
    for schema in schemas:
        inner = api_schema.body_of(schema)
        status = api_schema.get_status_success_schema(schema)
        entry = statuses.setdefault(status, _StatusEntry())
        if api_schema.is_stream_schema(inner):
            _validate_stream_success(inner, method)
            if has_stream:
                raise ValueError("Multiple streaming success responses are not supported")
            has_stream = True
            _add_stream(entry, status, inner)
        else:
            _add_buffered(entry, status, schema, inner)
    _validate_exclusivity(schemas, api_schema.get_status_success_schema)


def _no_content_and_stream(status: int) -> ValueError:
    return ValueError(
        f"Cannot combine no-content and streaming success responses for status: {status}"
    )


def _buffered_and_stream(status: int, content_type: str) -> ValueError:
    return ValueError(
        "Cannot combine buffered and streaming success responses for status "
        f"{status} and content-type: {content_type}"
    )


def _add_stream(entry: _StatusEntry, status: int, stream: api_schema.StreamSchema) -> None:
    if entry.no_content:
        raise _no_content_and_stream(status)
    if media_type.normalize(stream.content_type) in entry.buffered:
        raise _buffered_and_stream(status, stream.content_type)
    entry.stream = stream


def _add_buffered(entry: _StatusEntry, status: int, schema: Top, inner: Top) -> None:
    no_content = api_schema.is_no_content(inner.__codec__().ast)
    content_type = api_schema.get_response_encoding_schema(schema).content_type
    if entry.stream is not None:
        if no_content:
            raise _no_content_and_stream(status)
        if media_type.normalize(content_type) == media_type.normalize(entry.stream.content_type):
            raise _buffered_and_stream(status, content_type)
    if not no_content:
        entry.buffered.add(media_type.normalize(content_type))
    entry.no_content = entry.no_content or no_content


def _validate_upgrade(schemas: tuple[Top, ...], method: HttpMethod, payload: PayloadMap) -> None:
    if len(schemas) > 1:
        raise ValueError("Cannot combine an upgrade with other success responses")
    if method == "HEAD":
        raise ValueError("HEAD endpoints cannot declare an upgrade")
    # The 101 can only follow the end of the request, so the body is read first.
    for entry in payload.values():
        if isinstance(entry, StreamPayload) or (
            isinstance(entry.encoding, api_schema.MultipartEncoding)
            and entry.encoding.mode == "stream"
        ):
            raise ValueError("Upgrade endpoints cannot declare a streaming payload")


@dataclass(slots=True)
class _HeadersEntry:
    header_content_type: str | None = None
    plain: set[str] = field(default_factory=set[str])


def _validate_exclusivity(schemas: tuple[Top, ...], get_status: Callable[[Top], int]) -> None:
    statuses: dict[int, _HeadersEntry] = {}
    for schema in schemas:
        status = get_status(schema)
        annotation = api_schema.get_with_headers_annotation(schema.__codec__().ast)
        if api_schema.is_with_headers(schema):
            body = schema.schema
        else:
            body = annotation.body if annotation is not None else schema
        if api_schema.is_no_content(body.__codec__().ast):
            content_type = ""
        elif api_schema.is_stream_schema(body):
            content_type = media_type.normalize(body.content_type)
        else:
            content_type = media_type.normalize(
                api_schema.get_response_encoding_schema(schema).content_type
            )
        entry = statuses.setdefault(status, _HeadersEntry())
        combine = ValueError(
            "Cannot combine a response with headers with another response for status "
            f"{status} and content-type: {content_type or '<no content>'}"
        )
        if api_schema.is_with_headers(schema) or annotation is not None:
            if entry.header_content_type is not None:
                raise ValueError(
                    f"Cannot declare multiple responses with headers for status {status}"
                )
            if content_type in entry.plain:
                raise combine
            entry.header_content_type = content_type
        else:
            if entry.header_content_type == content_type:
                raise combine
            entry.plain.add(content_type)


def _validate_stream_success(schema: api_schema.StreamSchema, method: HttpMethod) -> None:
    if method == "HEAD":
        raise ValueError("HEAD endpoints cannot declare streaming success responses")
    if isinstance(schema, api_schema.StreamSseSchema) and _has_reserved_event(
        ast.to_encoded(schema.events.__codec__().ast), set()
    ):
        raise ValueError(f"SSE event name is reserved: {api_schema.RESERVED_STREAM_FAILURE_EVENT}")


def _has_reserved_event(node: ast.AST, seen: set[int]) -> bool:
    if id(node) in seen:
        return False
    seen.add(id(node))
    match node:
        case ast.Union():
            return any(_has_reserved_event(t, seen) for t in node.types)
        case ast.Suspend():
            return _has_reserved_event(node.target, seen)
        case ast.Objects():
            event = next((p for p in node.properties if p.name == "event"), None)
            return event is not None and _has_reserved_literal(event.type, seen)
        case _:
            return False


def _has_reserved_literal(node: ast.AST, seen: set[int]) -> bool:
    if id(node) in seen:
        return False
    seen.add(id(node))
    encoded = ast.to_encoded(node)
    if encoded is not node and node.encoding is not None:
        return _has_reserved_literal(encoded, seen)
    match node:
        case ast.Literal():
            return node.literal == api_schema.RESERVED_STREAM_FAILURE_EVENT
        case ast.Union():
            return any(_has_reserved_literal(t, seen) for t in node.types)
        case ast.Suspend():
            return _has_reserved_literal(node.target, seen)
        case _:
            return False


# --- typed constructors --------------------------------------------------------------


@overload
def get[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def get[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def get(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``GET`` endpoint (see ``make``)."""
    return make("GET", identifier, path, **options)


@overload
def head[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def head[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def head(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``HEAD`` endpoint (see ``make``)."""
    return make("HEAD", identifier, path, **options)


@overload
def options[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def options[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def options(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``OPTIONS`` endpoint (see ``make``)."""
    return make("OPTIONS", identifier, path, **options)


@overload
def post[B, CB, S, CS, P = None, Q = None, H = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, CS, E]: ...
@overload
def post[B, CB, P = None, Q = None, H = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, S, E]: ...
@overload
def post[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def post[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def post(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``POST`` endpoint (see ``make``)."""
    return make("POST", identifier, path, **options)


@overload
def put[B, CB, S, CS, P = None, Q = None, H = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, CS, E]: ...
@overload
def put[B, CB, P = None, Q = None, H = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, S, E]: ...
@overload
def put[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def put[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def put(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``PUT`` endpoint (see ``make``)."""
    return make("PUT", identifier, path, **options)


@overload
def patch[B, CB, S, CS, P = None, Q = None, H = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, CS, E]: ...
@overload
def patch[B, CB, P = None, Q = None, H = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, S, E]: ...
@overload
def patch[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def patch[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def patch(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``PATCH`` endpoint (see ``make``)."""
    return make("PATCH", identifier, path, **options)


@overload
def delete[B, CB, S, CS, P = None, Q = None, H = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, CS, E]: ...
@overload
def delete[B, CB, P = None, Q = None, H = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, S, E]: ...
@overload
def delete[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def delete[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def delete(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``DELETE`` endpoint (see ``make``)."""
    return make("DELETE", identifier, path, **options)


@overload
def query[B, CB, S, CS, P = None, Q = None, H = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, CS, E]: ...
@overload
def query[B, CB, P = None, Q = None, H = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: _Payload[B, CB],
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, CB, H, S, S, E]: ...
@overload
def query[S, CS, P = None, Q = None, H = None, B = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: _Success[S, CS],
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, CS, E]: ...
@overload
def query[P = None, Q = None, H = None, B = None, S = None, E = Never](
    identifier: str,
    path: str,
    *,
    params: Codec[P, Any, Never, Never] | None = None,
    query: Codec[Q, Any, Never, Never] | None = None,
    headers: Codec[H, Any, Never, Never] | None = None,
    payload: Codec[B, Any, Never, Never] | tuple[Codec[B, Any, Never, Never], ...] | None = None,
    success: Codec[S, Any, Never, Never] | tuple[Codec[S, Any, Never, Never], ...] | None = None,
    error: Codec[E, Any, Never, Never] | tuple[Codec[E, Any, Never, Never], ...] | None = None,
    disable_codecs: bool = False,
) -> HttpApiEndpoint[P, Q, B, B, H, S, S, E]: ...
def query(identifier: str, path: str, **options: Any) -> AnyEndpoint:
    """A ``QUERY`` endpoint (see ``make``)."""
    return make("QUERY", identifier, path, **options)


__all__ = [
    "AnyEndpoint",
    "BufferedPayload",
    "HttpApiEndpoint",
    "HttpMethod",
    "PayloadEntry",
    "PayloadMap",
    "StreamPayload",
    "delete",
    "error_schemas",
    "get",
    "head",
    "make",
    "options",
    "patch",
    "payload_schemas",
    "post",
    "put",
    "query",
    "success_schemas",
    "to_codec_http_properties",
    "transform_response",
]
