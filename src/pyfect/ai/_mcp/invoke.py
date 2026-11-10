"""How a registration's handler runs for a request (Effect's ``makeInvoke``):
with the services captured when it was registered, under the request's own,
inside the MCP middleware provided to it and to the whole server.

A middleware layer adds a stack (its function, then its dependencies') under
a tag of its own; ``middleware_of`` orders every stack of a context into one
list, innermost first. Visibility checks are middleware whose function is in
``is_gate``: they fail with ``Hidden``, which ``Invoke`` turns into the
request's not-found error, or a ``False`` on list requests.
"""

from __future__ import annotations

import itertools
import types
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import reduce
from typing import Any, ClassVar, Literal, Never, cast, final

import pyfect as fx
from pyfect import error_reporter
from pyfect._core import Effect
from pyfect.ai.mcp_schema import (
    INVALID_PARAMS_ERROR_CODE,
    InternalError,
    JsonObject,
    McpError,
    McpRequestContext,
    McpServerClient,
    RequestContext,
)
from pyfect.cause import Cause, Fail
from pyfect.context import Context, Reference, Tag
from pyfect.effect import fail, fail_cause, gen, service_option, succeed, update_context
from pyfect.errors import TaggedError
from pyfect.http.router import RouteContext
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams
from pyfect.logger import CurrentLogLevel
from pyfect.scope import Scope
from pyfect.tracer import ParentSpan

SESSION_HEADER = "mcp-session-id"

type MiddlewareMethod = Literal[
    "tools/call",
    "resources/read",
    "prompts/get",
    "completion/complete",
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
    "skills/list",
    "skills/get",
    "resources/directory/read",
]
"""The requests that run MCP middleware. More may be added: a ``match`` on it
needs a default case."""

