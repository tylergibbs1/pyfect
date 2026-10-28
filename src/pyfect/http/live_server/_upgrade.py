"""Upgrading a connection to another protocol (RFC 9110 §7.8): the
handler's ``request.upgrade`` answers ``101 Switching Protocols`` once it
takes the socket's reader, after the request body has ended (its unread
rest discarded, up to ``MaxBodySize``), and the socket reads the bytes the
client sent after the request first."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Never

from pyfect._core import Effect
from pyfect.effect import fail, succeed, suspend, sync, void
from pyfect.http.headers import Headers
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.live_server._exchange import (
    MAX_DRAIN_BYTES,
    Exchange,
    InvalidResponse,
    encode_fields,
)
from pyfect.http.server_error import HttpServerError, request_parse_error
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import empty
from pyfect.scope import Scope
from pyfect.socket._errors import CloseEvent, SocketError, upgrade_error
from pyfect.socket._socket import Chunk, Reader, SocketService, Writer, encode_chunk
from pyfect.socket._socket import make as make_socket

_RESERVED = frozenset({"connection", "upgrade", "content-length", "transfer-encoding"})
_SWITCHED = empty(status=101)


def _head(protocol: str, headers: Headers) -> bytes:
    fields = [("Connection", "Upgrade"), ("Upgrade", protocol), *headers.items()]
    return encode_fields("HTTP/1.1 101 Switching Protocols", fields)


def upgrade(
    exchange: Exchange, request: ServerRequest, headers: Headers
) -> Effect[SocketService, HttpServerError]:
    """The raw connection of an ``Upgrade`` request."""
    protocol = exchange.head.upgrade
    if protocol is None:
        return fail(request_parse_error(request, "Not an upgradeable ServerRequest"))
    reserved = sorted(_RESERVED.intersection(headers))
    if reserved:
        return fail(request_parse_error(request, f"Reserved upgrade header: {reserved[0]}"))
    try:
        head = _head(protocol, headers)
    except InvalidResponse as cause:
        return fail(request_parse_error(request, str(cause), cause))
    conn = exchange.conn

    def switch() -> Effect[None, SocketError]:
        if exchange.upgraded is not None:
            return void
        if exchange.headers_sent:
            return fail(upgrade_error(RuntimeError("the response was already sent")))
        exchange.headers_sent = True
        exchange.upgraded = _SWITCHED
        exchange.close_after = True
        return conn.write((head,))

    def drained(ok: bool) -> Effect[None, SocketError]:
        if not ok:
            return fail(upgrade_error(RuntimeError("the request body is too large")))
        return suspend(switch)

    def opened(_: None) -> Reader:
        leftover = exchange.take_pending()
        first: list[bytes] = [leftover] if leftover else []

        def pull() -> Effect[tuple[bytes, ...], SocketError]:
            return succeed((first.pop(),)) if first else conn.pull()

        return Reader(suspend(pull))

    def reader(limit: int | None) -> Effect[Reader, SocketError]:
        maximum = MAX_DRAIN_BYTES if limit is None else limit
        return exchange.body.drain(maximum).flat_map(drained).map(opened)

    def write(chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        if isinstance(chunk, CloseEvent):
            return sync(lambda: conn.close(graceful=chunk.code <= 1000))
        return conn.write((encode_chunk(chunk),))

    def write_all(chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        return conn.write(tuple(encode_chunk(chunk) for chunk in chunks))

    opened_reader: Effect[Reader, SocketError, Scope] = MaxBodySize().flat_map(reader)
    writer: Effect[Writer, Never, Scope] = succeed(Writer(write, write_all))
    return succeed(make_socket(opened_reader, writer))
