"""Router middleware: per-route (``Middleware.layer``) or global."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, Never, TypedDict, Unpack, cast, overload

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._layer_core import CurrentMemoMap, Layer, effect_context, fork_or_create, require_layer
from pyfect.context import Context
from pyfect.effect import succeed
from pyfect.http import middleware as http_middleware
from pyfect.http.middleware._cors import AllowedOrigins
from pyfect.http.router._markers import GlobalRaises, GlobalRequires, Raises, Requires, Unhandled
from pyfect.http.router._middleware_stack import (
    MiddlewareFn,
    MiddlewareFnTag,
    middleware_of,
    new_stack_tag,
)
from pyfect.http.router._provided import GlobalProvided, Provided
from pyfect.http.router._router import HttpRouter
from pyfect.http.server_response import HttpServerResponse
from pyfect.layer import effect_discard, provide, provide_merge, succeed_context
from pyfect.scope import Scope


class CorsOptions(TypedDict, total=False):
    allowed_origins: AllowedOrigins
    allowed_methods: Sequence[str]
    allowed_headers: Sequence[str]
    exposed_headers: Sequence[str]
    max_age: int | None
    credentials: bool


type _In = Effect[HttpServerResponse, Unhandled]
type MiddlewareFunction[E, R] = Callable[[_In], Effect[HttpServerResponse, E | Unhandled, R]]


class Middleware[E = Never, R = Never, LE = Never, LR = Never]:
    """Route middleware. Provide ``layer`` to the route layers it wraps;
    it runs inside the global middleware, for matched routes only.

    ``E`` and ``R`` are what it adds to each route's errors and
    requirements; ``LE`` and ``LR`` what building it may fail with and
    needs."""

    __slots__ = ("_dependencies", "_fn_layer", "layer")

    def __init__(
        self,
        fn_layer: Layer[Any, Any, Any],
        dependencies: Layer[Any, Any, Any] | None = None,
    ) -> None:
        self._fn_layer = fn_layer
        self._dependencies = dependencies
        stack_tag = new_stack_tag()

        def build(fiber: Fiber[Any, Any]) -> Effect[Context[Any], Any, Any]:
            context = fiber._context
            stack: list[MiddlewareFn] = [context.get_unsafe(MiddlewareFnTag)]
            if dependencies is None:
                return succeed(Context({stack_tag: stack}))
            found, memo = context.lookup(CurrentMemoMap)
            built = dependencies.build_with_memo_map(
                memo if found else fork_or_create(context), context.get_unsafe(Scope)
            )
            return built.map(lambda deps: Context({stack_tag: [*stack, *middleware_of(deps)]}))

        stacked: Layer[Any, Any, Any] = effect_context(_WithFiber(build))
        self.layer: Layer[Never, LE, LR | Requires[R] | Raises[E]] = stacked.pipe(provide(fn_layer))

    def combine[E2, R2, LE2, LR2](
        self, other: Middleware[E2, R2, LE2, LR2]
    ) -> Middleware[E | E2, R | R2, LE | LE2, LR | LR2]:
        """This middleware, running inside ``other``."""
        dependencies = (
            other.layer
            if self._dependencies is None
            else self._dependencies.pipe(provide_merge(other.layer))
        )
        return Middleware(self._fn_layer, dependencies)


def _fn_layer(fn: object) -> Layer[Any, Any, Any]:
    if isinstance(fn, Effect):
        made = cast("Effect[Any, Any, Any]", fn)
        return effect_context(made.map(lambda f: Context({MiddlewareFnTag: f})))
    return succeed_context(Context({MiddlewareFnTag: fn}))


def _global_layer(fn: object) -> Layer[Never, Any, Any]:
    made = cast("Effect[Any, Any, Any]", fn if isinstance(fn, Effect) else succeed(fn))
    return effect_discard(
        HttpRouter().flat_map(lambda router: made.flat_map(router.add_global_middleware))
    )


# Requirements only the router provides (or none) come first: pyright cannot
# solve ``R`` in ``R | Provided`` from ``Never``.
@overload
def middleware[E = Never](
    fn: Callable[[_In], Effect[HttpServerResponse, E | Unhandled, Provided]],
    /,
    *,
    global_: Literal[False] = False,
) -> Middleware[E]: ...
@overload
def middleware[E = Never, R = Never](
    fn: Callable[[_In], Effect[HttpServerResponse, E | Unhandled, R | Provided]],
    /,
    *,
    global_: Literal[False] = False,
) -> Middleware[E, R]: ...
@overload
def middleware[LE, LR, E = Never, R = Never](
    fn: Effect[Callable[[_In], Effect[HttpServerResponse, E | Unhandled, R | Provided]], LE, LR],
    /,
    *,
    global_: Literal[False] = False,
) -> Middleware[E, R, LE, LR]: ...
@overload
def middleware[E = Never](
    fn: Callable[[_In], Effect[HttpServerResponse, E | Unhandled, GlobalProvided]],
    /,
    *,
    global_: Literal[True],
) -> Layer[Never, Never, HttpRouter | GlobalRaises[E]]: ...
@overload
def middleware[E = Never, R = Never](
    fn: Callable[[_In], Effect[HttpServerResponse, E | Unhandled, R | GlobalProvided]],
    /,
    *,
    global_: Literal[True],
) -> Layer[Never, Never, HttpRouter | GlobalRequires[R] | GlobalRaises[E]]: ...
@overload
def middleware[LE, LR, E = Never, R = Never](
    fn: Effect[
        Callable[[_In], Effect[HttpServerResponse, E | Unhandled, R | GlobalProvided]], LE, LR
    ],
    /,
    *,
    global_: Literal[True],
) -> Layer[Never, LE, HttpRouter | LR | GlobalRequires[R] | GlobalRaises[E]]: ...
def middleware(fn: object, /, *, global_: bool = False) -> Any:
    """Middleware from a function of the handler (or an effect making
    one). The handler's own errors arrive as ``Unhandled``, which the
    result must keep.

    ``global_=True`` gives a layer wrapping every request, matched or not,
    instead."""
    return _global_layer(fn) if global_ else Middleware(_fn_layer(fn))


def cors(**options: Unpack[CorsOptions]) -> Layer[Never, Never, HttpRouter]:
    """``http.middleware.cors`` for every request, as global middleware."""
    return _global_layer(http_middleware.cors(**options))


disable_logger: Layer[Never, Never, Requires[Never] | Raises[Never]] = Middleware[Never, Never](
    _fn_layer(http_middleware.with_logger_disabled)
).layer
"""Route middleware turning off the request log for the routes it wraps."""


def provide_request[A2, E2, R2](
    services: Layer[A2, E2, R2],
) -> Callable[[Layer[Any, Any, Any]], Layer[Any, Any, Any]]:
    """Build ``services`` once and provide them to every request of the
    route layers this wraps. Use with ``.pipe``."""
    require_layer(services, "services")

    def fn(context: Context[Any]) -> Callable[[_In], Effect[HttpServerResponse, Unhandled]]:
        return lambda eff: eff.pipe(provide(context))

    made: Effect[Any, Any, Any] = services.build().map(fn)
    return provide(Middleware(_fn_layer(made)).layer)
