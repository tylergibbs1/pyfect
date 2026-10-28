"""One request and its response on a connection: the ``100 Continue``,
the response head and its body framing (RFC 9112 §6.3), and whether the
connection stays open.

As Node's server: a response gets ``date`` and ``connection`` headers, a
stream without a length is chunked (closed-delimited for HTTP/1.0), a
response whose headers cannot be written becomes a 500, and a body that
fails once sent aborts the connection, so the client never sees it as
complete.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from pyfect._core import Effect
from pyfect.cause import Cause, UnhandledError, merge
from pyfect.cause import die as die_cause
from pyfect.effect import fail_cause, succeed, suspend, void
from pyfect.http.headers import format_http_date
from pyfect.http.live_server._body import BodyReader
from pyfect.http.live_server._head import Length, RequestHead
from pyfect.http.live_server._inbound import Inbound
from pyfect.http.server_error import HttpServerError, cause_response
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.wire import WireResponse, to_wire
from pyfect.socket._connection import Connection
from pyfect.socket._errors import SocketError
from pyfect.stream import Stream

MAX_DRAIN_BYTES = 256 * 1024
"""Unread request body discarded after the response to keep the
connection alive; past this it closes."""

_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_VALUE = re.compile(r"[\t\x20-\x7e\x80-\xff]*\Z")
_CONTINUE = b"HTTP/1.1 100 Continue\r\n\r\n"


class InvalidResponse(Exception):
    """A response the server cannot write (Node's ``writeHead`` throws)."""


def _reason(status: int, text: str) -> str:
    if text:
        return text
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "unknown"


def encode_fields(start_line: str, fields: Sequence[tuple[str, str]]) -> bytes:
    """A head: ``start_line`` and the fields, values as Latin-1."""
    lines = [start_line]
    for name, value in fields:
        if not _TOKEN.match(name):
            raise InvalidResponse(f'Header name must be a valid HTTP token ["{name}"]')
        if not _VALUE.match(value):
            raise InvalidResponse(f'Invalid character in header content ["{name}"]')
        lines.append(f"{name}: {value}")
    try:
        return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
    except UnicodeEncodeError as cause:
        raise InvalidResponse("Header content is not Latin-1") from cause


def _encode_head(status: int, text: str, headers: Sequence[tuple[str, str]]) -> bytes:
    """The response head; Node's server answers ``HTTP/1.1`` to every
    request version."""
    if not 200 <= status <= 599:
        raise InvalidResponse(f"Invalid final response status: {status}")
    reason = _reason(status, text)
    if not _VALUE.match(reason):
        raise InvalidResponse("Invalid character in statusMessage")
    return encode_fields(f"HTTP/1.1 {status} {reason}", headers)


def _without(headers: list[tuple[str, str]], *names: str) -> list[tuple[str, str]]:
    return [(name, value) for name, value in headers if name not in names]


def _chunk(data: bytes) -> bytes:
    return b"%x\r\n%s\r\n" % (len(data), data)


class Exchange:
    """The state the server and the request's readers share."""

    __slots__ = (
        "_inbound",
        "body",
        "close_after",
        "conn",
        "finished",
        "head",
        "headers_sent",
        "keep_alive_seconds",
        "pending_continue",
        "upgraded",
    )

    def __init__(
        self,
        conn: Connection,
        inbound: Inbound,
        head: RequestHead,
        keep_alive_seconds: int,
    ) -> None:
        self.conn = conn
        self._inbound = inbound
        self.head = head
        self.pending_continue = head.expect == "continue"
        self.body = BodyReader(inbound, head.framing, self.write_continue)
        self.headers_sent = False
        self.finished = False
        # An upgrade request's connection does not go back to HTTP.
        self.close_after = not head.keep_alive or head.upgrade is not None
        self.keep_alive_seconds = keep_alive_seconds
        self.upgraded: HttpServerResponse | None = None

    # --- writing ----------------------------------------------------------------

    def _write(self, *chunks: bytes) -> Effect[None]:
        def lost(_: SocketError) -> Effect[None]:
            self.close_after = True
            return void

        return self.conn.write(chunks).catch_all(lost)

    def write_continue(self) -> Effect[None]:
        """Ask the client for the body it holds back, once."""

        def step() -> Effect[None]:
            if not self.pending_continue or self.headers_sent:
                return void
            self.pending_continue = False
            return self._write(_CONTINUE)

        return suspend(step)

    def _closes_connection(self, streaming: bool) -> bool:
        """Decided when the head is written, while ``connection: close`` can
        still be sent: a held-back body, or a long unread one."""
        if self.close_after:
            return True
        if self.body.complete:
            return False
        if self.pending_continue:
            return True
        framing = self.head.framing
        return (
            not streaming
            and isinstance(framing, Length)
            and framing.size - self.body.bytes_read > MAX_DRAIN_BYTES
        )

    def _framed_headers(
        self, wire: WireResponse, without_body: bool
    ) -> tuple[list[tuple[str, str]], bool]:
        """The headers to write, and whether a streamed body is chunked."""
        headers = list(wire.headers)
        streaming = isinstance(wire.body, Stream)
        chunked = False
        no_body = without_body or omits_body_status(wire.status)
        if not no_body:
            headers = _without(headers, "transfer-encoding")
            has_length = any(name == "content-length" for name, _ in headers)
            if isinstance(wire.body, bytes) or wire.body is None:
                size = 0 if wire.body is None else len(wire.body)
                headers = [*_without(headers, "content-length"), ("content-length", str(size))]
            elif streaming and not has_length:
                if self.head.version >= (1, 1):
                    chunked = True
                    headers.append(("transfer-encoding", "chunked"))
                else:
                    self.close_after = True
        if self._closes_connection(streaming and not no_body):
            self.close_after = True
        headers = _without(headers, "connection", "keep-alive")
        if self.close_after:
            headers.append(("connection", "close"))
        else:
            keep_alive = f"timeout={self.keep_alive_seconds}"
            headers.extend((("connection", "keep-alive"), ("keep-alive", keep_alive)))
        if not any(name == "date" for name, _ in headers):
            headers.append(("date", format_http_date(datetime.now(UTC))))
        return headers, chunked

    def respond(
        self, request: ServerRequest, response: HttpServerResponse
    ) -> Effect[object, HttpServerError]:
        """Write ``response``; what middleware sees as sent (the ``101`` of
        an upgraded connection)."""

        def step() -> Effect[object, Any]:
            if self.upgraded is not None:
                return succeed(self.upgraded)
            if self.headers_sent:
                return void
            without_body = request.method == "HEAD"
            wire = to_wire(response, without_body=without_body)
            headers, chunked = self._framed_headers(wire, without_body)
            try:
                head = _encode_head(wire.status, wire.status_text, headers)
            except InvalidResponse as defect:
                return self._failed(response, die_cause(defect))
            self.headers_sent = True
            body = wire.body
            if body is None or without_body or omits_body_status(wire.status):
                return self._write(head).map(self._done)
            if isinstance(body, bytes):
                return self._write(head, body).map(self._done)
            return self._write(head).flat_map(lambda _: self._stream(response, body, chunked))

        return suspend(step)

    def _done(self, _: object = None) -> None:
        self.finished = True

    def _stream(
        self, response: HttpServerResponse, body: Stream[bytes, object], chunked: bool
    ) -> Effect[None, Any]:
        def write(chunks: tuple[bytes, ...]) -> Effect[None]:
            data = b"".join(chunks)
            if not data:
                return void
            return self._write(_chunk(data) if chunked else data)

        def end(_: object) -> Effect[None]:
            return (self._write(b"0\r\n\r\n") if chunked else void).map(self._done)

        written: Effect[None, Any] = body.run_for_each_array(write).interruptible()
        return written.match_cause_effect(
            on_success=end, on_failure=lambda cause: self._failed(response, cause)
        )

    def _failed(self, response: HttpServerResponse, cause: Cause[Any]) -> Effect[None, Any]:
        """A response that could not be written: a 500 (or the failure's
        response) before the head is sent; after it, the connection is
        aborted, so a cut-off body never looks complete."""
        if self.headers_sent:
            self.close_after = True
            self.conn.close(graceful=False)
            return fail_cause(merge(cause, die_cause(UnhandledError(response))))

        def write(pair: tuple[HttpServerResponse, Cause[Any]]) -> Effect[None, Any]:
            fallback, reported = pair
            status = fallback.status if 200 <= fallback.status <= 599 else 500
            self.headers_sent = True
            self.close_after = True
            head = _encode_head(
                status,
                "",
                [("content-length", "0"), ("connection", "close")],
            )
            return self._write(head).map(self._done).flat_map(lambda _: fail_cause(reported))

        return cause_response(cause).flat_map(write)

    def take_pending(self) -> bytes:
        return self._inbound.take_pending()


def omits_body_status(status: int) -> bool:
    return status in (204, 205, 304) or 100 <= status < 200
