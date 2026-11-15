"""A result the redis-py client's loop decided for a fiber interrupted before
taking it is released, not dropped.

``reserve`` opens its connections on the client's loop, outside the client's
pool. When the pool shut down while one was opening, an interrupt that came
after the connect finished on the loop, but before the fiber took the
connection, dropped it open: nothing closed it, and its socket was reported
by the garbage collector in a later test, after its loop had closed (CI run
43743608270, ``test_an_idle_subscription_does_not_hold_the_test_clock``)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("redis")

import pyfect as fx
from pyfect.persistence.redis import RedisError
from pyfect.persistence.redis_py import _Loop


def _interrupted_after(
    finished: threading.Event, run: fx.Effect[str, RedisError]
) -> fx.Effect[None]:
    """Fork ``run``, wait until its work has finished on the loop, then
    interrupt it."""

    @fx.gen
    def program():
        fiber = yield from run.fork()
        yield from fx.blocking(finished.wait)
        yield from fiber.interrupt()

    return program


def test_a_result_decided_before_the_interrupt_is_released() -> None:
    loop = _Loop()
    finished = threading.Event()
    interrupted = threading.Event()
    released: list[str] = []

    async def open_connection() -> str:
        # Runs before the task's done callbacks: the connection is decided on
        # the loop, but does not reach the fiber until the interrupt landed.
        asyncio.get_running_loop().call_soon(interrupted.wait)
        finished.set()
        return "connection"

    async def release(connection: str) -> None:
        released.append(connection)

    run = loop.run(open_connection, waits_for="work", release=release)
    try:
        fx.run_blocking(_interrupted_after(finished, run))
    finally:
        interrupted.set()
        fx.run_blocking(loop.stop())
        loop._thread.stopped.result()
    assert released == ["connection"]
