"""The ``HttpRouter`` service: routes added while layers build, found per
request with find-my-way."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Never, overload

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._primitives import _Locally
from pyfect._tracer_ref import CurrentTracer
from pyfect.context import Context, Reference, Tag
from pyfect.effect import fail, sync, void
from pyfect.http import _redacted_path, _request_state, find_my_way
from pyfect.http.find_my_way._paths import closing_parenthesis
from pyfect.http.router._markers import Raises, Requires, Unhandled
from pyfect.http.router._middleware_stack import MiddlewareFn, middleware_of
from pyfect.http.router._provided import Provided, RouteContext, RouteInfo
from pyfect.http.router._route import (
    Method,
    Route,
    prefix_path,
    prefix_route,
    redacted_param_names,
    remove_trailing_slash,
    to_effect,
)
from pyfect.http.server_error import HttpServerError, RouteNotFound
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.tracer import ExternalSpan, ParentSpan, native_tracer

type GlobalMiddlewareFn = Callable[
    [Effect[HttpServerResponse, Unhandled]], Effect[HttpServerResponse, Any, Any]
]


class RouterConfig(Reference[find_my_way.RouterConfig], key="effect/http/HttpRouter/RouterConfig"):
    """How routes match: trailing and duplicate slashes, case, and the
    longest path parameter."""

    @classmethod
    def default(cls) -> find_my_way.RouterConfig:
        return find_my_way.RouterConfig()


@dataclass(frozen=True, slots=True)
class _Entry:
    route: Route[Any, Any]
    prefix_segments: int | None
    redacted_path: _redacted_path.Template | None


def count_segments(prefix: str, ignore_duplicate_slashes: bool) -> int:
    """The number of path segments ``prefix`` matches; slashes inside a
    parameter's regex do not count."""
    count = 0
    in_param = False
    i = 0
    while i < len(prefix):
        char = prefix[i]
        if char == "/":
            if not ignore_duplicate_slashes or prefix[i - 1 : i] != "/":
                count += 1
            in_param = False
        elif char == ":":
            if prefix[i + 1 : i + 2] == ":":
                i += 1
            else:
                in_param = True
        elif char in "-.":
            in_param = False
        elif char == "(" and in_param:
            i = closing_parenthesis(prefix, i)
            in_param = False
        i += 1
    return count


def slice_request_url(
    request: ServerRequest, prefix_segments: int, config: find_my_way.RouterConfig
) -> ServerRequest:
    """``request`` with its first ``prefix_segments`` path segments
    removed from the URL."""
    ignore_duplicate_slashes = config.ignore_duplicate_slashes
    segment_end = "/?;#" if config.use_semicolon_delimiter else "/?#"
    url = request.url
    index = 0
    for _ in range(prefix_segments):
        if ignore_duplicate_slashes:
            while url[index : index + 1] == "/":
                index += 1
        elif url[index : index + 1] == "/":
            index += 1
        while index < len(url) and url[index] not in segment_end:
            index += 1
    rest = url[index:]
    return request.modify(url=rest if rest.startswith("/") else "/" + rest)


@dataclass(eq=False)
class _Core:
    config: find_my_way.RouterConfig
    router: find_my_way.Router[_Entry]
    global_middleware: list[GlobalMiddlewareFn] = field(default_factory=list[GlobalMiddlewareFn])

    def add_all(self, routes: Sequence[Route[Any, Any]]) -> Effect[None]:
        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            middleware = middleware_of(fiber._context)
            for route in routes:
                self._add(route if not middleware else _with_middleware(route, middleware))
            return void

        return _WithFiber(body)

    def _add(self, route: Route[Any, Any]) -> None:
        entry = _Entry(
            route,
            None
            if route.prefix is None
            else count_segments(route.prefix, self.config.ignore_duplicate_slashes),
            _redacted_path.compile_template(route.path, route.redacted_params)
            if route.redacted_params
            else None,
        )
        if route.method == "*":
            self.router.all(route.path, entry)
        else:
            self.router.on(route.method, route.path, entry)
        # A wildcard route also serves its bare prefix, unless that path has its own route.
        if route.path.endswith("/*"):
            self.router.on_fallback(route.method, route.path[:-2] or "/", entry)

    def as_http_effect(self) -> Effect[HttpServerResponse, Any, HttpServerRequest]:
        handler: Effect[HttpServerResponse, Any, Any] = _WithFiber(self._dispatch)
        for fn in reversed(self.global_middleware):
            handler = fn(handler)
        return handler

    def _find(self, request: ServerRequest) -> tuple[find_my_way.FindResult[_Entry] | None, bool]:
        result = self.router.find(request.method, request.url)
        exceeded = result is None and self.router.max_param_length_exceeded
        if result is None and request.method == "HEAD":
            result = self.router.find("GET", request.url)
            exceeded = exceeded or (result is None and self.router.max_param_length_exceeded)
        return result, exceeded

    def _dispatch(self, fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, Any, Any]:
        request = fiber._context.get_unsafe(HttpServerRequest)
        result, exceeded = self._find(request)
        if result is None:
            limit = self.config.max_param_length
            description = (
                f"path parameter is longer than maxParamLength ({limit})" if exceeded else None
            )
            return fail(HttpServerError(RouteNotFound(request, description)))
        route = result.handler.route
        segments = result.handler.prefix_segments
        routed = request if segments is None else slice_request_url(request, segments, self.config)
        template = result.handler.redacted_path
        if template is not None:
            state = _request_state.get(fiber._context)
            if state is not None:
                state.redacted_path = _redacted_path.combine(
                    state.redacted_path, _redacted_path.render(template, result.params), request
                )
        if fiber.get_ref(CurrentTracer) is not native_tracer:
            span = fiber.get_ref(ParentSpan)
            if span is not None and not isinstance(span, ExternalSpan) and span.sampled:
                span.attribute("http.route", route.path)
        info = RouteInfo(route, result.params)
        search_params = result.search_params

        def provide(ctx: Context[Any]) -> Context[Any]:
            return (
                ctx.add(HttpServerRequest, routed)
                .add(ParsedSearchParams, search_params)
                .add(RouteContext, info)
            )

        handler = route.handler if route.uninterruptible else route.handler.interruptible()
        return _Locally(handler, provide)


