"""A head or chunk line sent a byte at a time costs the live server linear time.

Every arrival used to search the whole buffered head again (for its end and for a bare LF),
so a client dripping a 16 KiB head one byte per packet cost the event loop about a second of
CPU, and a few such connections could stall every other request. llhttp parses
incrementally; each byte is now searched once.
"""

import time
from collections.abc import Callable

import pyfect as fx
from pyfect.effect import Effect, succeed
from pyfect.http.live_server._inbound import BareLineFeed, Inbound


class _Drip:
    """A connection that receives ``data`` one byte per read."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.sent = 0

    def pull_into(self, take: Callable[[tuple[bytes, ...]], bool]) -> Effect[bool]:
        if self.sent == len(self.data):
            return succeed(False)
        byte = self.data[self.sent : self.sent + 1]
        self.sent += 1
        return succeed(take((byte,)))


def _inbound(data: bytes) -> Inbound:
    return Inbound(_Drip(data))  # pyright: ignore[reportArgumentType]


def _head(size: int) -> bytes:
    return b"GET / HTTP/1.1\r\nhost: a\r\nx: " + b"a" * size


def _seconds_to_read(size: int) -> float:
    inbound = _inbound(_head(size) + b"\r\n\r\n")
    start = time.perf_counter()
    assert fx.run_sync(inbound.read_head(10**7).or_die()) == _head(size)
    return time.perf_counter() - start


def test_a_dripped_head_costs_linear_time():
    small = min(_seconds_to_read(8 * 1024) for _ in range(3))
    large = min(_seconds_to_read(32 * 1024) for _ in range(3))
    # Four times the bytes: about four times the time when linear, sixteen when quadratic.
    assert large / small < 8, (small, large)


def test_dripped_heads_and_lines_parse_as_whole_ones():
    inbound = _inbound(b"\r\n\nGET / HTTP/1.1\r\nhost: a\r\n\r\n5\r\nrest")
    assert fx.run_sync(inbound.read_head(1024).or_die()) == b"GET / HTTP/1.1\r\nhost: a"
    assert fx.run_sync(inbound.read_line(1024, succeed).or_die()) == b"5"
    bare = _inbound(b"GET / HTTP/1.1\r\nhost: a\nx: b\r\n\r\n")
    assert isinstance(fx.run_sync(bare.read_head(1024).flip().or_die()), BareLineFeed)
    lf_only = _inbound(b"5\n")
    assert fx.run_sync(lf_only.read_line(1024, succeed).or_die()) is None
