"""(pyfect) The asyncmy internals the MySQL driver relies on, pinned against the installed asyncmy.

The driver reads a connection's ``_encoding`` (swapped for a codec that reads bytes that are not
UTF-8 as U+FFFD) and ``_next_seq_id`` (to tell whether a failed command was written). An asyncmy
that renames or changes either must fail here, and fail ``adapt`` at connect, not break quietly.
"""

from __future__ import annotations

import asyncio
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
        adapted: Any = _asyncmy.adapt(conn)
        assert b"\xff\xfe".decode(adapted._encoding) == "\ufffd\ufffd"
        assert "\u00e9".encode(adapted._encoding) == b"\xc3\xa9"

    asyncio.run(run())


def test_a_command_is_sent_once_asyncmy_writes_its_first_packet() -> None:
    async def run() -> None:
        conn, transport = _connected_after_handshake()
        raw = _asyncmy.adapt(conn)
        _asyncmy.begin_command(raw)
        assert not _asyncmy.command_sent(raw)
        await conn._execute_command(_COM_QUERY, "SELECT 1")
        assert transport.written
        assert _asyncmy.command_sent(raw)

    asyncio.run(run())


def test_a_sequence_id_wrapped_to_zero_still_counts_as_sent() -> None:
    """asyncmy wraps the id at 256 packets, so a result failing after a multiple of 256
    packets leaves it 0: the connection is out of step all the same."""

    async def run() -> None:
        conn, _ = _connected_after_handshake()
        raw = _asyncmy.adapt(conn)
        _asyncmy.begin_command(raw)
        conn._next_seq_id = 0
        assert _asyncmy.command_sent(raw)

    asyncio.run(run())


@pytest.mark.parametrize(
    "missing",
    [
        pytest.param({"_encoding": None, "_next_seq_id": 0}, id="no encoding"),
        pytest.param({"_encoding": "utf8", "_next_seq_id": None}, id="no sequence id"),
        pytest.param({"_encoding": "no-such-codec", "_next_seq_id": 0}, id="unknown codec"),
    ],
)
def test_a_connection_without_the_internals_fails_at_adapt(missing: dict[str, object]) -> None:
    class Renamed:
        pass

    conn = Renamed()
    for name, value in missing.items():
        if value is not None:
            setattr(conn, name, value)
    with pytest.raises(_asyncmy.UnsupportedAsyncmyError, match=r"asyncmy .* is not supported"):
        _asyncmy.adapt(conn)
