"""``pyfect.sql.pg._loop.call``: running psycopg coroutines from fibers."""
# pyright: reportPrivateUsage=false

import asyncio
import time

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import testing
from pyfect.sql.pg._loop import call, get_loop
from pyfect.sql.pg.error import catch


@testing.live
def test_a_result_that_lands_as_the_fiber_is_interrupted_is_released():
    """The coroutine finishes after the interrupt but before the loop can
    stop it: what it made is released, not lost."""
    loop = get_loop()
    gate: asyncio.Future[str] = loop.create_future()
    released: list[str] = []

    async def make() -> str:
        return await gate

    async def release(value: str) -> None:
        released.append(value)

    def finish_then_hold_the_loop() -> None:
        # The task's last step is queued before the stop the interrupt
        # posts, so it completes first.
        gate.set_result("session")
        time.sleep(0.1)

    child = yield from call(make, catch("m", "query"), release=release).fork()
    yield from fx.yield_now()
    yield from fx.sync(lambda: loop.call_soon_threadsafe(finish_then_hold_the_loop))
    yield from child.interrupt()
    exit_ = yield from child.await_exit()
    assert isinstance(exit_, fx.Failure)
    assert exit_.cause.has_interrupts_only
    assert released == ["session"]
