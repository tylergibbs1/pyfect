"""Building apps from route layers: ``use``, ``add``, ``add_all``,
``to_http_effect``, ``serve`` and ``to_web_handler``."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Never, Unpack, overload

from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._layer_core import Layer, MemoMap, fork_or_create, require_layer
from pyfect.context import Context
from pyfect.effect import succeed
from pyfect.http import find_my_way, server
from pyfect.http.asgi._app import AsgiApp, to_asgi_with
from pyfect.http.http_effect import HttpMiddleware
from pyfect.http.incoming_message import Reviver, revive
from pyfect.http.middleware import logger as http_logger
from pyfect.http.router._markers import GlobalRaises, GlobalRequires, Raises, Requires
from pyfect.http.router._provided import Provided, RouteContext
from pyfect.http.router._route import Method, Route, to_effect
from pyfect.http.router._router import HttpRouter, HttpRouterService, RouterConfig, make
from pyfect.http.server import HttpServer
from pyfect.http.server_error import HttpServerError
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web_handler import WebHandlerLayer, to_web_handler_layer_with
from pyfect.layer import effect as layer_effect
from pyfect.layer import effect_discard, merge, provide, provide_merge, succeed_context, unwrap
from pyfect.layer import succeed as layer_succeed
from pyfect.schema import Codec, ParseOptions, SchemaError, decode_unknown_effect
from pyfect.scope import Scope

layer: Layer[HttpRouter] = layer_effect(HttpRouter, make)
"""The ``HttpRouter`` service, configured by ``RouterConfig``."""

params: Effect[Mapping[str, str], Never, RouteContext] = RouteContext().map(
    lambda info: info.params
)
"""The matched route's path parameters."""


def schema_path_params[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | RouteContext]:
    """The path parameters decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return params.flat_map(lambda values: decode(dict(values)))


def schema_params[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | RouteContext | ParsedSearchParams]:
    """The query and path parameters (path ones win) decoded by
    ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return ParsedSearchParams().flat_map(
        lambda search: params.flat_map(lambda path: decode({**search, **path}))
    )


def _request_fields(fiber: Fiber[Any, Any]) -> dict[str, object]:
    context = fiber._context
    request = context.unsafe_get(HttpServerRequest)
    return {
        "method": request.method,
        "url": request.url,
        "headers": dict(request.headers),
        "cookies": dict(request.cookies),
        "pathParams": dict(context.unsafe_get(RouteContext).params),
        "searchParams": dict(context.unsafe_get(ParsedSearchParams)),
    }


