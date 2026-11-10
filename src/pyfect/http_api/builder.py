"""Serving an ``HttpApi`` (Effect's ``HttpApiBuilder``).

``group(api, Users, build)`` is the layer of one group's handlers;
``layer(api)`` adds every group's routes to the ``HttpRouter``::

    UsersLive = builder.group(
        api, Users, lambda handlers: handlers.handle(Users.get_user)(get_user)
    )
    app = builder.layer(api).pipe(layer.provide(UsersLive))
    router.serve(app)

A handler gets an ``HttpApiRequest`` with the decoded parts and returns
its success value (or any ``HttpServerResponse``); a declared error is
answered with its schema's response. A request part that does not decode
is a ``400``, a response that does not encode a ``500``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Generator, Mapping
from typing import Any, Never, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Context, Reference
from pyfect.effect import (
    context,
    die,
    gen,
    provide_context,
    provide_service,
    succeed,
    suspend,
    sync,
)
from pyfect.http.router import HttpRouter, HttpRouterService, Route, RouteContext, route, use
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams, ServerRequest
from pyfect.http.server_respondable import is_respondable, to_response
from pyfect.http.server_response import HttpServerResponse, empty, json_unsafe
from pyfect.http_api import _path
from pyfect.http_api import schema as api_schema
from pyfect.http_api._handlers import (
    GroupHandlers,
    HandlerEntry,
    Handlers,
    HttpApiRequest,
    PayloadErrors,
)
from pyfect.http_api._html import memoize_success
from pyfect.http_api._payload import decode_payload, payload_decoders
from pyfect.http_api._response import (
    StreamEncode,
    WithHeadersEncoders,
    error_schema,
    stream_encoder,
    success_schema,
    with_headers_encoders,
)
from pyfect.http_api._security import (
    authorization_credential,
    security_decode,
    security_middleware,
    security_set_cookie,
)
from pyfect.http_api.api import AnyApi, ApiWith, HttpApi, api_of, get_slot_parse_options
from pyfect.http_api.endpoint import AnyEndpoint, HttpApiEndpoint
from pyfect.http_api.error import HttpApiPayloadTooLarge, HttpApiSchemaError
from pyfect.http_api.group import AnyGroup, GroupService, HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware, MiddlewareOptions
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.scope import Scope

_GROUP_KEY_PREFIX = "effect/http-api/HttpApiGroup/"


def layer[G](
    api: HttpApi[G], *, openapi_path: str | None = None, schema_error_details: bool = False
) -> Layer[Never, Never, HttpRouter | G]:
    """Adds the routes of every group of ``api`` to the router (each
    group's layer must be provided), and ``GET openapi_path`` answering
    with the API's OpenAPI document.

    A request whose params, headers, query or payload do not decode gets an
    empty 400, as in Effect; ``schema_error_details=True`` sends the schema
    issue in it (``{"_tag": "HttpApiSchemaError", "kind", "message"}``)."""

    def add(router: HttpRouterService) -> Effect[None, Never, Any]:
        def with_services(services: Context[Any]) -> Effect[None, Never, Any]:
            routes: list[Route[Any, Any]] = []
            owners: dict[str, str] = {}
            for group in api.groups.values():
                found = services.get_option(group.origin)
                if found is None:
                    return die(RuntimeError(_missing_group(group, services)))
                service: GroupService = found.value
                for entry in service.handlers.values():
                    clash = _claim_route(owners, group, entry.endpoint)
                    if clash is not None:
                        return die(RuntimeError(clash))
                routes.extend(service.routes)
            if schema_error_details:
                detailed = provide_service(_SchemaErrorDetails, True)
                routes = [dataclasses.replace(r, handler=detailed(r.handler)) for r in routes]
            added = router.add_all(routes)
            if openapi_path is None:
                return added
            path = openapi_path
            document = memoize_success(lambda: _openapi_document(api))
            return added.flat_map(lambda _: router.add("GET", path, sync(document)))

        return context().flat_map(with_services)

    return use(add)


def _claim_route(owners: dict[str, str], group: AnyGroup, endpoint: AnyEndpoint) -> str | None:
    """Records ``endpoint`` as its method and path's owner; the message when
    another endpoint has them already."""
    owner = f"{group.identifier}.{endpoint.identifier}"
    key = f"{endpoint.method} {_path.to_router_path(endpoint.path, endpoint.params)}"
    existing = owners.get(key)
    if existing is not None:
        return (
            f'HttpApiEndpoint "{owner}" ({endpoint.method} {endpoint.path}) has the same '
            f'method and path as "{existing}". Declare one endpoint whose query, headers, '
            "payload or success schemas cover each variant instead."
        )
    owners[key] = owner
    return None


class _SchemaErrorDetails(Reference[bool]):
    """Set by ``layer(api, schema_error_details=True)`` on its routes."""

    @classmethod
    def default(cls) -> bool:
        return False


def _missing_group(group: AnyGroup, services: Context[Any]) -> str:
    available = [tag.key for tag in services.tags() if tag.key.startswith(_GROUP_KEY_PREFIX)]
    return (
        f'HttpApiGroup "{group.identifier}" not found (key: "{group.key}"). '
        f'Did you forget to provide HttpApiBuilder.group(api, "{group.identifier}", ...)? '
        f"Available groups: {', '.join(available) or 'none'}"
    )


def _openapi_document(api: AnyApi) -> HttpServerResponse:
    from pyfect.http_api import openapi

    return json_unsafe(openapi.from_api(api))


# --- groups ----------------------------------------------------------------------------


@overload
def group[G: HttpApiGroup[Any, Any]](
    api: ApiWith[G],
    group: type[G],
    build: Callable[[GroupHandlers[G]], GroupHandlers[G]],
    /,
) -> Layer[G]: ...
@overload
def group[G: HttpApiGroup[Any, Any], R](
    api: ApiWith[G],
    group: type[G],
    build: Callable[[GroupHandlers[G]], Handlers[Any, Any, R]],
    /,
) -> Layer[G, Never, R]: ...
@overload
def group[G: HttpApiGroup[Any, Any], EX, RR = Never](
    api: ApiWith[G],
    group: type[G],
    build: Callable[[GroupHandlers[G]], Effect[Handlers[Any, Any, RR], EX, RR]],
    /,
) -> Layer[G, EX, RR]: ...
def group(
    given: ApiWith[Any],
    group: AnyGroup,
    build: Callable[[GroupHandlers[Any]], Any],
    /,
) -> Layer[Any, Any, Any]:
    """The layer of ``group``'s handlers in ``api``: ``build`` gets the
    empty handlers and returns them with one for each endpoint (or an
    effect making them; it runs when the layer is built). A group with an
    endpoint left unhandled is a defect of the layer (a group not in
    ``api`` is a type error, and a ``ValueError``). The handlers run with
    the services of the layer's context."""
    api = api_of(given)
    declared = api.groups.get(group.identifier)
    if declared is None:
        raise ValueError(
            f'HttpApiGroup "{group.identifier}" not found in HttpApi "{api.identifier}"'
        )
    api_group = declared

    def make(services: Context[Any]) -> Effect[Context[Any], Any, Any]:
        result = build(GroupHandlers(api_group))
        made: Effect[Any, Any, Any] = (
            cast("Effect[Any, Any, Any]", result) if isinstance(result, Effect) else succeed(result)
        )
        return made.flat_map(lambda handlers: _group_context(api, api_group, handlers, services))

    return layer_effect_context(context().flat_map(lambda services: make(_omit_scope(services))))


def _omit_scope(services: Context[Any]) -> Context[Any]:
    return Context({tag: s for tag, s in services.map_unsafe.items() if tag is not Scope})


def _group_context(
    api: AnyApi,
    group: AnyGroup,
    handlers: Handlers[Any, Any, Any] | GroupHandlers[Any],
    services: Context[Any],
) -> Effect[Context[Any]]:
    entries: Mapping[str, HandlerEntry] = handlers.entries if isinstance(handlers, Handlers) else {}
    missing = [identifier for identifier in group.endpoints if identifier not in entries]
    if missing:
        return die(RuntimeError(_unhandled_message(group, missing)))
    routes = tuple(handler_to_route(api, group, entry, services) for entry in entries.values())
    return succeed(Context({group.origin: GroupService(routes, entries)}))


def _unhandled_message(group: AnyGroup, missing: list[str]) -> str:
    """Names each endpoint left without a handler, with the attribute that
    declares it (Effect rejects such a group at compile time; pyright
    cannot name the endpoints not yet handled)."""
    attributes: dict[str, str] = {}
    for klass in reversed(group.origin.__mro__):
        for name, value in vars(klass).items():
            if isinstance(value, HttpApiEndpoint):
                attributes[cast("AnyEndpoint", value).identifier] = name
    named = [
        f'"{identifier}"'
        + (
            f" ({group.origin.__name__}.{attributes[identifier]})"
            if identifier in attributes
            else ""
        )
        for identifier in missing
    ]
    return f'HttpApiGroup "{group.identifier}" has no handler for {", ".join(named)}'


type _Handler[X, S, E, R] = Callable[[X], Effect[S | HttpServerResponse, E | PayloadErrors, R]]


@overload
def handler[P, Q, B, CB, H, S1, CS, E1, R](
    endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, Never],
    f: _Handler[HttpApiRequest[P, Q, B, H], S1, E1, R],
    /,
) -> _Handler[HttpApiRequest[P, Q, B, H], S1, E1, R]: ...
@overload
def handler[P, Q, B, CB, H, S1, CS, E1, MP, ME, MR, MT, R](
    endpoint: HttpApiEndpoint[P, Q, B, CB, H, S1, CS, E1, HttpApiMiddleware[MP, ME, MR], MT],
    f: _Handler[HttpApiRequest[P, Q, B, H], S1, E1 | ME, R],
    /,
) -> _Handler[HttpApiRequest[P, Q, B, H], S1, E1 | ME, R]: ...
def handler(endpoint: AnyEndpoint, f: Any, /) -> Any:
    """``f`` unchanged, typed as ``endpoint``'s handler, for a later
    ``handle(endpoint)(f)`` (Effect's ``HttpApiBuilder.handler``)."""
    return f