def _with_middleware(route: Route[Any, Any], middleware: Sequence[MiddlewareFn]) -> Route[Any, Any]:
    handler = route.handler
    for fn in middleware:
        handler = fn(handler)
    return replace(route, handler=handler)


@dataclass(frozen=True, slots=True)
class HttpRouterService:
    """Add routes while layers build; ``as_http_effect`` serves them."""

    _core: _Core
    _prefix: str | None = None

    def prefixed(self, prefix: str) -> HttpRouterService:
        """This router with every route mounted under ``prefix``."""
        prefix = remove_trailing_slash(prefix)
        return HttpRouterService(
            self._core, prefix if self._prefix is None else prefix_path(prefix, self._prefix)
        )

    @overload
    def add(
        self,
        method: Method,
        path: str,
        handler: HttpServerResponse
        | Effect[HttpServerResponse, Never, Provided]
        | Callable[[ServerRequest], Effect[HttpServerResponse, Never, Provided]],
        *,
        uninterruptible: bool = False,
        redacted_params: Sequence[str] = (),
    ) -> Effect[None]: ...
    @overload
    def add[E](
        self,
        method: Method,
        path: str,
        handler: Effect[HttpServerResponse, E, Provided]
        | Callable[[ServerRequest], Effect[HttpServerResponse, E, Provided]],
        *,
        uninterruptible: bool = False,
        redacted_params: Sequence[str] = (),
    ) -> Effect[None, Never, Raises[E]]: ...
    @overload
    def add[R](
        self,
        method: Method,
        path: str,
        handler: Effect[HttpServerResponse, Never, R | Provided]
        | Callable[[ServerRequest], Effect[HttpServerResponse, Never, R | Provided]],
        *,
        uninterruptible: bool = False,
        redacted_params: Sequence[str] = (),
    ) -> Effect[None, Never, Requires[R]]: ...
    @overload
    def add[E, R](
        self,
        method: Method,
        path: str,
        handler: Effect[HttpServerResponse, E, R | Provided]
        | Callable[[ServerRequest], Effect[HttpServerResponse, E, R | Provided]],
        *,
        uninterruptible: bool = False,
        redacted_params: Sequence[str] = (),
    ) -> Effect[None, Never, Requires[R] | Raises[E]]: ...
    def add(
        self,
        method: Method,
        path: str,
        # Spelled out (not ``Handler``): a function is a valid handler.
        handler: HttpServerResponse
        | Effect[HttpServerResponse, Any, Any]
        | Callable[[ServerRequest], Effect[HttpServerResponse, Any, Any]],
        *,
        uninterruptible: bool = False,
        redacted_params: Sequence[str] = (),
    ) -> Effect[None, Never, Any]:
        """Add a route. ``handler`` is a response, an effect, or a function
        of the request; it runs interruptibly unless ``uninterruptible``.
        ``redacted_params`` are as in ``route``."""
        route = Route(
            method,
            path if self._prefix is None else prefix_path(path, self._prefix),
            to_effect(handler),
            uninterruptible,
            self._prefix,
            redacted_param_names(redacted_params),
        )
        return self._core.add_all([route])

    @overload
    def add_all(self, routes: Sequence[Route[Never, Never]], /) -> Effect[None]: ...
    @overload
    def add_all[E](
        self, routes: Sequence[Route[E, Never]], /
    ) -> Effect[None, Never, Raises[E]]: ...
    @overload
    def add_all[R](
        self, routes: Sequence[Route[Never, R]], /
    ) -> Effect[None, Never, Requires[R]]: ...
    @overload
    def add_all[E, R](
        self, routes: Sequence[Route[E, R]], /
    ) -> Effect[None, Never, Requires[R] | Raises[E]]: ...
    def add_all(self, routes: Sequence[Route[Any, Any]], /) -> Effect[None, Never, Any]:
        """Add several routes (under this router's prefix)."""
        if self._prefix is not None:
            routes = [prefix_route(self._prefix)(route) for route in routes]
        return self._core.add_all(routes)

    def add_global_middleware(self, middleware: GlobalMiddlewareFn) -> Effect[None]:
        """Wrap every request, matched or not. Added first is outermost."""
        return sync(lambda: self._add_global(middleware))

    def _add_global(self, middleware: GlobalMiddlewareFn) -> None:
        if middleware not in self._core.global_middleware:
            self._core.global_middleware.append(middleware)

    def as_http_effect(self) -> Effect[HttpServerResponse, Any, HttpServerRequest]:
        """The app: routes each request, failing with ``RouteNotFound``
        when nothing matches."""
        return self._core.as_http_effect()


class HttpRouter(Tag[HttpRouterService], key="effect/http/HttpRouter"):
    """Tag of the HTTP router that layers add routes to and requests are matched against."""


def _make(config: find_my_way.RouterConfig) -> HttpRouterService:
    return HttpRouterService(_Core(config, find_my_way.Router[_Entry](config)))


make: Effect[HttpRouterService] = RouterConfig().map(_make)
