"""The RPC server without serialization (Effect's
``RpcServer.makeNoSerialization``): decoded requests in, decoded responses
out through ``on_from_server``."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Never, cast

from pyfect import cause as Cause
from pyfect import exit as Exit
from pyfect._core import Effect, _AfterStarted, _WithFiber
from pyfect._fiber import Fiber
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.effect import (
    context,
    die,
    fail_cause,
    from_exit,
    gen,
    interrupt,
    provide_context,
    succeed,
    suspend,
)
from pyfect.error_reporter import report_unsafe
from pyfect.errors import Done
from pyfect.latch import Latch
from pyfect.queue import Dequeue
from pyfect.rpc._rpc import (
    AnyRpc,
    HandlerEntry,
    RpcRequest,
    ServerClient,
    handler_tag,
    wrap_options,
)
from pyfect.rpc._rpc import unwrap as unwrap_handler
from pyfect.rpc.group import HandlersFor, RpcGroup
from pyfect.rpc.message import (
    Ack,
    ClientEnd,
    Eof,
    FromClient,
    FromServer,
    Interrupt,
    Request,
    RequestId,
    ResponseChunk,
    ResponseDefect,
    ResponseExit,
)
from pyfect.rpc.middleware import MiddlewareOptions
from pyfect.rpc.schema import ClientAbort
from pyfect.schema import DecodedDefect
from pyfect.scope import CloseableScope, Scope, scoped
from pyfect.semaphore import Semaphore
from pyfect.stream import Stream
from pyfect.tracer import AnySpan, ExternalSpan, ParentSpan, SpanLink, SpanOptions

type Concurrency = int | Literal["unbounded"]
type OnFromServer = Callable[[FromServer], Effect[None]]
type OnRequest = Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]

_VOID: Effect[None] = succeed(None)


def unknown_tag(tag: object) -> DecodedDefect:
    """The defect of a request for no RPC (Effect dies with this text)."""
    return DecodedDefect(f"Unknown request tag: {tag}")


@dataclass(frozen=True, slots=True)
class ServerOptions:
    """How a server runs its handlers: in a span named
    the tag, or ``<span_prefix>.<tag>`` (no span with ``disable_tracing``), at most
    ``concurrency`` at once, a defect ending every request of the client
    unless ``disable_fatal_defects``, and waiting for the client's ``Ack``
    after each stream chunk unless ``disable_client_acks``."""

    disable_tracing: bool = False
    disable_span_propagation: bool = False
    span_prefix: str | None = None
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    concurrency: Concurrency = "unbounded"
    disable_fatal_defects: bool = False
    disable_client_acks: bool = False


@dataclass(slots=True, eq=False)
class _Client:
    id: int
    server_client: ServerClient
    fibers: dict[RequestId, Fiber[Any, Any]] = field(
        default_factory=dict[RequestId, Fiber[Any, Any]]
    )
    latches: dict[RequestId, Latch] = field(default_factory=dict[RequestId, Latch])
    ended: bool = False


class RpcServer:
    """A running server: ``write`` hands it a client's message,
    ``disconnect`` drops a client and interrupts its requests."""

    __slots__ = (
        "_clients",
        "_group",
        "_is_shutdown",
        "_on_from_server",
        "_options",
        "_semaphore",
        "_services",
        "_shutdown",
        "_track",
    )

    def __init__(
        self,
        group: type[RpcGroup],
        *,
        on_from_server: OnFromServer,
        options: ServerOptions,
        services: Context[Any],
        track: CloseableScope,
        semaphore: Semaphore | None,
    ) -> None:
        self._group = group
        self._on_from_server = on_from_server
        self._options = options
        self._services = services
        self._track = track
        self._semaphore = semaphore
        self._clients: dict[int, _Client] = {}
        self._is_shutdown = False
        self._shutdown = Latch(False)

    # --- lifecycle -------------------------------------------------------------------

    def _close(self) -> Effect[None]:
        def body(parent: Fiber[Any, Any]) -> Effect[None]:
            self._is_shutdown = True
            for client in list(self._clients.values()):
                client.ended = True
                if not client.fibers:
                    self._run(self._end_client(client), self._services)
                    continue
                for fiber in list(client.fibers.values()):
                    fiber.interrupt_as_unsafe(parent.id)
            return _VOID if not self._clients else self._shutdown.wait()

        return _WithFiber(body)

    def _run(self, eff: Effect[Any, Any, Any], ctx: Context[Any]) -> Fiber[Any, Any]:
        """Fork ``eff`` with ``ctx`` into the tracking scope, now."""
        fiber = Fiber.get_current()
        if fiber is None:
            raise RuntimeError("an RPC server runs on a fiber")
        child = fiber._fork(eff.pipe(provide_context(ctx)), daemon=True)
        child.run_in(self._track)
        return child

    def disconnect(self, client_id: int) -> Effect[None]:
        def body(parent: Fiber[Any, Any]) -> Effect[None]:
            client = self._clients.pop(client_id, None)
            if client is not None:
                for fiber in list(client.fibers.values()):
                    fiber.interrupt_as_unsafe(parent.id)
            return _VOID

        return _WithFiber(body)

    def _end_client(self, client: _Client) -> Effect[None]:
        def body() -> Effect[None]:
            self._clients.pop(client.id, None)
            write = self._on_from_server(ClientEnd(client.id))
            if self._is_shutdown and not self._clients:
                return write.flat_map(lambda _: self._shutdown.open().as_void())
            return write

        return suspend(body)

    def _send_defect(self, client: _Client, defect: BaseException) -> Effect[None]:
        def body() -> Effect[None]:
            should_end = client.ended and not client.fibers
            write = self._on_from_server(ResponseDefect(client.id, defect))
            return write.flat_map(lambda _: self._end_client(client)) if should_end else write

        return suspend(body)

    # --- messages from a client ---------------------------------------------------------

    def write(
        self, client_id: int, message: FromClient, on_request: OnRequest | None = None
    ) -> Effect[None]:
        """Hand the server a message of the client ``client_id``. Fails
        (interrupted) when the server is shut down, or the client ended and
        the message is not for one of its running requests."""

        def body(request_fiber: Fiber[Any, Any]) -> Effect[None]:
            if self._is_shutdown:
                return interrupt()
            client = self._clients.get(client_id)
            if client is None:
                client = _Client(client_id, ServerClient(client_id))
                self._clients[client_id] = client
            elif client.ended and not (
                isinstance(message, Ack | Interrupt) and message.request_id in client.fibers
            ):
                return interrupt()
            return self._dispatch(request_fiber, client, message, on_request)

        return _WithFiber(body).catch_defect(lambda defect: self._defect_of(client_id, defect))

    def _dispatch(
        self,
        request_fiber: Fiber[Any, Any],
        client: _Client,
        message: FromClient,
        on_request: OnRequest | None,
    ) -> Effect[None]:
        match message:
            case Request():
                return self._handle_request(request_fiber, client, message, on_request)
            case Ack(request_id=request_id):
                latch = client.latches.get(request_id)
                return _VOID if latch is None else latch.open().as_void()
            case Interrupt(request_id=request_id):
                fiber = client.fibers.get(request_id)
                if fiber is None:
                    return self._on_from_server(
                        ResponseExit(client.id, request_id, Exit.interrupt())
                    )
                fiber.interrupt_as_unsafe(request_fiber.id, ClientAbort.annotation)
                return _VOID
            case Eof():
                client.ended = True
                return _VOID if client.fibers else self._end_client(client)

    def _defect_of(self, client_id: int, defect: BaseException) -> Effect[None]:
        client = self._clients.get(client_id)
        return _VOID if client is None else self._send_defect(client, defect)

    def _handle_request(
        self,
        request_fiber: Fiber[Any, Any],
        client: _Client,
        request: Request,
        on_request: OnRequest | None,
    ) -> Effect[None]:
        if request.id in client.fibers:
            return interrupt()
        rpc = self._group.rpcs.get(request.tag)
        found = None if rpc is None else self._services.get_option(handler_tag(rpc))
        if rpc is None or found is None:
            return self._unknown_request(client, request)
        entry: HandlerEntry = found.value
        metadata = RpcRequest(
            request.payload, client.server_client, request.id, request.headers, rpc
        )
        result = _run_handler(entry, metadata)
        options = wrap_options(result)
        run = _RequestRun(self, client, request, CloseableScope())
        effect = self._handler_effect(entry, rpc, run, unwrap_handler(result)).on_exit(run.on_exit)
        if on_request is not None:
            effect = on_request(effect)
        if not self._options.disable_tracing:
            effect = self._traced(effect, request, request_fiber.get_ref(ParentSpan))
        if not (options is not None and options.fork) and self._semaphore is not None:
            effect = self._semaphore.with_permits(effect)
        run.context = entry.context.merge(request_fiber._context).add(Scope, run.scope)
        # Started at once, as Effect's ``runForkWith``: an ``Interrupt``
        # written next finds the handler's ``on_interrupt`` in place.
        fiber = request_fiber._fork(
            effect.pipe(provide_context(run.context)),
            daemon=True,
            start_immediately=True,
            uninterruptible=options is not None and options.uninterruptible,
        )
        run.watch(fiber)
        return _AfterStarted(None)

    def _unknown_request(self, client: _Client, request: Request) -> Effect[None]:
        write = self._on_from_server(
            ResponseExit(client.id, request.id, Exit.die(unknown_tag(request.tag)))
        ).catch_defect(lambda defect: self._send_defect(client, defect))
        if not client.ended or client.fibers:
            return write
        return write.ensuring(self._end_client(client))

    def _handler_effect(
        self, entry: HandlerEntry, rpc: AnyRpc, run: _RequestRun, result: Any
    ) -> Effect[Any, Any, Any]:
        """The handler's effect with the RPC's middleware around it; a
        stream is run, writing its chunks."""
        client, request = run.client, run.request
        handler: Effect[Any, Any, Any] = (
            self._stream_effect(client, request, result, run.write_failures.append)
            if rpc.is_stream
            else result
        )
        if not rpc.middlewares:
            return handler
        middleware_options = MiddlewareOptions(
            client.server_client, request.id, rpc, request.payload, request.headers
        )
        wrapped = _apply_middleware(self._services, entry, handler, middleware_options)
        if not rpc.is_stream:
            return wrapped
        # Middleware may rewrite or swallow a chunk write failure: restore it.
        # A stream ends with no value (Effect's ``Schema.Void``), whatever
        # value the middleware passes on.
        failures = run.write_failures
        return wrapped.exit().flat_map(
            lambda exit: fail_cause(failures[0]) if failures else from_exit(exit).as_void()
        )

    def _traced(
        self, effect: Effect[Any, Any, Any], request: Request, writer_span: AnySpan | None
    ) -> Effect[Any, Any, Any]:
        """``effect`` in the request's server span: a child of the client's
        span, linked to the span the request was written in."""
        options = self._options
        prefix = options.span_prefix
        name = request.tag if prefix is None else f"{prefix}.{request.tag}"
        attributes: dict[str, object] = {"rpc.system.name": "effect_rpc", "rpc.method": request.tag}
        attributes.update(options.span_attributes)
        span_options: SpanOptions = {"kind": "server", "attributes": attributes}
        if not options.disable_span_propagation:
            if request.span_id and request.trace_id:
                span_options["parent"] = ExternalSpan(
                    request.span_id, request.trace_id, request.sampled is not False
                )
            if writer_span is not None:
                span_options["links"] = [SpanLink(writer_span)]
        return effect.with_span(name, capture_stack_trace=False, **span_options)

    def _stream_effect(
        self,
        client: _Client,
        request: Request,
        stream: object,
        on_write_failure: Callable[[Cause.Cause[Never]], None],
    ) -> Effect[None, Any, Any]:
        def write_chunk(values: tuple[Any, ...]) -> Effect[None]:
            def failed(cause: Cause.Cause[Never]) -> Effect[None]:
                if not cause.has_interrupts_only:
                    on_write_failure(cause)
                return _VOID

            return self._on_from_server(ResponseChunk(client.id, request.id, values)).on_error(
                failed
            )

        latch: Latch | None = None
        if not self._options.disable_client_acks:
            latch = client.latches.setdefault(request.id, Latch(False))

        def send(values: tuple[Any, ...]) -> Effect[None]:
            write = write_chunk(values)
            gate = latch
            if gate is None:
                return write
            gate.close_unsafe()
            return write.flat_map(lambda _: gate.wait())

        if isinstance(stream, Stream):
            items = cast("Stream[Any, Any, Any]", stream)
            return items.run_for_each_array(lambda values: send(tuple(values)))
        queue_effect = cast("Effect[Dequeue[Any, Any], Any, Any]", stream)

        @gen
        def drain():
            queue = yield from queue_effect
            while True:
                values = yield from queue.take_all()
                yield from send(tuple(values))

        return _scoped_drain(drain)


class _RequestRun:
    """One request's run: answers the client when it exits, and follows a
    handler that succeeded with a ``Deferred`` until it is done."""

    __slots__ = (
        "client",
        "context",
        "deferred",
        "request",
        "responded",
        "scope",
        "server",
        "write_failures",
    )

    def __init__(
        self, server: RpcServer, client: _Client, request: Request, scope: CloseableScope
    ) -> None:
        self.server = server
        self.client = client
        self.request = request
        self.scope = scope
        self.context: Context[Any] = Context.empty()
        self.responded = False
        self.deferred: Deferred[Any, Any] | None = None
        self.write_failures: list[Cause.Cause[Never]] = []

    def respond(self, exit: Exit.Exit[Any, Any]) -> Effect[None]:
        return self.server._on_from_server(ResponseExit(self.client.id, self.request.id, exit))

    def on_exit(self, exit: Exit.Exit[Any, Any]) -> Effect[None]:
        self.responded = True
        server = self.server
        write: Effect[None]
        if isinstance(exit, Exit.Success):
            value = exit.value
            if isinstance(value, Deferred):
                self.deferred = cast("Deferred[Any, Any]", value)
                write = _VOID
            else:
                write = self.respond(exit)
        elif self.write_failures:
            # The chunk writer already answered the client and reported it.
            return self.scope.close_unsafe(exit) or _VOID
        elif (
            not server._options.disable_fatal_defects
            and exit.cause.has_dies
            and not exit.cause.has_interrupts
        ):
            write = server._send_defect(self.client, exit.cause.squash())
        else:
            write = self.respond(exit)
        close = self.scope.close_unsafe(exit)
        if isinstance(exit, Exit.Failure):
            current = Fiber.get_current()
            if current is not None:
                report_unsafe(current, exit.cause)
        return write if close is None else write.ensuring(close)

    def watch(self, fiber: Fiber[Any, Any]) -> None:
        fiber.run_in(self.server._track)
        self.client.fibers[self.request.id] = fiber
        fiber.add_observer_unsafe(self._observe)

    def _observe(self, exit: Exit.Exit[Any, Any]) -> None:
        server, client = self.server, self.client
        deferred = self.deferred
        if deferred is not None:
            self.deferred = None
            waiting = server._run(deferred.wait().on_exit(self.respond), self.context)
            client.fibers[self.request.id] = waiting
            waiting.add_observer_unsafe(self._observe)
            return
        if not self.responded and isinstance(exit, Exit.Failure):
            server._run(self.respond(Exit.interrupt()), self.context)
        client.fibers.pop(self.request.id, None)
        client.latches.pop(self.request.id, None)
        if client.ended and not client.fibers:
            server._run(server._end_client(client), self.context)


def _scoped_drain(drain: Effect[Any, Any, Any]) -> Effect[None, Any, Any]:
    def done(cause: Cause.Cause[Any]) -> Effect[None, Any, Any]:
        found = cause.find_recoverable_error()
        if isinstance(found, Cause.Fail) and isinstance(found.error, Done):
            return _VOID
        return fail_cause(cause)

    return scoped(drain.catch_cause(done))


def _run_handler(entry: HandlerEntry, request: RpcRequest[Any]) -> Any:
    """A raise in the handler is a defect of the request."""
    try:
        return entry.handler(request)
    except KeyboardInterrupt:
        raise  # Ctrl-C: the loop interrupts the fiber (Fiber._raised)
    except BaseException as defect:
        return die(defect)


def _apply_middleware(
    services: Context[Any],
    entry: HandlerEntry,
    handler: Effect[Any, Any, Any],
    options: MiddlewareOptions,
) -> Effect[Any, Any, Any]:
    for middleware in options.rpc.middlewares:
        found = entry.context.get_option(middleware) or services.get_option(middleware)
        if found is None:
            return die(LookupError(f"no service for the middleware {middleware.key}"))
        handler = found.value(handler, options)
    return handler


def make_no_serialization[G: RpcGroup](
    group: type[G],
    on_from_server: OnFromServer,
    options: ServerOptions | None = None,
) -> Effect[RpcServer, Never, Scope | HandlersFor[G]]:
    """A server of ``group`` writing its responses with ``on_from_server``.
    It shuts down with the current scope: running requests are interrupted
    and it waits until each client is told it ended."""
    resolved = options or ServerOptions()

    @gen
    def make():
        services = yield from context()
        scope = yield from Scope()
        track = yield from scope.fork("parallel")
        semaphore = None
        if resolved.concurrency != "unbounded":
            semaphore = yield from Semaphore.make(resolved.concurrency)
        server = RpcServer(
            group,
            on_from_server=on_from_server,
            options=resolved,
            services=services,
            track=track,
            semaphore=semaphore,
        )
        yield from scope.add_finalizer(lambda _: server._close())
        return server

    return cast("Effect[RpcServer, Never, Scope | HandlersFor[G]]", make)


__all__ = [
    "Concurrency",
    "OnFromServer",
    "RpcServer",
    "ServerOptions",
    "make_no_serialization",
    "unknown_tag",
]