type CallMethod = Literal[
    "tools/call", "resources/read", "prompts/get", "completion/complete", "skills/get"
]
type ListMethod = Literal[
    "tools/list",
    "resources/list",
    "resources/templates/list",
    "prompts/list",
    "skills/list",
    "resources/directory/read",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class MiddlewareOptions:
    """The request a middleware wraps.

    ``target`` is the tool name, the resource URI or the prompt name; for
    ``completion/complete`` the prompt name or the URI template; for
    ``skills/get`` the URI of the skill's ``SKILL.md``. ``payload`` holds the
    request's parameters. On a list request, which runs middleware only around
    a visibility, once per registration, ``target`` is that registration's
    name, URI or URI template and ``payload`` is ``None``.

    ``headers`` are the HTTP request's, empty on stdio and in process;
    ``session_id`` is its ``mcp-session-id`` header."""

    method: MiddlewareMethod
    target: str
    payload: object
    request_context: RequestContext
    headers: Mapping[str, str]
    session_id: str | None


@final
class MiddlewareSuccess:
    """A handler's result as middleware sees it: it can wrap the handler and
    provide services, but not read or replace what it returns."""

    __slots__ = ()


type AnyMiddlewareFn = Callable[[Effect[Any, Any, Any], MiddlewareOptions], Effect[Any, Any, Any]]


type Deliver = Callable[[str, JsonObject], Effect[None]]
"""Sends a notification on the stream of the request being served."""


class RequestOutbound(Tag[Deliver], key="pyfect/ai/McpServer/RequestOutbound"):
    """Where the request being served sends its log messages and progress."""


class MiddlewareStack(
    Tag[tuple[AnyMiddlewareFn, ...]], key="effect/ai/McpServer/Middleware", base=True
):
    """The base of each middleware layer's own stack tag."""


_ids = itertools.count(1)


def new_stack_tag() -> type[MiddlewareStack]:
    key = f"effect/ai/McpServer/Middleware-{next(_ids)}"
    return types.new_class(key.rsplit("/", 1)[1], (MiddlewareStack,), {"key": key})


def middleware_of(context: Context[Any]) -> tuple[AnyMiddlewareFn, ...]:
    """Every stack of ``context`` in one list, innermost first. Each stack
    keeps its own order; where that leaves the order open, a stack provided
    further outside (earlier in the context) runs further outside. Stacks
    ordering the same middleware both ways have no common order, so the
    first one seen decides."""
    inners: dict[AnyMiddlewareFn, list[AnyMiddlewareFn]] = {}
    unplaced_outers: dict[AnyMiddlewareFn, int] = {}
    for tag, stack in context.map_unsafe.items():
        if not issubclass(tag, MiddlewareStack):
            continue
        fns = cast("tuple[AnyMiddlewareFn, ...]", stack)
        for index in range(len(fns) - 1, -1, -1):
            fn = fns[index]
            if fn not in inners:
                inners[fn] = []
                unplaced_outers[fn] = 0
            outer = fns[index + 1] if index + 1 < len(fns) else None
            if outer is not None and outer is not fn:
                inners[outer].append(fn)
                unplaced_outers[fn] += 1
    outermost_first: list[AnyMiddlewareFn] = []
    while unplaced_outers:
        placed = next((fn for fn, count in unplaced_outers.items() if count == 0), None)
        chosen = placed if placed is not None else next(iter(unplaced_outers))
        del unplaced_outers[chosen]
        outermost_first.append(chosen)
        for inner in inners[chosen]:
            if inner in unplaced_outers:
                unplaced_outers[inner] -= 1
    return tuple(reversed(outermost_first))


def middleware_stack(
    local: tuple[AnyMiddlewareFn, ...], global_: list[AnyMiddlewareFn]
) -> tuple[AnyMiddlewareFn, ...]:
    """The local middleware inside the global; one provided both ways runs
    once, at its outermost place."""
    if not global_:
        return local
    if not local:
        return tuple(global_)
    stack = (*local, *global_)
    last = {fn: index for index, fn in enumerate(stack)}
    return tuple(fn for index, fn in enumerate(stack) if last[fn] == index)


_gates: weakref.WeakSet[AnyMiddlewareFn] = weakref.WeakSet()


def mark_gate(fn: AnyMiddlewareFn) -> AnyMiddlewareFn:
    """Mark ``fn`` as a visibility check's middleware."""
    _gates.add(fn)
    return fn


def is_gate(fn: AnyMiddlewareFn) -> bool:
    return fn in _gates


@dataclass(eq=False)
class Hidden(McpError):
    """A visibility check hid the registration. Middleware outside it sees an
    MCP error; ``Invoke`` replaces it with the request's not-found error."""

    _tag: ClassVar[str] = "effect/ai/McpServer/Hidden"
    CODE: ClassVar[int] = INVALID_PARAMS_ERROR_CODE


HIDDEN: Effect[Never, Hidden] = fail(Hidden("Not found"))


@dataclass(eq=False)
class RequestRejected(TaggedError):
    """A request refused outside its handler (by middleware, or hidden).
    Transports answer it as a JSON-RPC error with ``error`` 's code, message
    and data, never as a tool result; in-process callers get ``error``."""

    error: McpError


@dataclass(eq=False)
class ResourceNotFound(TaggedError):
    """No resource serves ``uri`` for this request (a hidden one included):
    each transport answers its revision's not-found error."""

    uri: str


class _HandlerFailure(Reference[bool], key="effect/ai/McpServer/HandlerFailure"):
    """Marks a cause as the handler's own, not one middleware raised."""

    @classmethod
    def default(cls) -> bool:
        return False


_HANDLER_FAILURE = Context.make(_HandlerFailure, True)
_INTERNAL_ERROR = RequestRejected(InternalError("Internal error"))


def _rejected(cause: Cause[Any], middleware: tuple[AnyMiddlewareFn, ...]) -> Effect[Never, Any]:
    """A failed run's outcome: interruption and the handler's own failures
    pass through, ``Hidden`` is kept, a middleware's MCP error is rejected
    with it; anything else is logged, reported and an internal error."""
    if cause.has_interrupts:
        return fail_cause(cause)
    found = cause.find_recoverable_error()
    if isinstance(found, Fail):
        error = found.error
        if isinstance(error, Hidden):
            return fail(error)
        if not middleware or Context(dict(found.annotations)).get_or_else(
            _HandlerFailure, lambda: False
        ):
            return fail_cause(cause)
        if isinstance(error, McpError):
            return fail(RequestRejected(error))
    reported = fx.log_error(cause).and_then(error_reporter.report(cause))
    return reported.and_then(fail(_INTERNAL_ERROR))


def run_middleware[A, E](
    handler: Effect[A, E, Any],
    middleware: tuple[AnyMiddlewareFn, ...],
    method: MiddlewareMethod,
    target: str,
    payload: object,
) -> Effect[A, E | Hidden | RequestRejected, McpRequestContext]:
    """``handler`` inside ``middleware`` (innermost first)."""
    if not middleware:
        run: Effect[Any, Any, Any] = handler
    else:

        @gen
        def wrapped():
            context = yield from McpRequestContext()
            request = yield from service_option(HttpServerRequest)
            headers: Mapping[str, str] = {} if request is None else request.value.headers
            options = MiddlewareOptions(
                method=method,
                target=target,
                payload=payload,
                request_context=context,
                headers=headers,
                session_id=headers.get(SESSION_HEADER),
            )
            handled: Effect[Any, Any, Any] = handler.catch_cause(
                lambda cause: fail_cause(cause.annotate(_HANDLER_FAILURE))
            )
            return (yield from reduce(lambda effect, fn: fn(effect, options), middleware, handled))

        run = wrapped
    return run.catch_cause(lambda cause: _rejected(cause, middleware))


def omit_request_services(context: Context[Any]) -> Context[Any]:
    """``context`` without what a request provides, or a middleware layer
    adds: a registration made during one request serves later ones with
    their own."""
    request_tags: frozenset[type[Tag[Any]]] = frozenset(
        {
            McpRequestContext,
            McpServerClient,
            HttpServerRequest,
            ParsedSearchParams,
            RouteContext,
            CurrentLogLevel,
            Scope,
            ParentSpan,
            RequestOutbound,
        }
    )
    return Context(
        {
            tag: service
            for tag, service in context.map_unsafe.items()
            if tag not in request_tags and not issubclass(tag, MiddlewareStack)
        }
    )


def unwrap_rejected[A, E, R](
    effect: Effect[A, E | RequestRejected, R],
) -> Effect[A, E | McpError, R]:
    """``effect`` failing with the MCP error a request was rejected with."""

    def unwrap(cause: Cause[Any]) -> Effect[Never, Any]:
        found = None if cause.has_interrupts else cause.find_recoverable_error()
        if isinstance(found, Fail) and isinstance(found.error, RequestRejected):
            return fail(found.error.error)
        return fail_cause(cause)

    return cast("Any", effect.catch_cause(unwrap))


def _is_hidden(cause: Cause[Any]) -> bool:
    if cause.has_interrupts:
        return False
    found = cause.find_recoverable_error()
    return isinstance(found, Fail) and isinstance(found.error, Hidden)


@dataclass(frozen=True, slots=True)
class Invoke:
    """Runs one registration's handlers (Effect's ``makeInvoke``): with the
    services captured at registration under the request's, inside its local
    middleware and the server's global middleware (read on each call)."""

    services: Context[Any]
    local: tuple[AnyMiddlewareFn, ...]
    global_: list[AnyMiddlewareFn]

    @staticmethod
    def make(services: Context[Any] | None, global_: list[AnyMiddlewareFn]) -> Invoke:
        if services is None:
            return Invoke(Context.empty(), (), global_)
        return Invoke(omit_request_services(services), middleware_of(services), global_)

    def __call__[A, E, X](
        self,
        handler: Effect[A, E, Any],
        *,
        method: CallMethod,
        target: str,
        payload: object,
        hidden: X,
    ) -> Effect[A, E | X | RequestRejected, McpRequestContext]:
        """``handler`` for a request; a visibility hiding it fails with
        ``hidden``, the request's not-found error."""
        services = self.services
        provided: Effect[A, E, Any] = handler
        if services.map_unsafe:

            def under_request(current: Context[Any]) -> Context[Any]:
                return services.merge(current)

            provided = handler.pipe(update_context(under_request))
        stack = middleware_stack(self.local, self.global_)
        ran = run_middleware(provided, stack, method, target, payload)

        def recover(cause: Cause[Any]) -> Effect[Never, Any]:
            return fail(hidden) if _is_hidden(cause) else fail_cause(cause)

        return cast("Any", ran.catch_cause(recover))

    def visible(
        self, method: ListMethod, target: str
    ) -> Effect[bool, RequestRejected, McpRequestContext]:
        """Whether a list request shows the registration: only the middleware
        outside the innermost visibility runs, and a failure fails the list."""
        stack = middleware_stack(self.local, self.global_)
        innermost = next((index for index, fn in enumerate(stack) if is_gate(fn)), None)
        if innermost is None:
            return succeed(True)
        ran = run_middleware(succeed(None), stack[innermost:], method, target, None)

        def recover(cause: Cause[Any]) -> Effect[bool, Any]:
            return succeed(False) if _is_hidden(cause) else fail_cause(cause)

        return cast("Any", ran.as_(True).catch_cause(recover))
