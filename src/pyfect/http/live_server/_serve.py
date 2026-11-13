"""Serving one connection: read a head, hand the request to the app, write
its response, and keep the connection for the next request unless it must
close (a ``connection: close``, a body too long to drain, a broken
response, a shutdown)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from typing import Any

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.duration import Duration, millis
from pyfect.effect import gen, succeed, sync, void
from pyfect.http._authority import LOCALHOST, absolute_url
from pyfect.http.headers import Headers
from pyfect.http.live_server._exchange import MAX_DRAIN_BYTES, Exchange
from pyfect.http.live_server._head import HeadError, RequestHead, parse_head
from pyfect.http.live_server._inbound import BareLineFeed, HeadTooLarge, Inbound
from pyfect.http.live_server._listener import ConnectionState, Listener
from pyfect.http.live_server._timers import timeout_option
from pyfect.http.live_server._upgrade import upgrade
from pyfect.http.live_server._ws_deflate import WebSocketConfig
from pyfect.http.server_error import CLIENT_ABORT_ANNOTATION
from pyfect.http.server_request import RequestProtocol, ServerRequest, SourceRequest
from pyfect.option import Option
from pyfect.socket._connection import Connection
from pyfect.socket._errors import SocketError

MAX_HEAD_SIZE = 16 * 1024
"""Node's ``maxHeaderSize``: a longer head is answered with 431."""

CLOSE_GRACE_PERIOD = millis(500)
"""How long a closing connection waits for the client to stop sending
before it is torn down (so the response is not lost to a reset)."""

type Handle = Callable[[SourceRequest, Exchange], Effect[None]]


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Node's ``keepAliveTimeout`` (an idle connection between requests is
    closed), ``headersTimeout`` (a head must arrive within it once it is
    awaited, or started after a keep-alive wait; a started one is answered
    with 408) and ``requestTimeout`` (the body must have arrived within it
    of the head arriving, or its read fails, the response drain
    included, and the connection closes)."""

    keep_alive: Duration
    headers: Duration
    request: Duration


def _reject(conn: Connection, status: int) -> Effect[None]:
    head = (
        f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\n"
        "connection: close\r\ncontent-length: 0\r\n\r\n"
    ).encode("ascii")

    def ignore(_: SocketError) -> Effect[None]:
        return void

    return conn.write((head,)).catch_all(ignore).flat_map(lambda _: _close(conn))


def _close(conn: Connection) -> Effect[None]:
    """End the response side, read on for the grace period, then close."""

    def start() -> None:
        conn.end_writing()
        conn.discard_input()

    waited = timeout_option(conn.closed(), CLOSE_GRACE_PERIOD)
    return (
        sync(start)
        .flat_map(lambda _: waited)
        .flat_map(lambda _: sync(lambda: conn.close(graceful=False)))
    )


def _peer_address(conn: Connection) -> str | None:
    name: Any = conn.peer_name()
    if isinstance(name, tuple) and name:
        return str(name[0])  # pyright: ignore[reportUnknownArgumentType]
    return None


def _request(
    exchange: Exchange,
    protocol: RequestProtocol,
    remote_address: str | None,
    websocket: WebSocketConfig,
) -> SourceRequest:
    head = exchange.head
    url = head.target
    body = exchange.body
    return SourceRequest(
        head.method,
        url if url == "*" else absolute_url(protocol, head.authority or LOCALHOST, url),
        head.headers,
        None if body.complete else body.stream,
        source=exchange,
        remote_address=remote_address,
        protocol=protocol,
        upgrade=partial(_upgrade, exchange, websocket) if head.upgrade is not None else None,
    )


def _upgrade(
    exchange: Exchange, websocket: WebSocketConfig, request: ServerRequest, headers: Headers
) -> Effect[Any, Any]:
    return upgrade(exchange, request, headers, websocket)


def _run_request(exchange: Exchange, handled: Effect[None]) -> Effect[None]:
    """Run the request on a fiber interrupted as a client abort if the
    client goes first: once it stops sending (Node's servers do not allow
    half-open connections), or for an upgrade once the connection is
    lost."""
    conn = exchange.conn
    gone = conn.closed() if exchange.head.upgrade is not None else conn.read_ended()

    def body():
        fiber: Fiber[None, Any] = yield from handled.fork()

        def abort(_: None) -> Effect[None]:
            if exchange.finished:
                return void
            exchange.close_after = True
            exchange.aborted = True
            return sync(lambda: fiber.interrupt_as_unsafe(None, CLIENT_ABORT_ANNOTATION))

        watcher = yield from gone.flat_map(abort).fork()
        yield from fiber.await_exit()
        yield from watcher.interrupt()

    return gen(body)


def serve_connection(
    listener: Listener,
    state: ConnectionState,
    handle: Handle,
    protocol: RequestProtocol,
    timeouts: Timeouts,
    *,
    websocket: WebSocketConfig,
) -> Effect[None]:
    conn = state.conn
    inbound = Inbound(conn)
    remote_address = _peer_address(conn)

    def head_failed(
        error: SocketError | HeadTooLarge | BareLineFeed,
    ) -> Effect[bytes | int | None]:
        if isinstance(error, HeadTooLarge):
            return succeed(431)
        return succeed(400 if isinstance(error, BareLineFeed) else None)

    def within_headers_timeout(found: Option[bytes | int | None]) -> bytes | int | None:
        if found is None:
            return 408 if inbound.has_pending else None
        return found.value

    def next_head(first: bool) -> Effect[bytes | int | None]:
        """The next head, or the status to reject it with; ``None`` to
        close quietly."""
        head = timeout_option(
            inbound.read_head(MAX_HEAD_SIZE).catch_all(head_failed), timeouts.headers
        ).map(within_headers_timeout)
        if first:
            return head

        def started(_: SocketError) -> Effect[None]:
            return void  # the head read sees the failure

        waited = timeout_option(inbound.wait_data().catch_all(started), timeouts.keep_alive)
        return waited.flat_map(lambda found: succeed(None) if found is None else head)

    def parsed(data: bytes | int | None) -> RequestHead | int | None:
        if not isinstance(data, bytes):
            return data
        try:
            return parse_head(data)
        except HeadError as error:
            return error.status

    def after(exchange: Exchange) -> Effect[bool]:
        """Whether the connection serves another request."""
        if exchange.upgraded is not None or not exchange.finished:
            return succeed(False)
        if exchange.close_after:
            return _close(conn).as_(False)
        return exchange.body.drain(MAX_DRAIN_BYTES).flat_map(
            lambda drained: succeed(True) if drained else _close(conn).as_(False)
        )

    def loop():
        first = True
        # As Node's server, a connection busy when shutdown starts goes on
        # serving keep-alive requests until it is idle for the keep-alive
        # timeout (or the graceful shutdown timeout ends).
        while True:
            state.waiting = True
            state.exchange = None
            inbound.deadline = None
            data = yield from next_head(first)
            inbound.deadline = time.monotonic() + timeouts.request.to_seconds()
            first = False
            state.waiting = False
            head = parsed(data)
            if head is None:
                return
            if isinstance(head, int):
                yield from _reject(conn, head)
                return
            exchange = Exchange(conn, inbound, head, int(timeouts.keep_alive.to_seconds()))
            state.exchange = exchange
            request = _request(exchange, protocol, remote_address, websocket)
            yield from _run_request(exchange, handle(request, exchange))
            if not (yield from after(exchange)):
                return

    return gen(loop).ensuring(sync(lambda: listener.done(state)))
