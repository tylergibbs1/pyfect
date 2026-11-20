"""The asyncio loop the live sockets run on: one per process, on a daemon
thread of its own, started on first use (``pyfect._loop_bridge``). Fibers
never run on it: they ask it to act (``call_soon``, ``run``)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect._loop_bridge import CANCEL_AND_WAIT, LoopBridge, Make
from pyfect.effect import fail


def _quiet(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Connection errors are reported to the socket that saw them; the
    loop's own report of them (a failed TLS handshake, a reset during
    close) would only be noise."""
    if not isinstance(context.get("exception"), OSError):
        loop.default_exception_handler(context)


_NET = LoopBridge("pyfect-net", exception_handler=_quiet)


def get_loop() -> asyncio.AbstractEventLoop:
    return _NET.loop


def started_loop() -> asyncio.AbstractEventLoop | None:
    """The loop, if a socket has started it."""
    return _NET.started


def call_soon(f: Callable[[], object]) -> None:
    """Run ``f`` on the loop thread."""
    _NET.call_soon(f)


def run[A](make: Make[A]) -> Effect[A, BaseException]:
    """Run the coroutine ``make()`` on the loop and wait for its result.
    Interrupting cancels it and waits until it has ended, so whatever it
    was doing to a socket is over before the fiber goes on (its scope's
    finalizers close what it opened)."""
    return _NET.run(make, fail, waits_for="work", on_interrupt=CANCEL_AND_WAIT)
