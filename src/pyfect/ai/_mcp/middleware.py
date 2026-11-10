"""MCP middleware (Effect's ``McpServer.middleware`` and ``visibility``).

A ``Middleware``'s ``layer``, provided to registration layers (or to the
effect registering), runs it around those registrations' requests;
``layer_global`` runs it around every request of the server. Its function
gets the handler, as an opaque ``Effect[MiddlewareSuccess, McpError, P]``,
and the request's ``MiddlewareOptions``; it provides ``P`` (the services it
declares) and may fail with an ``McpError``, sent as a JSON-RPC error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Never, cast, overload

from pyfect._core import Effect
from pyfect._layer_core import CurrentMemoMap, Layer, effect_context, fork_or_create
from pyfect.ai._mcp.core import McpServer
from pyfect.ai._mcp.invoke import (
    HIDDEN,
    AnyMiddlewareFn,
    MiddlewareOptions,
    MiddlewareSuccess,
    mark_gate,
    middleware_of,
    new_stack_tag,
)
from pyfect.ai.mcp_schema import McpError
from pyfect.context import Context, Tag, TagLike
from pyfect.effect import context as fx_context
from pyfect.effect import gen, succeed, sync
from pyfect.layer import effect_discard, provide, provide_merge, succeed_context
from pyfect.scope import Scope, acquire_release

type MiddlewareFunction[P, E: McpError, R] = Callable[
    [Effect[MiddlewareSuccess, McpError, P], MiddlewareOptions],
    Effect[MiddlewareSuccess, E, R],
]
"""A middleware: given the handler and the request, the handler run (with
the services ``P`` provided), or a failure."""

type VisibilityCheck[E: McpError, R] = Callable[[MiddlewareOptions], Effect[bool, E, R]]
"""Whether the request may see the registration."""


class _FnTag(Tag[AnyMiddlewareFn], key="effect/ai/McpServer/MiddlewareFn"):
    """The function a ``Middleware`` layer adds."""


class Middleware[P = Never, R = Never, LE = Never]:
    """Composable MCP middleware.

    ``P`` is what it provides the handlers inside it, ``R`` what it needs:
    per request (from middleware outside it, or the transport) and to be
    built, in one parameter, as a union of two defaulted parameters widens to
    ``Unknown``. ``LE`` is what building it may fail with. ``layer`` claims
    ``P`` for the registrations it is provided to: Python has no request-level
    marker types, so a request-level service is the service itself."""

    __slots__ = ("_dependencies", "_fn_layer", "layer", "layer_global")

    # Declared mutable, so every parameter is invariant: ``combine`` then
    # discharges ``R`` only when ``other`` provides exactly it.
    layer: Layer[P, LE, R]
    """Runs the middleware around the registrations it is provided to."""
    layer_global: Layer[P, LE, R | McpServer]
    """Runs the middleware around every request of the server, once even
    when it is also provided locally (at its outermost place)."""

    def __init__(
        self, fn_layer: Layer[Any, Any, Any], dependencies: Layer[Any, Any, Any] | None = None
    ) -> None:
        self._fn_layer = fn_layer
        self._dependencies = dependencies
        stack_tag = new_stack_tag()

        def build(context: Context[Any]) -> Effect[Context[Any], Any, Any]:
            stack: tuple[AnyMiddlewareFn, ...] = (context.get_unsafe(_FnTag),)
            if dependencies is None:
                return succeed(Context({stack_tag: stack}))
            found, memo = context.lookup(CurrentMemoMap)
            built = dependencies.build_with_memo_map(
                memo if found else fork_or_create(context), context.get_unsafe(Scope)
            )
            return built.map(lambda deps: Context({stack_tag: (*stack, *middleware_of(deps))}))

        stacked: Layer[Any, Any, Any] = effect_context(fx_context().flat_map(build)).pipe(
            provide(fn_layer)
        )

        @gen
        def install():
            server = yield from McpServer()
            built: Context[Any] = yield from fx_context()
            stack = built.get_unsafe(stack_tag)

            def add() -> Effect[None]:
                return _sync(lambda: server.global_middleware.extend(stack))

            def remove(_: object, __: object) -> Effect[None]:
                def drop() -> None:
                    for fn in stack:
                        if fn in server.global_middleware:
                            server.global_middleware.remove(fn)

                return _sync(drop)

            yield from acquire_release(add(), remove)

        self.layer = cast("Any", stacked)
        self.layer_global = cast("Any", effect_discard(install).pipe(provide(stacked)))

    @overload
    def combine[P2, R2, LE2](
        self: Middleware[P, Never, LE], other: Middleware[P2, R2, LE2]
    ) -> Middleware[P | P2, R2, LE | LE2]: ...
    @overload
    def combine[P2, R2, LE2](
        self: Middleware[P, P2, LE], other: Middleware[P2, R2, LE2]
    ) -> Middleware[P | P2, R2, LE | LE2]: ...
    @overload
    def combine[P2, R2, LE2](
        self, other: Middleware[P2, R2, LE2]
    ) -> Middleware[P | P2, R | R2, LE | LE2]: ...
    def combine(self, other: Middleware[Any, Any, Any]) -> Middleware[Any, Any, Any]:
        """This middleware running inside ``other``, which can provide what
        it reads."""
        dependencies = (
            other.layer
            if self._dependencies is None
            else self._dependencies.pipe(provide_merge(other.layer))
        )
        return Middleware(self._fn_layer, dependencies)


def _sync(f: Callable[[], object]) -> Effect[None]:
    return sync(f).as_void()


def _fn_layer(fn: object) -> Layer[Any, Any, Any]:
    if isinstance(fn, Effect):
        made = cast("Effect[Any, Any, Any]", fn)
        return effect_context(made.map(lambda f: Context({_FnTag: f})))
    return succeed_context(Context({_FnTag: fn}))


# The declared ``provides`` only types the layers; ``P`` is solved from it.
@overload
def middleware[E: McpError = Never, R = Never](
    fn: MiddlewareFunction[Never, E, R], /, *, global_: Literal[False] = False
) -> Middleware[Never, R]: ...
@overload
def middleware[P, E: McpError = Never, R = Never](
    fn: MiddlewareFunction[P, E, R],
    /,
    *,
    provides: TagLike[Any, P] | tuple[TagLike[Any, P], ...],
    global_: Literal[False] = False,
) -> Middleware[P, R]: ...
@overload
def middleware[LE, E: McpError = Never, R = Never](
    fn: Effect[MiddlewareFunction[Never, E, R], LE, R],
    /,
    *,
    global_: Literal[False] = False,
) -> Middleware[Never, R, LE]: ...
@overload
def middleware[P, LE, E: McpError = Never, R = Never](
    fn: Effect[MiddlewareFunction[P, E, R], LE, R],
    /,
    *,
    provides: TagLike[Any, P] | tuple[TagLike[Any, P], ...],
    global_: Literal[False] = False,
) -> Middleware[P, R, LE]: ...
@overload
def middleware[P = Never, E: McpError = Never, R = Never](
    fn: MiddlewareFunction[P, E, R],
    /,
    *,
    provides: TagLike[Any, P] | tuple[TagLike[Any, P], ...] = (),
    global_: Literal[True],
) -> Layer[P, Never, R | McpServer]: ...
@overload
def middleware[LE, P = Never, E: McpError = Never, R = Never](
    fn: Effect[MiddlewareFunction[P, E, R], LE, R],
    /,
    *,
    provides: TagLike[Any, P] | tuple[TagLike[Any, P], ...] = (),
    global_: Literal[True],
) -> Layer[P, LE, R | McpServer]: ...
def middleware(fn: object, /, *, provides: object = (), global_: bool = False) -> Any:
    """MCP middleware from a function (or an effect making one) run around
    ``tools/call``, ``resources/read``, ``prompts/get`` and
    ``completion/complete``, and around list requests only when it wraps a
    ``visibility``. ``provides`` names the services it provides the handler
    (the tags; only their types matter)::

        auth = mcp_server.middleware(
            lambda effect, options: effect.pipe(
                fx.provide_service(CurrentUser, options.headers.get("authorization", ""))
            ),
            provides=CurrentUser,
        )

    A failure is an ``McpError``, sent as a JSON-RPC error with its code,
    message and data; a defect is logged, reported and sent as
    ``Internal error``; interruption propagates. Local middleware runs
    inside global middleware. ``global_=True`` gives ``layer_global``."""
    del provides
    made = Middleware[Any, Any, Any](_fn_layer(fn))
    return made.layer_global if global_ else made


def _gate(check: Callable[[MiddlewareOptions], Effect[bool, Any, Any]]) -> AnyMiddlewareFn:
    def gate(effect: Effect[Any, Any, Any], options: MiddlewareOptions) -> Effect[Any, Any, Any]:
        return check(options).flat_map(lambda visible: effect if visible else HIDDEN)

    return mark_gate(gate)


@overload
def visibility[E: McpError = Never, R = Never](
    check: VisibilityCheck[E, R], /, *, global_: Literal[False] = False
) -> Middleware[Never, R]: ...
@overload
def visibility[LE, E: McpError = Never, R = Never](
    check: Effect[VisibilityCheck[E, R], LE, R], /, *, global_: Literal[False] = False
) -> Middleware[Never, R, LE]: ...
@overload
def visibility[E: McpError = Never, R = Never](
    check: VisibilityCheck[E, R], /, *, global_: Literal[True]
) -> Layer[Never, Never, R | McpServer]: ...
@overload
def visibility[LE, E: McpError = Never, R = Never](
    check: Effect[VisibilityCheck[E, R], LE, R], /, *, global_: Literal[True]
) -> Layer[Never, LE, R | McpServer]: ...
def visibility(check: object, /, *, global_: bool = False) -> Any:
    """Middleware hiding registrations per request: where ``check`` gives
    ``False``, the registration is left out of lists and a request for it
    fails as if it were not registered. It runs on list requests and on
    calls, reads, gets and completions, with the middleware outside it (once
    per registration on a list; the middleware inside does not run there). A
    failure of that middleware or of ``check`` fails the whole list.

    Unlike ``EnabledWhen``, middleware sees requests for hidden registrations
    (as an ``McpError``)."""
    if isinstance(check, Effect):
        made: object = cast("Effect[Any, Any, Any]", check).map(_gate)
    else:
        made = _gate(cast("Callable[[MiddlewareOptions], Effect[bool, Any, Any]]", check))
    built = Middleware[Any, Any, Any](_fn_layer(made))
    return built.layer_global if global_ else built
