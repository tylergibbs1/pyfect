"""Splitting a response body into rows, one per line, and finding the
exception ClickHouse writes into a body it already began.

From 25.11 a query that fails after its first rows were sent ends its body
with ``\\r\\n__exception__\\r\\n<tag>\\r\\n<message>\\n<length> <tag>\\r\\n__exception__\\r\\n``,
``<tag>`` being the response's ``X-ClickHouse-Exception-Tag``, and then
cuts the chunked body short (no last chunk), so the transport fails right
after it: the exception read wins. A row never ends with ``\\r`` (formats
escape it), so the first line that does starts the exception.
"""

from __future__ import annotations

import re

from pyfect._js import text_encode
from pyfect.sql.clickhouse.error import ClickhouseError, parse_error

_MARKER = b"__exception__"


def _message(tail: bytes, tag: bytes) -> ClickhouseError:
    """The exception in ``tail``, the body from the line ending in ``\\r``."""
    head = b"\r\n" + _MARKER + b"\r\n" + tag + b"\r\n"
    trailer = re.compile(rb"\n\d+ " + re.escape(tag) + rb"\r\n" + _MARKER + rb"\r\n$")
    start = tail.find(head)
    end = trailer.search(tail)
    if start < 0 or end is None or end.start() < start + len(head):
        return ClickhouseError("there was an error in the stream, but the last chunk is malformed")
    return parse_error(tail[start + len(head) : end.start()].decode("utf-8", "replace"))


def body_error(body: bytes, tag: str | None) -> ClickhouseError | None:
    """The exception a whole ``body`` ends with, if any."""
    if tag is None:
        return None
    start = body.find(b"\r\n" + _MARKER + b"\r\n" + text_encode(tag) + b"\r\n")
    return None if start < 0 else _message(body[start:], text_encode(tag))


class RowSplitter:
    """Rows (lines, as text) from a body's chunks."""

    __slots__ = ("_pending", "_scanned", "_tag", "_tail")

    def __init__(self, tag: str | None) -> None:
        self._tag = None if tag is None else text_encode(tag)
        self._pending = bytearray()
        self._scanned = 0
        """How much of ``_pending`` holds no line break: each byte is searched once."""
        self._tail: bytearray | None = None

    def feed(self, chunk: bytes) -> list[str]:
        """The rows ``chunk`` completes."""
        if self._tail is not None:
            self._tail += chunk
            return []
        self._pending += chunk
        rows: list[str] = []
        start = 0
        pending = self._pending
        while (end := pending.find(b"\n", max(start, self._scanned))) >= 0:
            if self._tag is not None and end > 0 and pending[end - 1] == 0x0D:
                # ``start`` is past the row before the exception's ``\r\n``.
                self._tail = bytearray(pending[end - 1 :])
                self._pending = bytearray()
                return rows
            rows.append(pending[start:end].decode())
            start = end + 1
        del pending[:start]
        self._scanned = len(pending)
        return rows

    def failure(self) -> ClickhouseError | None:
        """The exception the body began, if one did."""
        if self._tail is None or self._tag is None:
            return None
        return _message(bytes(self._tail), self._tag)

    def finish(self) -> list[str]:
        """The last row, once the body ended; raises the body's exception."""
        failure = self.failure()
        if failure is not None:
            raise failure
        rest = self._pending.decode()
        self._pending = bytearray()
        return [rest] if rest else []


__all__ = ["RowSplitter", "body_error"]
