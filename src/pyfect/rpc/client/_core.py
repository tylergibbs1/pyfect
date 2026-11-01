"""The RPC client without serialization (Effect's
``RpcClient.makeNoSerialization``): requests out through
``on_from_client``, decoded responses in through ``write``."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Never

from pyfect import exit as Exit
from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._interrupt_reason import interrupt_closed
from pyfect.context import Context, Reference
from pyfect.effect import (
    callback,
    context,
    from_exit,
    gen,
    provide_service,
    succeed,
)
from pyfect.http.headers import Headers, from_input
from pyfect.queue import Queue
from pyfect.rpc._methods import CallOptions, StreamMethod, UnaryMethod
from pyfect.rpc._rpc import AnyRpc
from pyfect.rpc.group import RpcGroup
from pyfect.rpc.message import (
    Ack,
    ClientEnd,
    FromClient,
    FromServer,
    Interrupt,
    Request,
    RequestId,
    ResponseChunk,
    ResponseDefect,
    ResponseExit,
)
from pyfect.rpc.middleware import ClientMiddlewareOptions, client_tag
from pyfect.scope import Scope, fork_in
from pyfect.tracer import AnySpan, make_span_scoped

_VOID: Effect[None] = succeed(None)


class CurrentHeaders(Reference[Headers], key="effect/rpc/RpcClient/CurrentHeaders"):
    """Headers added to every request a client sends from here."""

    @classmethod
    def default(cls) -> Headers:
        return Headers()


class _WithHeaders:
    __slots__ = ("headers",)

    def __init__(self, headers: Headers) -> None:
        self.headers = headers

    def __call__[A, E, R](self, target: Effect[A, E, R]) -> Effect[A, E, R]:
        return CurrentHeaders().flat_map(
            lambda current: target.pipe(
                provide_service(CurrentHeaders, current.merge(self.headers))
            )
        )


def with_headers(headers: Mapping[str, str] | Headers) -> _WithHeaders:
    """Send ``headers`` with the requests made inside:
    ``eff.pipe(with_headers({"authorization": token}))``."""
    return _WithHeaders(from_input(headers))


@dataclass(frozen=True, slots=True)
class OnFromClient:
    """A message for the protocol, with the call's services ``context``
    and whether its caller ``discard``\\s the result."""

    message: FromClient
    context: Context[Any]
    discard: bool


type SendFn = Callable[[OnFromClient], Effect[None, Any]]


@dataclass(frozen=True, slots=True)
class ClientOptions:
    """How a client calls: spans named after the tag, or ``<span_prefix>.<tag>`` (none with
    ``disable_tracing``); ``supports_ack`` sends an ``Ack`` after each
    chunk taken."""

    span_prefix: str | None = None
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    disable_tracing: bool = False
    supports_ack: bool = True
    generate_request_id: Callable[[], RequestId] | None = None


_request_ids = itertools.count()


@dataclass(slots=True, eq=False)
class _EffectEntry:
    rpc: AnyRpc
    context: Context[Any]
    resume: Callable[[Exit.Exit[Any, Any]], None]


@dataclass(slots=True, eq=False)
class _QueueEntry:
    rpc: AnyRpc
    queue: Queue[Any, Any]
    context: Context[Any]


type _Entry = _EffectEntry | _QueueEntry


class ClientCore:
    """The state of a client: the requests waiting for responses."""

    __slots__ = ("_entries", "_is_shutdown", "_options", "_send", "_services")

    def __init__(self, send: SendFn, options: ClientOptions, services: Context[Any]) -> None:
        self._send = send
        self._options = options
        self._services = services
        self._entries: dict[RequestId, _Entry] = {}
        self._is_shutdown = False

    def _next_id(self) -> RequestId:
        generate = self._options.generate_request_id
        return next(_request_ids) if generate is None else generate()

    def _span_name(self, rpc: AnyRpc) -> str:
        prefix = self._options.span_prefix
        return rpc.tag if prefix is None else f"{prefix}.{rpc.tag}"

    def _span_attributes(self, rpc: AnyRpc) -> dict[str, object]:
        attributes: dict[str, object] = {"rpc.system.name": "effect_rpc", "rpc.method": rpc.tag}
        attributes.update(self._options.span_attributes)
        return attributes

    # --- shutdown -----------------------------------------------------------------------

    def close(self) -> Effect[None]:
        def body(parent: Fiber[Any, Any]) -> Effect[None]:
            self._is_shutdown = True
            return self._clear(Exit.interrupt(parent.id))

        return _WithFiber(body)

    def _clear(self, exit: Exit.Exit[Never, Never]) -> Effect[None]:
        pending = list(self._entries.values())
        self._entries.clear()

        @gen
        def clear():
            for entry in pending:
                if isinstance(entry, _QueueEntry):
                    if isinstance(exit, Exit.Failure):
                        yield from entry.queue.fail_cause(exit.cause)
                    else:
                        entry.queue.end_unsafe()
                else:
                    entry.resume(exit)

        return clear.uninterruptible()

    # --- middleware -----------------------------------------------------------------------

    def _with_middleware(
        self, rpc: AnyRpc, send: Callable[[Request], Effect[Any, Any]], request: Request
    ) -> Effect[Any, Any]:
        middlewares = [
            found.value
            for tag in rpc.middlewares
            if (found := self._services.get_option(client_tag(tag))) is not None
        ]

        def loop(request: Request, index: int) -> Effect[Any, Any]:
            if index == -1:
                return send(request)
            options = ClientMiddlewareOptions(rpc, request, lambda r: loop(r, index - 1))
            return middlewares[index](options)

        return loop(request, len(middlewares) - 1)

    def _request(
        self,
        fiber: Fiber[Any, Any],
        rpc: AnyRpc,
        id: RequestId,
        *,
        payload: object,
        call: CallOptions,
        span: AnySpan | None,
    ) -> Request:
        headers = fiber.get_ref(CurrentHeaders)
        if call.headers is not None:
            headers = headers.merge(from_input(call.headers))
        if span is None:
            return Request(id, rpc.tag, payload, headers)
        return Request(id, rpc.tag, payload, headers, span.trace_id, span.span_id, _sampled(span))

    def _send_interrupt(
        self, request_id: RequestId, context: Context[Any], interruptors: tuple[int, ...]
    ) -> Effect[None]:
        sent = self._send(OnFromClient(Interrupt(request_id, interruptors), context, False))
        return sent.timeout(1.0).exit().as_void()

    # --- unary calls -----------------------------------------------------------------

    def call(self, rpc: AnyRpc, payload: object, call: CallOptions) -> Effect[Any, Any]:
        if self._options.disable_tracing:
            return self._effect_request(rpc, payload, call, None)
        from pyfect.tracer import use_span

        return use_span(
            self._span_name(rpc),
            lambda span: self._effect_request(rpc, payload, call, span),
            kind="client",
            attributes=self._span_attributes(rpc),
        )

    def _effect_request(
        self, rpc: AnyRpc, payload: object, call: CallOptions, span: AnySpan | None
    ) -> Effect[Any, Any]:
        context = call.context or Context.empty()

        def body(parent: Fiber[Any, Any]) -> Effect[Any, Any]:
            if self._is_shutdown:
                return interrupt_closed("RPC client")
            id = self._next_id()
            send = self._with_middleware(
                rpc,
                lambda message: self._send(OnFromClient(message, context, call.discard)),
                self._request(parent, rpc, id, payload=payload, call=call, span=span),
            )
            if span is not None:
                send = send.with_parent_span(span, capture_stack_trace=False)
            if call.discard:
                return send.as_void()
            sender: list[Fiber[Any, Any]] = []

            def on_exit(exit: Exit.Exit[Any, Any]) -> Effect[None]:
                # Effect's ``onInterrupt``: any interruption, also the
                # client closing or the server's interrupted exit.
                if not (isinstance(exit, Exit.Failure) and exit.cause.has_interrupts):
                    return _VOID
                self._entries.pop(id, None)
                interruptors = tuple(sorted(exit.cause.interruptors))
                return (
                    sender[0]
                    .interrupt()
                    .flat_map(lambda _: self._send_interrupt(id, context, interruptors))
                )

            waiting: Effect[Any, Any] = callback(
                lambda resume: self._register(
                    parent, rpc, id, context, send=send, resume=resume, sender=sender
                )
            )
            return waiting.on_exit(on_exit)

        return _WithFiber(body)

    def _register(
        self,
        parent: Fiber[Any, Any],
        rpc: AnyRpc,
        id: RequestId,
        context: Context[Any],
        *,
        send: Effect[Any, Any],
        resume: Callable[[Effect[Any, Any]], None],
        sender: list[Fiber[Any, Any]],
    ) -> None:
        def done(exit: Exit.Exit[Any, Any]) -> None:
            resume(from_exit(exit))
            if sender and sender[0].poll_unsafe() is None:
                # Deferred to a task, as Effect's: the sender may be the
                # fiber delivering this reply.
                fiber = sender[0]
                parent._scheduler.schedule(lambda: fiber.interrupt_as_unsafe(parent.id))

        self._entries[id] = _EffectEntry(rpc, context, done)
        fiber = parent._fork(send, daemon=True, start_immediately=True)
        sender.append(fiber)

        def observe(exit: Exit.Exit[Any, Any]) -> None:
            if isinstance(exit, Exit.Failure):
                self._entries.pop(id, None)
                resume(from_exit(exit))

        fiber.add_observer_unsafe(observe)

    # --- stream calls ------------------------------------------------------------------

    def open_stream(
        self, rpc: AnyRpc, payload: object, call: CallOptions
    ) -> Effect[Queue[Any, Any], Never, Scope]:
        context = call.context or Context.empty()

        @gen
        def open():
            if self._is_shutdown:
                yield from interrupt_closed("RPC client")
            span = None
            if not self._options.disable_tracing:
                span = yield from make_span_scoped(
                    self._span_name(rpc), kind="client", attributes=self._span_attributes(rpc)
                )
            fiber = _current_fiber()
            id = self._next_id()
            scope = fiber._context.get_unsafe(Scope)
            queue = yield from Queue[Any, Any].bounded(call.stream_buffer_size)

            def finalize(exit: Exit.Exit[Any, Any]) -> Effect[None]:
                queue.shutdown_unsafe()
                if id not in self._entries:
                    return _VOID
                del self._entries[id]
                interruptors = (
                    tuple(sorted(exit.cause.interruptors)) if isinstance(exit, Exit.Failure) else ()
                )
                return self._send_interrupt(id, context, interruptors)

            yield from scope.add_finalizer(finalize)
            self._entries[id] = _QueueEntry(rpc, queue, context)
            send = self._with_middleware(
                rpc,
                lambda message: self._send(OnFromClient(message, context, False)),
                self._request(fiber, rpc, id, payload=payload, call=call, span=span),
            )
            if span is not None:
                send = send.with_parent_span(span, capture_stack_trace=False)

            def failed(cause: Any) -> Effect[None]:
                if not cause.has_interrupts_only:
                    self._entries.pop(id, None)
                return queue.fail_cause(cause).as_void()

            yield from fork_in(send.on_error(failed).interruptible(), scope, start_immediately=True)
            return queue

        return open

    # --- responses -------------------------------------------------------------------

    def write(self, message: FromServer) -> Effect[None]:
        """Hand the client a response."""
        match message:
            case ResponseChunk(request_id=request_id, values=values):
                entry = self._entries.get(request_id)
                if not isinstance(entry, _QueueEntry):
                    return _VOID
                return self._offer(entry, request_id, values)
            case ResponseExit(request_id=request_id, exit=exit):
                return self._exit(request_id, exit)
            case ResponseDefect(defect=defect):
                return self._clear(Exit.die(defect))
            case ClientEnd():
                return _VOID

    def _exit(self, request_id: RequestId, exit: Exit.Exit[Any, Any]) -> Effect[None]:
        entry = self._entries.pop(request_id, None)
        if entry is None:
            return _VOID
        if isinstance(entry, _EffectEntry):
            entry.resume(exit)
            return _VOID
        if isinstance(exit, Exit.Failure):
            return entry.queue.fail_cause(exit.cause).as_void()
        entry.queue.end_unsafe()
        return _VOID

    def _offer(
        self, entry: _QueueEntry, request_id: RequestId, values: tuple[Any, ...]
    ) -> Effect[None]:
        offered: Effect[Any, Any] = entry.queue.offer_all(values)
        if self._options.supports_ack:
            offered = offered.flat_map(
                lambda _: self._send(OnFromClient(Ack(request_id), entry.context, False))
            )
        return offered.catch_cause(lambda cause: entry.queue.fail_cause(cause).as_void())

    # --- the client ---------------------------------------------------------------------

    def methods(self, group: type[RpcGroup]) -> dict[str, Any]:
        """The client's methods, by RPC tag."""
        methods: dict[str, Any] = {}
        for rpc in group.rpcs.values():
            methods[rpc.tag] = self._method(rpc)
        return methods

    def _method(self, rpc: AnyRpc) -> Any:
        if rpc.is_stream:
            return StreamMethod[Any, Any, Any](
                lambda payload, call: self.open_stream(rpc, payload, call)
            )
        return UnaryMethod[Any, Any, Any](lambda payload, call: self.call(rpc, payload, call))


def make_no_serialization[G: RpcGroup](
    group: type[G], on_from_client: SendFn, options: ClientOptions | None = None
) -> Effect[tuple[G, ClientCore], Never, Scope]:
    """A client of ``group`` sending its requests with ``on_from_client``;
    hand it the responses with the core's ``write``. Closing the scope
    interrupts the calls waiting."""

    @gen
    def make():
        services = yield from context()
        scope = yield from Scope()
        core = ClientCore(on_from_client, options or ClientOptions(), services)
        yield from scope.add_finalizer(lambda _: core.close())
        client = group()
        client._rpc_methods = core.methods(group)
        return client, core

    return make


def _current_fiber() -> Fiber[Any, Any]:
    fiber = Fiber.get_current()
    if fiber is None:
        raise RuntimeError("an RPC client runs on a fiber")
    return fiber


def _sampled(span: AnySpan) -> bool:
    return bool(getattr(span, "sampled", True))


__all__ = [
    "ClientCore",
    "ClientOptions",
    "CurrentHeaders",
    "OnFromClient",
    "make_no_serialization",
    "with_headers",
]
