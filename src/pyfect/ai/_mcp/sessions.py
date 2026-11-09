"""The Streamable HTTP transport's sessions, bounded.

Any peer the Origin check admits can open a session, so the table is
capped, a session idle past its timeout is dropped (each request renews
it; one serving a request is kept), and the message that opens it is read
under a size limit. Effect's table has none of these (see PARITY.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyfect import byte_size
from pyfect._core import Effect
from pyfect.ai._mcp.core import McpServerService
from pyfect.ai._mcp.dispatch import Connection
from pyfect.byte_size import ByteSize
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import fail, succeed
from pyfect.errors import IllegalArgumentError

DEFAULT_MAX_SESSIONS = 1000
DEFAULT_IDLE_TIMEOUT: Duration = "30 minutes"
DEFAULT_MAX_MESSAGE_BYTES: byte_size.Input = "4 MiB"


@dataclass(frozen=True)
class Limits:
    """Parsed by ``limits``: every field is positive."""

    max_sessions: int
    idle_timeout: Seconds
    max_message_bytes: ByteSize


def limits(
    max_sessions: int, idle_timeout: Duration, max_message_bytes: byte_size.Input
) -> Effect[Limits, IllegalArgumentError]:
    if isinstance(max_sessions, bool) or max_sessions < 1:
        return fail(IllegalArgumentError(f"max_sessions must be at least 1, got {max_sessions!r}"))
    timeout = to_seconds(idle_timeout)
    if not timeout > 0:
        return fail(
            IllegalArgumentError(f"session_idle_timeout must be positive, got {idle_timeout!r}")
        )
    size = byte_size.from_input(max_message_bytes)
    if size is None or byte_size.is_zero(size):
        return fail(
            IllegalArgumentError(
                f"max_message_bytes must be a positive byte size, got {max_message_bytes!r}"
            )
        )
    return succeed(Limits(max_sessions, timeout, size))


@dataclass
class _Entry:
    connection: Connection
    last_used: float


class Table:
    """Sessions by id. Times are the clock's monotonic seconds."""

    def __init__(self, server: McpServerService, limits: Limits) -> None:
        self._server = server
        self.limits = limits
        self._entries: dict[str, _Entry] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def _idle(self, entry: _Entry, now: float) -> bool:
        timeout = self.limits.idle_timeout
        return (
            not math.isinf(timeout)
            and now - entry.last_used > timeout
            and not entry.connection.busy
        )

    def _drop(self, session_id: str) -> Connection:
        connection = self._entries.pop(session_id).connection
        self._server.disconnect(connection.client_id)
        return connection

    def sweep(self, now: float) -> list[Connection]:
        """Drop the idle sessions; the caller closes what is returned."""
        idle = [id for id, entry in self._entries.items() if self._idle(entry, now)]
        return [self._drop(id) for id in idle]

    def full(self) -> bool:
        return len(self._entries) >= self.limits.max_sessions

    def open(self, session_id: str, connection: Connection, now: float) -> bool:
        """Add a session; ``False`` when the table is full."""
        if self.full():
            return False
        self._entries[session_id] = _Entry(connection, now)
        self._server.connect(connection)
        return True

    def get(self, session_id: str, now: float) -> tuple[Connection | None, Connection | None]:
        """The live session (renewed), and the idle one it replaced, to close."""
        entry = self._entries.get(session_id)
        if entry is None:
            return None, None
        if self._idle(entry, now):
            return None, self._drop(session_id)
        entry.last_used = now
        return entry.connection, None

    def pop(self, session_id: str) -> Connection | None:
        return self._drop(session_id) if session_id in self._entries else None
