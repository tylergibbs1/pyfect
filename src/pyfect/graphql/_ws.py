"""GraphQL over graphql-transport-ws (Effect's
``GraphQLProtocol.makeWebSocket``).

One WebSocket is shared by every operation. It opens on the first
operation, sends ``connection_init`` (with ``connection_params``) and waits
up to ``connection_ack_timeout`` for ``connection_ack``; it pings every
``keep_alive`` and is lost when a ping goes unanswered. It closes
``idle_timeout`` after the last operation ends. A lost connection fails
the operations on it; the next operation opens a new one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Never

from pyfect import effect as fx
from pyfect import stream
from pyfect._all import all as fx_all
from pyfect._concurrency import for_each
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.cause import fail as cause_fail
from pyfect.clock import sleep
from pyfect.deferred import Deferred
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import Effect
from pyfect.exit import Success
from pyfect.exit import fail as exit_fail
from pyfect.graphql._types import Answer, GraphQLProtocolService, GraphQLRequest, request_body
from pyfect.graphql._ws_messages import Ack, Complete, Error, Invalid, Next, Ping, parse
from pyfect.graphql.client_error import TransportError
from pyfect.http import headers as _headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.queue import Done, Queue
from pyfect.result import Ok
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in, scoped
from pyfect.socket import CloseEvent, SocketCloseError, SocketError, SocketService
from pyfect.socket._socket import Chunk, Writer
from pyfect.socket._web_socket import WebSocketConstructor, make_web_socket
from pyfect.stream import Stream


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSocketOptions[R = Never]:
    """A graphql-transport-ws endpoint: its ``url`` and handshake
    ``headers``; ``connection_params`` (run once per connection, needing
    ``R``) is the ``connection_init`` payload. ``connection_ack_timeout``
    (10s), ``keep_alive`` (10s; ``False`` for no pings) and
    ``idle_timeout`` (0: close as soon as the last operation ends)."""

    url: str
    headers: HeadersInput | None = None
    connection_params: Effect[Mapping[str, object] | None, object, R] | None = None
    connection_ack_timeout: Duration | None = None
    keep_alive: Duration | Literal[False] | None = None
    idle_timeout: Duration | None = None


@dataclass(frozen=True, slots=True)
class _Timing:
    """``WebSocketOptions``' durations, parsed once."""

    ack_timeout: Seconds
    keep_alive: Seconds | None
    idle_timeout: Seconds


def _timing(options: WebSocketOptions[Any]) -> _Timing:
    ack = options.connection_ack_timeout
    keep_alive = options.keep_alive
    idle = options.idle_timeout
    return _Timing(
        ack_timeout=to_seconds(10 if ack is None else ack),
        keep_alive=None
        if keep_alive is False
        else to_seconds(10 if keep_alive is None else keep_alive),
        idle_timeout=to_seconds(0 if idle is None else idle),
    )


class _Connection:
    """One WebSocket connection. ``error`` is set once it is lost, and the
    operations attached to it fail with it."""

    __slots__ = ("ack", "error", "fiber", "received_frame")

    def __init__(self) -> None:
        self.ack: Deferred[None, TransportError] = Deferred()
        self.error: TransportError | None = None
        self.received_frame = True
        self.fiber: Fiber[None, Never] | None = None


@dataclass(frozen=True, slots=True)
class _Operation:
    queue: Queue[Answer, TransportError | Done]
    connection: _Connection


def _error_message(cause: object) -> str:
    message = getattr(cause, "message", None)
    return message if isinstance(message, str) else str(cause)


def _exception(cause: object) -> BaseException | None:
    return cause if isinstance(cause, BaseException) else None


def _error_of(error: object) -> TransportError:
    if isinstance(error, TransportError):
        return error
    if isinstance(error, SocketError) and isinstance(error.reason, SocketCloseError):
        return TransportError(
            description=f"The graphql-ws connection closed with {error.reason.message}",
            close_code=error.reason.code,
            cause=error,
        )
    return TransportError(
        description=f"The graphql-ws connection failed: {_error_message(error)}",
        cause=_exception(error),
    )


def _connection_error(cause: Cause[object]) -> TransportError:
    found = cause.find_error()
    if not isinstance(found, Ok):
        return TransportError(description="The graphql-ws connection was closed")
    return _error_of(found.value)


def _encode(message: Mapping[str, object]) -> str:
    # Unset fields are left out, as JSON.stringify drops undefined.
    return json.dumps({key: value for key, value in message.items() if value is not None})


def _no_ack() -> Effect[Never, TransportError]:
    return fx.fail(TransportError(description="The graphql-ws server did not send connection_ack"))


