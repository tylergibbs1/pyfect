"""Tasks nobody awaits, which must run to their end: closes and releases.

asyncio keeps only weak references to tasks: one started and dropped can
be collected while it waits ("Task was destroyed but it is pending"), its
work cut short. ``start`` keeps the task until it ends, and a
``LoopThread`` waits for every task started here on its loop, without
cancelling it, before the loop closes (``settle``): a response dropped
while its client shuts down is still closed, so its connection does not
leak. ``tests/test_background_tasks.py`` bans dropping the result of
``create_task`` / ``ensure_future`` anywhere else, and keeping tasks in a
set of one's own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_running: set[asyncio.Task[Any]] = set()


def start[A](coroutine: Coroutine[Any, Any, A], loop: asyncio.AbstractEventLoop) -> asyncio.Task[A]:
    """Run ``coroutine`` as a task of ``loop`` (called on its thread), kept
    until it ends."""
    task = loop.create_task(coroutine)
    _running.add(task)
    task.add_done_callback(_running.discard)
    return task


def running(loop: asyncio.AbstractEventLoop) -> list[asyncio.Task[Any]]:
    """The tasks started on ``loop`` that have not ended."""
    return [task for task in list(_running) if task.get_loop() is loop and not task.done()]


async def settle() -> None:
    """Wait (on the running loop) until no task started on it is left, those
    started meanwhile included."""
    loop = asyncio.get_running_loop()
    while tasks := running(loop):
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["running", "settle", "start"]
