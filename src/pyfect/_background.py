"""Tasks nobody awaits.

asyncio keeps only weak references to tasks: one started and dropped can
be collected while it waits ("Task was destroyed but it is pending"), its
work cut short. ``start`` keeps the task until it ends.
``tests/test_background_tasks.py`` bans dropping the result of
``create_task`` / ``ensure_future`` anywhere else.
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


__all__ = ["start"]