class _Transport:
    """The shared connection and the operations on it."""

    def __init__(
        self,
        socket: SocketService,
        writer: Writer,
        scope: CloseableScope,
        connection_params: Effect[Mapping[str, object] | None, TransportError],
        timing: _Timing,
    ) -> None:
        self.socket = socket
        self.writer = writer
        self.scope = scope
        self.connection_params = connection_params
        self.timing = timing
        self.operations: dict[str, _Operation] = {}
        self.connection: _Connection | None = None
        self.next_id = 0
        self.active = 0
        self.idle_generation = 0

    def send(self, message: Mapping[str, object]) -> Effect[None, TransportError]:
        return self.writer.write(_encode(message)).map_error(_error_of)

    def lose(self, conn: _Connection, error: TransportError) -> None:
        if conn.error is not None:
            return
        conn.error = error
        if self.connection is conn:
            self.connection = None
        conn.ack.done_unsafe(exit_fail(error))
        for id, operation in list(self.operations.items()):
            if operation.connection is conn:
                del self.operations[id]
                operation.queue.fail_cause_unsafe(cause_fail(error))

    def invalid(self, message: Invalid) -> Effect[Never, TransportError]:
        # An invalid server message closes the connection with 4400, which
        # is fatal for every operation on it.
        error = TransportError(
            description=f"Invalid graphql-ws message: {message.reason}",
            close_code=4400,
            cause=message.cause,
        )
        closing = self.writer.write(CloseEvent(4400, "Invalid message")).ignore()
        return closing.flat_map(lambda _: fx.fail(error))

    def handle(self, conn: _Connection, frame: Chunk) -> Effect[None, TransportError]:
        # Any frame answers a keep-alive ping; an invalid one drops the
        # connection anyway.
        conn.received_frame = True
        message = parse(frame)
        match message:
            case Invalid():
                return self.invalid(message)
            case Ack():
                conn.ack.done_unsafe(Success(None))
                return fx.void
            case Ping():
                return self.send({"type": "pong"})
            case Next() | Error() | Complete():
                self.route(conn, message)
                return fx.void
            case _:
                return fx.void

    def route(self, conn: _Connection, message: Next | Error | Complete) -> None:
        operation = self.operations.get(message.id)
        # Unknown ids, including operations this client already completed,
        # are dropped.
        if operation is None or operation.connection is not conn:
            return
        if isinstance(message, Next):
            operation.queue.offer_unsafe(Answer(body=message.payload))
            return
        del self.operations[message.id]
        if isinstance(message, Error):
            # The server rejected the operation; the client fails it with a
            # ResponseError.
            operation.queue.offer_unsafe(Answer(body={"errors": message.payload}))
        operation.queue.fail_cause_unsafe(cause_fail(Done()))

    def pinger(self, conn: _Connection) -> Effect[Never, TransportError]:
        interval = self.timing.keep_alive
        if interval is None:
            return fx.never

        def ping() -> Effect[None, TransportError]:
            if not conn.received_frame:
                return fx.fail(
                    TransportError(
                        description="The graphql-ws server did not answer the keep-alive ping"
                    )
                )
            conn.received_frame = False
            return self.send({"type": "ping"})

        return sleep(interval).flat_map(lambda _: fx.suspend(ping)).forever()

    def run(self, conn: _Connection) -> Effect[None]:
        def connected():
            reader = yield from self.socket.reader
            init = self.connection_params.flat_map(
                lambda payload: self.send({"type": "connection_init", "payload": payload})
            )
            read: Effect[Never, TransportError | SocketError] = reader.pull.flat_map(
                lambda frames: for_each(frames, lambda frame: self.handle(conn, frame)).as_void()
            ).forever()
            acknowledged = conn.ack.wait().timeout_or_else(self.timing.ack_timeout, _no_ack)
            # Reading starts with ``connection_params``, so a close while it
            # runs still fails the waiting operations. The ack timeout starts
            # once ``connection_init`` is sent.
            ready: Effect[Never, TransportError] = init.flat_map(lambda _: acknowledged).flat_map(
                lambda _: self.pinger(conn)
            )
            yield from fx_all(read, ready, concurrency=2, discard=True)

        # Runs before the socket closes, so no write waits on a dead socket.
        body: Effect[None, Any, Scope] = fx.gen(connected).on_error(
            lambda cause: fx.sync(lambda: self.lose(conn, _connection_error(cause)))
        )
        return scoped(body).ignore()

    def close(self, conn: _Connection) -> Effect[None]:
        self.lose(conn, TransportError(description="The graphql-ws connection was closed"))
        return fx.void if conn.fiber is None else conn.fiber.interrupt()

    def acquire_connection(self) -> Effect[_Connection]:
        if self.connection is not None:
            return fx.succeed(self.connection)
        conn = _Connection()
        self.connection = conn

        def started(fiber: Fiber[None, Never]) -> _Connection:
            conn.fiber = fiber
            return conn

        return fork_in(self.run(conn), self.scope).map(started)

    def register(self) -> Effect[tuple[str, _Connection], TransportError]:
        # A connection forked into a closed scope is interrupted before it
        # starts, so new operations fail instead of waiting for an ack.
        if self.scope.is_closed:
            return fx.fail(
                TransportError(description="The graphql-ws transport's scope is closed", fatal=True)
            )
        self.active += 1
        self.idle_generation += 1

        def numbered(conn: _Connection) -> tuple[str, _Connection]:
            self.next_id += 1
            return str(self.next_id), conn

        return self.acquire_connection().map(numbered)

    def close_if_idle(self) -> Effect[None]:
        self.active -= 1
        conn = self.connection
        if self.active > 0 or conn is None:
            return fx.void
        if self.timing.idle_timeout == 0:
            return self.close(conn)
        self.idle_generation += 1
        generation = self.idle_generation

        def close_if_still_idle() -> Effect[None]:
            if generation == self.idle_generation and self.connection is conn:
                return self.close(conn)
            return fx.void

        later = fx.suspend(close_if_still_idle).delay(self.timing.idle_timeout)
        return fork_in(later, self.scope).as_void()

    def release(self, id: str, conn: _Connection) -> Effect[None]:
        def start() -> Effect[None]:
            # Only a subscribed operation the server has not completed is
            # still in ``operations``.
            subscribed = self.operations.pop(id, None) is not None
            completed: Effect[None] = (
                self.send({"id": id, "type": "complete"}).ignore()
                if subscribed and conn.error is None
                else fx.void
            )
            return completed.flat_map(lambda _: self.close_if_idle())

        return fx.suspend(start)

    def subscribe(self, request: GraphQLRequest) -> Stream[Answer, TransportError]:
        def subscribed():
            id, conn = yield from acquire_release(
                fx.suspend(self.register), lambda pair, _exit: self.release(*pair)
            )
            yield from conn.ack.wait()
            if conn.error is not None:
                return (yield from fx.fail(conn.error))
            queue = yield from Queue[Answer, TransportError | Done].unbounded()
            self.operations[id] = _Operation(queue, conn)
            # Per-call ``request.headers`` and ``request.url_params`` are
            # ignored: graphql-ws has no per-operation headers or URL.
            yield from self.send({"id": id, "type": "subscribe", "payload": request_body(request)})
            return stream.from_queue(queue)

        answers: Effect[Stream[Answer, TransportError], TransportError, Scope] = fx.gen(subscribed)
        return stream.unwrap(answers)

    def execute(self, request: GraphQLRequest) -> Effect[Answer, TransportError]:
        def first(found: Any) -> Effect[Answer, TransportError]:
            if found is None:
                return fx.fail(
                    TransportError(
                        description="The graphql-ws operation completed without a result"
                    )
                )
            return fx.succeed(found.value)

        return self.subscribe(request).run_head().flat_map(first)