def handler_to_route(
    api: AnyApi, group: AnyGroup, entry: HandlerEntry, services: Context[Any]
) -> Route[Any, Any]:
    """The router route of a handler."""
    endpoint = entry.endpoint
    return route(
        endpoint.method,
        _path.to_router_path(endpoint.path, endpoint.params),
        handler_to_http_effect(api, group, endpoint, services, entry.handler, is_raw=entry.is_raw),
        uninterruptible=entry.uninterruptible,
    )


def endpoint(
    api: AnyApi,
    group: AnyGroup,
    endpoint: AnyEndpoint,
    handler: Callable[[HttpApiRequest[Any, Any, Any, Any]], Effect[Any, Any, Any]],
) -> Effect[Effect[HttpServerResponse, Never, Any], Never, Any]:
    """The HTTP effect of one endpoint's handler, run with the current
    services (Effect's ``HttpApiBuilder.endpoint``)."""
    api_group = api.groups[group.identifier]
    declared = api_group.endpoints[endpoint.identifier]
    return context().map(
        lambda services: handler_to_http_effect(
            api, api_group, declared, _omit_scope(services), handler, is_raw=False
        )
    )


# --- the HTTP effect of a handler ------------------------------------------------------


def handler_to_http_effect(
    api: AnyApi,
    group: AnyGroup,
    endpoint: AnyEndpoint,
    services: Context[Any],
    handler: Callable[[HttpApiRequest[Any, Any, Any, Any]], Effect[Any, Any, Any]],
    *,
    is_raw: bool,
) -> Effect[HttpServerResponse, Never, Any]:
    annotations = api.annotations.merge(group.annotations).merge(endpoint.annotations)
    options = get_slot_parse_options(annotations)
    encode_success = S.encode_unknown_effect(
        success_schema(endpoint, options.headers), **options.success
    )
    encode_error = S.encode_unknown_effect(error_schema(endpoint, options.headers), **options.error)
    decode_params = _decoder(endpoint.params, options.params)
    decode_headers = _decoder(endpoint.headers, options.headers)
    decode_query = (
        None
        if endpoint.query is None
        else S.decode_unknown_effect(S.to_codec_array_from_single(endpoint.query), **options.query)
    )
    encode_stream = stream_encoder(endpoint, options.success)
    encode_with_headers = with_headers_encoders(endpoint, options.success, options.headers)
    upgrade = next((s for s in endpoint.success if api_schema.is_upgrade(s)), None)
    # The handler of a mixed endpoint may decline the upgrade with another success.
    upgrade_only = upgrade is not None and len(endpoint.success) == 1
    encode_upgrade_headers = (
        None
        if upgrade is None or upgrade.headers is None
        else S.encode_unknown_effect(upgrade.headers, **options.headers)
    )
    encode_response = _ResponseEncoder(
        upgrade_only, encode_success, encode_stream, encode_with_headers, services
    )
    payload_by = (
        payload_decoders(endpoint.payload, options.payload)
        if endpoint.payload and not is_raw
        else None
    )

    def respond() -> Any:
        request: ServerRequest = yield from HttpServerRequest()
        route_info = yield from RouteContext()
        query = yield from ParsedSearchParams()
        params = headers = query_value = payload = None
        if decode_params is not None:
            params = yield from HttpApiSchemaError.wrap("Params", decode_params(route_info.params))
        if decode_headers is not None:
            headers = yield from HttpApiSchemaError.wrap("Headers", decode_headers(request.headers))
        if decode_query is not None:
            query_value = yield from HttpApiSchemaError.wrap("Query", decode_query(query))
        upgrader = None
        upgraded: list[bool] = []
        if upgrade is not None:
            if not _is_upgrade_request(request, upgrade.protocol):
                return _upgrade_required(upgrade.protocol)
            upgrader = _upgrader(request, encode_upgrade_headers, upgraded)
        if payload_by is not None:
            decoded = decode_payload(payload_by, request, query)
            payload = yield from HttpApiSchemaError.wrap("Payload", decoded)
            if isinstance(payload, HttpServerResponse):
                return payload
        response = yield from handler(
            HttpApiRequest(
                params, query_value, payload, headers, request, endpoint, group, upgrader
            )
        )
        return (yield from encode_response(response, upgraded=bool(upgraded)))

    def on_error(error: object) -> Effect[HttpServerResponse, Never, Any]:
        if isinstance(error, HttpApiSchemaError):
            schema_error = error

            def with_details(details: bool) -> Effect[HttpServerResponse, Never, Any]:
                return die(dataclasses.replace(schema_error, details=details))

            return _SchemaErrorDetails().flat_map(with_details)
        if isinstance(error, HttpApiPayloadTooLarge):
            return die(error)

        def unencodable(schema_error: object) -> Effect[HttpServerResponse, Never, Any]:
            if is_respondable(error):
                return to_response(error)
            return die(cast("BaseException", schema_error))

        encoded = cast("Effect[HttpServerResponse, S.SchemaError, Any]", encode_error(error))
        return encoded.catch_all(unencodable)

    wrapped = _apply_middleware(group, endpoint, services, gen(respond))
    return wrapped.with_error_reporting().catch_all(on_error).pipe(provide_context(services))


