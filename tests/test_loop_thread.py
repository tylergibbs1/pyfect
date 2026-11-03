"""A loop thread settles all of its work before its loop closes: a
generator dropped (on any thread) as it stops is closed to its end, a
coroutine still running is cancelled, and nothing is reported as lost."""

from __future__ import annotations

import asyncio
import gc
import logging
import threading
from collections.abc import AsyncGenerator

import pytest

from pyfect._loop_thread import LoopThread

_SETTLED = 5.0


async def _nested(cleaned: list[str], depth: int) -> AsyncGenerator[int]:
    """A generator over ``depth`` nested ones, each awaiting in its
    cleanup (as httpx's response bodies do): closing one drops the next,
    whose close takes more loop turns."""
    try:
        if depth == 0:
            while True:
                yield 0
        else:
            async for item in _nested(cleaned, depth - 1):
                yield item
    finally:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        cleaned.append(f"level {depth}")


def _started(thread: LoopThread, cleaned: list[str], depth: int) -> AsyncGenerator[int]:
    async def start() -> AsyncGenerator[int]:
        generator = _nested(cleaned, depth)
        await anext(generator)
        return generator

    return thread.submit(start).result(_SETTLED)


def test_a_generator_dropped_as_the_loop_stops_is_closed_before_it_closes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    thread = LoopThread("test-loop")
    cleaned: list[str] = []
    generator = _started(thread, cleaned, depth=5)
    del generator  # finalized here, on this thread: its close goes to the loop
    thread.stop()
    thread.stopped.result(_SETTLED)
    assert sorted(cleaned) == [f"level {depth}" for depth in range(6)]
    gc.collect()
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_generator_held_by_a_cancelled_coroutine_is_closed_before_the_loop_closes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    thread = LoopThread("test-loop")
    cleaned: list[str] = []
    holding = threading.Event()

    async def hold() -> None:
        generator = _nested(cleaned, 3)
        await anext(generator)
        holding.set()
        await asyncio.Event().wait()  # cancelled at stop, dropping the generator

    thread.submit(hold)
    assert holding.wait(_SETTLED)
    thread.stop()
    thread.stopped.result(_SETTLED)
    assert sorted(cleaned) == [f"level {depth}" for depth in range(4)]
    gc.collect()
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def test_a_generator_still_open_at_stop_is_closed() -> None:
    thread = LoopThread("test-loop")
    cleaned: list[str] = []
    generator = _started(thread, cleaned, depth=2)
    thread.stop()
    thread.stopped.result(_SETTLED)
    assert sorted(cleaned) == ["level 0", "level 1", "level 2"]
    del generator


def test_a_coroutine_still_running_at_stop_is_cancelled() -> None:
    thread = LoopThread("test-loop")
    waiting = thread.submit(asyncio.Event().wait)
    thread.stop()
    thread.stopped.result(_SETTLED)
    assert waiting.cancelled()
