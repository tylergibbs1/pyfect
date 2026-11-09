"""Request bodies read off the connection: ``Content-Length`` or chunked
framing (RFC 9112 §6, §7.1), shared by every reader of the request."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pyfect._core import Effect
from pyfect.effect import fail, succeed, suspend
from pyfect.errors import Done
from pyfect.http.live_server._head import Chunked, Framing, HeadError, parse_field_line
from pyfect.http.live_server._inbound import Inbound
from pyfect.socket._errors import SocketError
from pyfect.stream import Stream, from_pull

_READ_SIZE = 64 * 1024
_LINE_LIMIT = 4096
_TRAILERS_LIMIT = 16 * 1024
"""The most bytes of trailer lines, as the head's limit."""
_TCHAR = rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]"
_QUOTED = rb'"(?:[\t \x21\x23-\x5b\x5d-\x7e\x80-\xff]|\\[\t\x20-\x7e\x80-\xff])*"'
_CHUNK_SIZE = re.compile(
    rb"([0-9A-Fa-f]+)(?:;" + _TCHAR + rb"+(?:=(?:" + _TCHAR + rb"*|" + _QUOTED + rb"))?)*\Z"
)
"""A chunk size and its extensions as Node's ``llhttp`` reads them: RFC
9112's ``chunk-ext`` with no whitespace, a token name and an optional
token (possibly empty) or quoted-string value. Anything else, a control
character above all (a parser that ends a line at a bare CR would read
another message), fails the body."""
_MAX_CHUNK_SIZE = 2**64 - 1
"""``llhttp`` refuses a size that overflows 64 bits."""


class BodyError(Exception):
    """The body is malformed or ended early."""


type Pull = Effect[tuple[bytes, ...], BodyError | SocketError | Done]
type _State = Literal["length", "size", "data", "data-end", "trailers", "done"]


class BodyReader:
    """The request body. ``before_read`` runs before the first read (the
    ``100 Continue``); ``bytes_read`` counts body bytes."""

    __slots__ = (
        "_before_read",
        "_failed",
        "_inbound",
        "_left",
        "_state",
        "_trailer_bytes",
        "bytes_read",
        "started",
    )

    def __init__(
        self, inbound: Inbound, framing: Framing, before_read: Callable[[], Effect[None]]
    ) -> None:
        self._inbound = inbound
        self._before_read = before_read
        self._failed: BodyError | None = None
        self._state: _State
        if isinstance(framing, Chunked):
            self._state, self._left = "size", 0
        else:
            self._state, self._left = ("length", framing.size) if framing.size else ("done", 0)
        self._trailer_bytes = 0
        self.bytes_read = 0
        self.started = False

    @property
    def complete(self) -> bool:
        return self._state == "done"

    def _fail(self, message: str) -> Effect[bool, BodyError]:
        self._failed = BodyError(message)
        return fail(self._failed)

    def pull(self) -> Pull:
        def step() -> Pull:
            if self._failed is not None:
                return fail(self._failed)
            if self._state == "done":
                return fail(Done())
            if not self.started:
                self.started = True
                return self._before_read().flat_map(lambda _: self.pull())
            return self._advance().flat_map(lambda data: succeed((data,)) if data else self.pull())

        return suspend(step)

    def _advance(self) -> Effect[bytes, BodyError | SocketError]:
        """One step of the framing: body bytes, or ``b""`` for a step that
        read framing only."""
        match self._state:
            case "length" | "data":
                return self._inbound.read(min(self._left, _READ_SIZE), self._took_data)
            case "size":
                return self._inbound.read_line(_LINE_LIMIT, self._took_size)
            case "data-end":
                return self._inbound.read_line(_LINE_LIMIT, self._took_data_end)
            case "trailers":
                return self._inbound.read_line(_LINE_LIMIT, self._took_trailer)
            case "done":
                return succeed(b"")

    def _took_data(self, data: bytes) -> Effect[bytes, BodyError]:
        if not data:
            return self._fail("the body ended early").as_(b"")
        self._left -= len(data)
        self.bytes_read += len(data)
        if self._left == 0:
            self._state = "done" if self._state == "length" else "data-end"
        return succeed(data)

    def _took_size(self, line: bytes | None) -> Effect[bytes, BodyError]:
        match = None if line is None else _CHUNK_SIZE.match(line)
        size = None if match is None else int(match[1], 16)
        if size is None or size > _MAX_CHUNK_SIZE:
            return self._fail("invalid chunk size").as_(b"")
        self._left = size
        self._state = "data" if self._left else "trailers"
        return succeed(b"")

    def _took_data_end(self, line: bytes | None) -> Effect[bytes, BodyError]:
        if line != b"":
            return self._fail("a chunk does not end with CRLF").as_(b"")
        self._state = "size"
        return succeed(b"")

    def _took_trailer(self, line: bytes | None) -> Effect[bytes, BodyError]:
        if line is None:
            return self._fail("the body ended within its trailers").as_(b"")
        if line == b"":
            self._state = "done"
            return succeed(b"")
        # Trailers are field lines as a head's are, so a bare CR or LF
        # cannot end the message early for one parser and not another.
        self._trailer_bytes += len(line) + 2
        if self._trailer_bytes > _TRAILERS_LIMIT:
            return self._fail("the trailers are too large").as_(b"")
        try:
            parse_field_line(line)
        except HeadError:
            return self._fail("invalid trailer field").as_(b"")
        return succeed(b"")

    def stream(self) -> Stream[bytes, BodyError | SocketError]:
        return from_pull(succeed(self.pull()))

    def drain(self, maximum: int) -> Effect[bool]:
        """Read the rest of the body, discarding it: ``False`` if more than
        ``maximum`` bytes are left or it cannot be read. An unread body sends
        no ``100 Continue``: the client was not asked for it."""
        self.started = True
        start = self.bytes_read
        if self._state == "length" and self._left > maximum:
            return succeed(False)

        def loop() -> Effect[bool]:
            if self.bytes_read - start > maximum:
                return succeed(False)
            if self.complete:
                return succeed(True)
            return self.pull().match_effect(
                on_failure=lambda error: succeed(isinstance(error, Done)),
                on_success=lambda _: suspend(loop),
            )

        return suspend(loop)
