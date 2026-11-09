"""What "interrupting a statement ends it on the server" means, for every driver's tests:
asked of the server over another connection, soon after the interrupt returned.

What the client sees proves nothing: its socket is closed either way, and a client statement
that merely works next (on a new connection) passes while the old one still holds its locks.
MySQL 8.4 once answered our kill with an error that went unread, and tests asking only the
client stayed green."""

import time
from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx

GONE_WITHIN = 1.5
"""Seconds. Well under what a server takes to notice a closed socket by itself (measured on
MySQL 8.4: about 5 s into a ``SLEEP``, and not within 20 s for a busy ``SELECT``)."""


def until_running(on_server: Callable[[], object]) -> Generator[Any, Any]:
    """Wait until the statement ``on_server`` looks for has reached the server."""
    deadline = time.monotonic() + 15
    while not (yield from fx.blocking(on_server)):
        assert time.monotonic() < deadline, "the statement never reached the server"
        yield from fx.sleep("20 millis")


def gone_soon(on_server: Callable[[], object]) -> Generator[Any, Any]:
    """``on_server`` is empty within ``GONE_WITHIN``."""
    deadline = time.monotonic() + GONE_WITHIN
    while running := (yield from fx.blocking(on_server)):
        assert time.monotonic() < deadline, f"still on the server: {running}"
        yield from fx.sleep("50 millis")


def interrupted_and_gone(
    statement: fx.Effect[Any, Any], on_server: Callable[[], object]
) -> Generator[Any, Any]:
    """Run ``statement``, interrupt it once the server has it, and ask the server."""
    fiber = yield from statement.fork()
    yield from until_running(on_server)
    yield from fiber.interrupt()
    yield from gone_soon(on_server)


__all__ = ["GONE_WITHIN", "gone_soon", "interrupted_and_gone", "until_running"]