@dataclasses.dataclass(frozen=True)
class _ResponseEncoder:
    """A handler's result as the response: an upgrade's empty placeholder, a
    response as is, or the success encoded."""

    upgrade_only: bool
    encode_success: Callable[[object], Effect[Any, S.SchemaError, Any]]
    encode_stream: StreamEncode | None
    encode_with_headers: WithHeadersEncoders | None
    services: Context[Any]

    def __call__(self, response: object, *, upgraded: bool) -> Effect[HttpServerResponse, Any, Any]:
        if isinstance(response, HttpServerResponse):
            return succeed(response)
        if self.upgrade_only or upgraded:
            if response is not None and not self.upgrade_only:
                return die(RuntimeError("Cannot return a success value after calling upgrade()"))
            # The server replaces this with the 101 once the connection is upgraded.
            return succeed(empty())
        encode_stream, services = self.encode_stream, self.services
        encoders = self.encode_with_headers
        if encoders is not None and isinstance(response, api_schema.WithHeadersValue):
            value = cast("api_schema.WithHeadersValue[Any, Any]", response)
            return gen(lambda: _encode_with_headers(encoders, encode_stream, services, value))
        streamed = None if encode_stream is None else encode_stream(response, services)
        encoding = self.encode_success(response) if streamed is None else streamed
        return HttpApiSchemaError.wrap("Body", encoding)