def make_web_socket_protocol[R = Never](
    options: WebSocketOptions[R],
) -> Effect[GraphQLProtocolService, Never, WebSocketConstructor | Scope | R]:
    """A transport running every operation over one shared
    graphql-transport-ws connection (see ``WebSocketOptions``). The
    connection lives in the current scope; an operation started after it
    closed fails with a fatal ``TransportError``."""
    timing = _timing(options)
    handshake_headers = None if options.headers is None else _headers.from_input(options.headers)

    def connection_params(context: Any) -> Effect[Mapping[str, object] | None, TransportError]:
        params = options.connection_params
        if params is None:
            return fx.succeed(None)
        return params.pipe(fx.provide_context(context)).map_error(
            lambda cause: TransportError(
                description=f"graphql-ws connectionParams failed: {_error_message(cause)}",
                cause=_exception(cause),
            )
        )

    def build():
        socket = yield from make_web_socket(
            options.url, protocols="graphql-transport-ws", headers=handshake_headers
        )
        writer: Writer = yield from socket.writer
        scope: CloseableScope = yield from Scope()
        context = yield from fx.context()
        transport = _Transport(socket, writer, scope, connection_params(context), timing)
        return GraphQLProtocolService(execute=transport.execute, subscribe=transport.subscribe)

    built: Effect[GraphQLProtocolService, Never, Any] = fx.gen(build)
    return built
