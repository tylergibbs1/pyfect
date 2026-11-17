"""(pyfect) The asyncmy internals the MySQL driver relies on, pinned against the installed asyncmy.

The driver reads a connection's ``_encoding`` (swapped for a codec that reads bytes that are not
UTF-8 as U+FFFD) and watches its ``_write_bytes`` (to tell whether a failed command was written).
An asyncmy that renames or changes either must fail here, and fail ``adapt`` at connect, not break
quietly. The driver writes nothing of its own into asyncmy's state: asyncmy 0.2.18 typed
``_next_seq_id`` as an unsigned int, and the -1 the driver once wrote there failed every query.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from asyncmy.connection import Connection

from pyfect.sql.mysql import _asyncmy

_COM_QUERY = 3


class _Transport:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def is_closing(self) -> bool:
        return False

    def write(self, data: bytes) -> None:
        self.written.append(data)


def _connected_after_handshake() -> tuple[Any, _Transport]:
    """A connection as asyncmy leaves it after its handshake, writing to a fake transport.
    Called inside a running loop, which asyncmy's constructor takes."""
    conn: Any = Connection(charset="utf8mb4")
    transport = _Transport()
    conn._transport = transport
    conn._connected = True
    conn._result = None
    conn._next_seq_id = 0  # what the handshake leaves (asyncmy's connect sets it)
    return conn, transport


def test_utf8_connections_decode_with_the_replacing_codec() -> None:
    async def run() -> None:
        conn, _ = _connected_after_handshake()
        assert conn._encoding == "utf8"
        adapted: Any = _asyncmy.adapt(conn).raw
        assert b"\xff\xfe".decode(adapted._encoding) == "\ufffd\ufffd"
        assert "\u00e9".encode(adapted._encoding) == b"\xc3\xa9"

    asyncio.run(run())


def test_a_command_is_sent_once_asyncmy_writes_its_first_packet() -> None:
    async def run() -> None:
        conn, transport = _connected_after_handshake()
        writes = _asyncmy.adapt(conn).writes
        writes.begin()
        assert not writes.sent
        await conn._execute_command(_COM_QUERY, "SELECT 1")
        assert transport.written
        assert writes.sent
        writes.begin()
        assert not writes.sent

    asyncio.run(run())


def test_a_command_that_fails_before_asyncmy_writes_it_is_not_sent() -> None:
    async def run() -> None:
        conn, transport = _connected_after_handshake()
        writes = _asyncmy.adapt(conn).writes
        writes.begin()
        with pytest.raises(UnicodeEncodeError):
            await conn._execute_command(_COM_QUERY, "SELECT '\ud800'")
        assert not transport.written
        assert not writes.sent

    asyncio.run(run())


def test_adapt_leaves_the_sequence_id_alone() -> None:
    async def run() -> None:
        conn, _ = _connected_after_handshake()
        conn._next_seq_id = 7
        writes = _asyncmy.adapt(conn).writes
        writes.begin()
        assert conn._next_seq_id == 7

    asyncio.run(run())


class _Fixed:
    """A connection whose ``_write_bytes`` cannot be replaced."""

    __slots__ = ("_encoding",)

    def __init__(self) -> None:
        self._encoding = "utf8"

    def _write_bytes(self, data: bytes) -> None:
        return None


@pytest.mark.parametrize(
    "conn",
    [
        pytest.param(SimpleNamespace(_write_bytes=print), id="no encoding"),
        pytest.param(SimpleNamespace(_encoding="utf8"), id="no write"),
        pytest.param(SimpleNamespace(_encoding="utf8", _write_bytes=0), id="write not callable"),
        pytest.param(
            SimpleNamespace(_encoding="no-such-codec", _write_bytes=print), id="unknown codec"
        ),
        pytest.param(_Fixed(), id="write not replaceable"),
    ],
)
def test_a_connection_without_the_internals_fails_at_adapt(conn: object) -> None:
    with pytest.raises(_asyncmy.UnsupportedAsyncmyError, match=r"asyncmy .* is not supported"):
        _asyncmy.adapt(conn)