def _encode_with_headers(
    encoders: WithHeadersEncoders,
    encode_stream: StreamEncode | None,
    services: Context[Any],
    value: api_schema.WithHeadersValue[Any, Any],
) -> Generator[Any, Any, HttpServerResponse]:
    streamed = None if encode_stream is None else encode_stream(value.body, services)
    encoding = encoders.encode_body(value.body) if streamed is None else streamed
    encoded: HttpServerResponse = yield from HttpApiSchemaError.wrap("Body", encoding)
    encode_headers = encoders.encode_headers[encoded.status]
    headers = yield from HttpApiSchemaError.wrap("ResponseHeaders", encode_headers(value.headers))
    return encoded.set_headers(headers)


def _decoder(
    schema: S.Top | None, options: S.ParseOptions
) -> Callable[[object], Effect[Any, S.SchemaError, Any]] | None:
    return None if schema is None else S.decode_unknown_effect(schema, **options)


def _upgrader(
    request: ServerRequest,
    encode_headers: Callable[[object], Effect[Any, S.SchemaError, Any]] | None,
    upgraded: list[bool],
) -> Callable[[object], Effect[Any]]:
    def upgrade(headers: object) -> Effect[Any]:
        def run() -> Effect[Any]:
            upgraded.append(True)
            if encode_headers is None:
                return request.upgrade.or_die()
            return (
                HttpApiSchemaError.wrap("ResponseHeaders", encode_headers(headers))
                .flat_map(lambda encoded: request.upgrade_with(headers=encoded))
                .or_die()
            )

        return suspend(run)

    return upgrade


def _is_upgrade_request(request: ServerRequest, protocol: str) -> bool:
    """RFC 9110 §7.8: ``Upgrade`` only applies with an ``upgrade``
    connection option."""
    upgrade = request.headers.get("upgrade")
    connection = request.headers.get("connection") or ""
    return (
        upgrade is not None
        and upgrade.lower() == protocol.lower()
        and any(option.strip().lower() == "upgrade" for option in connection.split(","))
    )


def _upgrade_required(protocol: str) -> HttpServerResponse:
    return empty(status=426, headers={"connection": "Upgrade", "upgrade": protocol})


def _apply_middleware(
    group: AnyGroup, endpoint: AnyEndpoint, services: Context[Any], handler: Effect[Any, Any, Any]
) -> Effect[Any, Any, Any]:
    options = MiddlewareOptions(endpoint, group)
    for middleware in endpoint.middlewares:
        service: Any = services.get_unsafe(middleware)
        securities = middleware.security
        apply = service if securities is None else security_middleware(securities, service)
        handler = apply(handler, options)
    return handler


__all__ = [
    "authorization_credential",
    "endpoint",
    "group",
    "handler",
    "handler_to_http_effect",
    "handler_to_route",
    "layer",
    "security_decode",
    "security_set_cookie",
]
