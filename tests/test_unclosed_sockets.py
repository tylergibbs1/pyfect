"""The tests/ plugin that fails the test leaving a socket for the garbage collector."""

from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT

TESTS = """
import asyncio
import socket


class Holder:
    def __init__(self, sock):
        self.sock = sock
        self.me = self  # a cycle: only the collector frees it


def test_drops_an_open_socket():
    Holder(socket.socket())


def test_drops_an_open_transport():
    loop = asyncio.new_event_loop()
    left, right = socket.socketpair()

    async def connect():
        return await loop.connect_accepted_socket(asyncio.Protocol, left)

    transport, _ = loop.run_until_complete(connect())
    Holder(transport)
    right.close()
    loop.close()


def test_closes_its_socket():
    with socket.socket():
        pass


def test_makes_no_socket():
    pass
"""


def test_a_socket_left_open_fails_the_test_that_dropped_it(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each leak errors in its own test's teardown, naming the socket (and a transport's
    protocol); the tests that closed theirs or made none pass."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(test_a=TESTS)
    pytester.makeini("[pytest]\nfilterwarnings = error::ResourceWarning\n")
    result = pytester.runpytest_subprocess(
        "-p", "_unclosed_sockets", "-p", "no:randomly", timeout=SUBPROCESS_TIMEOUT
    )
    result.assert_outcomes(passed=4, errors=2)
    out = " ".join(result.stdout.str().split())
    assert "ERROR at teardown of test_drops_an_open_socket" in out, out
    assert "ERROR at teardown of test_drops_an_open_transport" in out, out
    assert "unclosed <socket.socket" in out, out
    assert "unclosed transport" in out and "(protocol Protocol)" in out, out
