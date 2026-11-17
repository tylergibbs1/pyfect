"""Every worker backend says whether it copies a message when it is sent or hands over the
object itself, and a test holds it to that: a new backend can't skip the choice."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from _subclasses import subclasses

import pyfect as fx
from pyfect import effect, testing
from pyfect._core import Effect
from pyfect.queue import Queue
from pyfect.workers import (
    ProcessWorker,
    ThreadWorker,
    WorkerHandle,
    WorkerPlatform,
    python_worker,
    python_worker_runner,
)
from pyfect.workers.worker import Worker
from pyfect.workers.worker_runner import WorkerRunnerPlatform

_ECHO = """
import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers.worker_runner import WorkerRunnerPlatform

@effect.gen
def main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())
    yield from runner.run(lambda port, message: runner.send(port, message))

fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)).or_die())
"""


@effect.gen
def _thread_echo():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())

    def handle(port: int, message: Any) -> Effect[None]:
        return runner.send(port, message)

    yield from runner.run(handle)


def _run_thread_echo() -> None:
    fx.run_blocking(_thread_echo.pipe(fx.provide(python_worker_runner.layer)).or_die())


COPIES: dict[type[WorkerHandle], tuple[Callable[[], WorkerHandle], bool]] = {
    ProcessWorker: (lambda: ProcessWorker(["-c", _ECHO]), True),
    # 0.7.0: thread-worker-copy-070 copies, as Effect's postMessage structured-clones.
    ThreadWorker: (lambda: ThreadWorker(_run_thread_echo), False),
}


@fx.fn
def _started(handle: WorkerHandle):
    worker: Worker[Any, Any] = yield from (
        WorkerPlatform()
        .flat_map(lambda platform: platform.spawn(0))
        .pipe(fx.provide(python_worker.layer(lambda _: handle)))
    )
    replies = yield from Queue[object].unbounded()
    yield from worker.run(replies.offer).fork_scoped()
    yield from worker.send("ready")
    assert (yield from replies.take()) == "ready"
    return worker, replies


def test_every_backend_is_checked() -> None:
    """A new backend must say whether it copies messages."""
    assert subclasses(WorkerHandle) == set(COPIES)


@pytest.mark.parametrize("backend", list(COPIES), ids=lambda b: b.__name__)
@testing.live(timeout="20 seconds")
def test_a_backend_copies_or_shares_a_message_as_it_says(backend: type[WorkerHandle]):
    start, copies = COPIES[backend]
    worker, replies = yield from _started(start())
    items = [0, 1, 2]
    yield from worker.send(items)
    echoed = yield from replies.take()
    assert echoed == items
    assert (echoed is not items) is copies