def schema_no_body[T, RD](
    schema: Codec[T, Any, RD, Any], **options: Unpack[ParseOptions]
) -> Effect[T, SchemaError, RD | HttpServerRequest | ParsedSearchParams | RouteContext]:
    """The request's ``method``, ``url``, ``headers``, ``cookies``,
    ``pathParams`` and ``searchParams`` decoded by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return _WithFiber(lambda fiber: decode(_request_fields(fiber)))


def schema_json[T, RD](
    schema: Codec[T, Any, RD, Any],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> Effect[
    T, HttpServerError | SchemaError, RD | HttpServerRequest | ParsedSearchParams | RouteContext
]:
    """As ``schema_no_body``, with the JSON ``body`` too (parsed with
    ``reviver``)."""
    decode = decode_unknown_effect(schema, **options)

    def parsed(json: object) -> object:
        return json if reviver is None else revive(json, reviver)

    def body(fiber: Fiber[Any, Any]) -> Effect[T, HttpServerError | SchemaError, RD]:
        fields = _request_fields(fiber)
        request = fiber._context.unsafe_get(HttpServerRequest)
        return request.json.flat_map(lambda json: decode({**fields, "body": parsed(json)}))

    return _WithFiber(body)


@overload
def use[E](
    f: Callable[[HttpRouterService], Effect[object, E, Scope]],
) -> Layer[Never, E, HttpRouter]: ...
@overload
def use[E, R](
    f: Callable[[HttpRouterService], Effect[object, E, R | Scope]],
) -> Layer[Never, E, HttpRouter | R]: ...
def use(f: Callable[[HttpRouterService], Effect[object, Any, Any]]) -> Layer[Never, Any, Any]:
    """A layer doing ``f`` with the router while it builds."""
    return effect_discard(HttpRouter().flat_map(f))


@overload
def add(
    method: Method,
    path: str,
    handler: HttpServerResponse
    | Effect[HttpServerResponse, Never, Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, Never, Provided]],
    *,
    uninterruptible: bool = False,
) -> Layer[Never, Never, HttpRouter]: ...
@overload
def add[E](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, Provided]],
    *,
    uninterruptible: bool = False,
) -> Layer[Never, Never, HttpRouter | Raises[E]]: ...
@overload
def add[R](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, Never, R | Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, Never, R | Provided]],
    *,
    uninterruptible: bool = False,
) -> Layer[Never, Never, HttpRouter | Requires[R]]: ...
@overload
def add[E, R](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, R | Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, R | Provided]],
    *,
    uninterruptible: bool = False,
) -> Layer[Never, Never, HttpRouter | Requires[R] | Raises[E]]: ...
def add(
    method: Method,
    path: str,
    # Spelled out (not ``Handler``): a function is a valid handler.
    handler: HttpServerResponse
    | Effect[HttpServerResponse, Any, Any]
    | Callable[[ServerRequest], Effect[HttpServerResponse, Any, Any]],
    *,
    uninterruptible: bool = False,
) -> Layer[Never, Never, Any]:
    """A layer adding one route."""
    route = Route(method, path, to_effect(handler), uninterruptible)
    return effect_discard(HttpRouter().flat_map(lambda router: router.add_all([route])))


@overload
def add_all(
    routes: Sequence[Route[Never, Never]], *, prefix: str | None = None
) -> Layer[Never, Never, HttpRouter]: ...
@overload
def add_all[E](
    routes: Sequence[Route[E, Never]], *, prefix: str | None = None
) -> Layer[Never, Never, HttpRouter | Raises[E]]: ...
@overload
def add_all[R](
    routes: Sequence[Route[Never, R]], *, prefix: str | None = None
) -> Layer[Never, Never, HttpRouter | Requires[R]]: ...
@overload
def add_all[E, R](
    routes: Sequence[Route[E, R]], *, prefix: str | None = None
) -> Layer[Never, Never, HttpRouter | Requires[R] | Raises[E]]: ...
@overload
def add_all[E, R, EX, RX](
    routes: Effect[Sequence[Route[E, R]], EX, RX | Scope], *, prefix: str | None = None
) -> Layer[Never, EX, HttpRouter | RX | Requires[R] | Raises[E]]: ...
def add_all(
    routes: Sequence[Route[Any, Any]] | Effect[Sequence[Route[Any, Any]], Any, Any],
    *,
    prefix: str | None = None,
) -> Layer[Never, Any, Any]:
    """A layer adding routes (or the routes an effect makes), under
    ``prefix`` when given."""
    if not isinstance(routes, Sequence):
        require_effect(routes, "routes")
    made: Effect[Sequence[Route[Any, Any]], Any, Any] = (
        routes if isinstance(routes, Effect) else succeed(routes)
    )

    def add_to(router: HttpRouterService) -> Effect[None, Any, Any]:
        target = router.prefixed(prefix) if prefix else router
        return made.flat_map(target.add_all)

    return effect_discard(HttpRouter().flat_map(add_to))


def _with_router(app_layer: Layer[Any, Any, Any], config: find_my_way.RouterConfig | None) -> Any:
    router_layer = (
        layer if config is None else layer.pipe(provide(layer_succeed(RouterConfig, config)))
    )
    return app_layer.pipe(provide_merge(router_layer))


def _app_middleware(
    middleware: Callable[[Any], Effect[HttpServerResponse, Any, Any]] | None,
    disable_logger: bool,
) -> HttpMiddleware | None:
    if disable_logger:
        return middleware
    if middleware is None:
        return http_logger
    outer = middleware
    return lambda app: outer(http_logger(app))


type _Routed[RE, R] = Effect[
    HttpServerResponse, RE | HttpServerError, Scope | HttpServerRequest | R
]


@overload
def to_http_effect[A, LE](
    app_layer: Layer[A, LE, HttpRouter],
) -> Effect[_Routed[Never, Never], LE, Scope]: ...
@overload
def to_http_effect[A, LE, E = Never, R = Never, GE = Never, GR = Never](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE]
    ],
) -> Effect[_Routed[E | GE, R | GR], LE, Scope]: ...
def to_http_effect(app_layer: Layer[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """Build ``app_layer`` with a router (into the current scope) and give
    the app serving its routes."""
    require_layer(app_layer, "app_layer")

    def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        context = fiber._context
        built: Effect[Context[Any], Any, Any] = _with_router(app_layer, None).build_with_memo_map(
            fork_or_create(context), context.unsafe_get(Scope)
        )
        return built.map(lambda ctx: ctx.unsafe_get(HttpRouter).as_http_effect())

    return _WithFiber(body)


@overload
def serve[A, LE](
    app_layer: Layer[A, LE, HttpRouter],
    *,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[A, LE, HttpServer]: ...
@overload
def serve[A, LE, E = Never, R = Never, GE = Never, GR = Never](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE]
    ],
    *,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[A, LE, HttpServer | R | GR]: ...
@overload
def serve[A, LE, HE, HR = Never](
    app_layer: Layer[A, LE, HttpRouter],
    *,
    middleware: Callable[
        [_Routed[Never, Never]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[A, LE, HttpServer | HR]: ...
@overload
def serve[A, LE, HE, E = Never, R = Never, HR = Never](
    app_layer: Layer[A, LE, HttpRouter | Requires[R] | Raises[E]],
    *,
    middleware: Callable[
        [_Routed[E, R]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[A, LE, HttpServer | HR]: ...
@overload
def serve[A, LE, HE, HR, E = Never, R = Never, GE = Never, GR = Never](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE]
    ],
    *,
    middleware: Callable[
        [_Routed[E | GE, R | GR]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[A, LE, HttpServer | HR]: ...
def serve(
    app_layer: Layer[Any, Any, Any],
    *,
    middleware: Callable[[Any], Effect[HttpServerResponse, Any, Any]] | None = None,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    disable_listen_log: bool = False,
) -> Layer[Any, Any, Any]:
    """Serve the routes ``app_layer`` adds on the ``HttpServer``, logging
    each request (unless ``disable_logger``) and the address (unless
    ``disable_listen_log``). The layer's other requirements must be
    provided before serving."""
    require_layer(app_layer, "app_layer")
    app_middleware = _app_middleware(middleware, disable_logger)
    with_router = _with_router(app_layer, router_config)

    def body(fiber: Fiber[Any, Any]) -> Effect[Layer[Any, Any, Any], Any, Any]:
        context = fiber._context
        built: Effect[Context[Any], Any, Any] = with_router.build_with_memo_map(
            fork_or_create(context), context.unsafe_get(Scope)
        )

        def serving(ctx: Context[Any]) -> Layer[Any, Any, Any]:
            app = ctx.unsafe_get(HttpRouter).as_http_effect()
            served: Layer[Any, Any, Any] = (
                server.serve(app) if app_middleware is None else server.serve(app, app_middleware)
            )
            return merge(served, succeed_context(ctx))

        return built.map(serving)

    served: Layer[Any, Any, Any] = unwrap(_WithFiber(body))
    return served if disable_listen_log else server.with_log_address(served)


@overload
def to_web_handler[A, LE](
    app_layer: Layer[A, LE, HttpRouter],
    *,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer: ...
@overload
def to_web_handler[A, LE, E = Never, R = Never, GE = Never, GR = Never](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE]
    ],
    *,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer: ...
@overload
def to_web_handler[A, LE, HE, HR = Never](
    app_layer: Layer[A, LE, HttpRouter],
    *,
    middleware: Callable[
        [_Routed[Never, Never]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer: ...
@overload
def to_web_handler[A, LE, HE, E = Never, R = Never, HR = Never](
    app_layer: Layer[A, LE, HttpRouter | Requires[R] | Raises[E]],
    *,
    middleware: Callable[
        [_Routed[E, R]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer: ...
@overload
def to_web_handler[A, LE, HE, HR, E = Never, R = Never, GE = Never, GR = Never](
    app_layer: Layer[
        A, LE, HttpRouter | Requires[R] | Raises[E] | GlobalRequires[GR] | GlobalRaises[GE]
    ],
    *,
    middleware: Callable[
        [_Routed[E | GE, R | GR]], Effect[HttpServerResponse, HE, HR | HttpServerRequest | Scope]
    ],
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer: ...
def to_web_handler(
    app_layer: Layer[Any, Any, Any],
    *,
    middleware: Callable[[Any], Effect[HttpServerResponse, Any, Any]] | None = None,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> WebHandlerLayer:
    """An asyncio handler for the routes ``app_layer`` adds; the layer is
    built at once (sharing the layers of other handlers built with
    ``memo_map``) and released by ``dispose``. Request services the app
    still needs come from the handler's ``context`` argument."""
    require_layer(app_layer, "app_layer")
    return to_web_handler_layer_with(
        _with_router(app_layer, router_config),
        lambda ctx: succeed(ctx.unsafe_get(HttpRouter).as_http_effect()),
        _app_middleware(middleware, disable_logger),
        memo_map=memo_map,
    )


def to_asgi(
    app_layer: Layer[Any, Any, Any],
    *,
    middleware: Callable[[Any], Effect[HttpServerResponse, Any, Any]] | None = None,
    router_config: find_my_way.RouterConfig | None = None,
    disable_logger: bool = False,
    memo_map: MemoMap | None = None,
) -> AsgiApp:
    """An ASGI 3 application for the routes ``app_layer`` adds
    (``asgi.to_asgi_with``): the layer is built at the server's lifespan
    startup and released at its shutdown."""
    require_layer(app_layer, "app_layer")
    return to_asgi_with(
        _with_router(app_layer, router_config),
        lambda ctx: ctx.unsafe_get(HttpRouter).as_http_effect(),
        middleware=_app_middleware(middleware, disable_logger),
        memo_map=memo_map,
    )
