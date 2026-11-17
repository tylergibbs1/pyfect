"""Every worker backend copies a message when it is sent, both ways, as Effect's
``postMessage`` structured-clones it: a change made after ``send`` never reaches
the other side. Values in the transfer list are moved where the backend can
(a thread), not copied."""

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
    WorkerSendError,
    python_worker,
    python_worker_runner,
)
from pyfect.workers.worker import Worker
from pyfect.workers.worker_runner import WorkerRunnerPlatform

_MOVED = bytearray(b"moved")

_MAIN = """
import pyfect as fx
from pyfect import effect
from pyfect.workers import python_worker_runner
from pyfect.workers.worker_runner import WorkerRunnerPlatform

@effect.gen
def main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())

    def handle(port, message):
        if message == "send":
            items = [0] * 3
            runner.send_unsafe(port, items)
            items.append(99)
            return None
        return fx.sleep("50 millis").and_then(fx.suspend(lambda: runner.send(port, len(message))))

    yield from runner.run(handle)

fx.run_blocking(main.pipe(fx.provide(python_worker_runner.layer)).or_die())
"""


@effect.gen
def _thread_main():
    runner = yield from WorkerRunnerPlatform().flat_map(lambda p: p.start())

    def handle(port: int, message: Any) -> Effect[None] | None:
        if message == "send":
            items = [0] * 3
            runner.send_unsafe(port, items)
            items.append(99)
            return None
        if isinstance(message, tuple):
            return runner.send(port, message[0] is _MOVED)
        return fx.sleep("50 millis").and_then(fx.suspend(lambda: runner.send(port, len(message))))

    yield from runner.run(handle)


def _run_thread_main() -> None:
    fx.run_blocking(_thread_main.pipe(fx.provide(python_worker_runner.layer)).or_die())


BACKENDS: dict[type[WorkerHandle], Callable[[], WorkerHandle]] = {
    ThreadWorker: lambda: ThreadWorker(_run_thread_main),
    ProcessWorker: lambda: ProcessWorker(["-c", _MAIN]),
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
    # Ready: a message sent before is buffered, and copied when posted (as in Effect).
    yield from worker.send([0])
    assert (yield from replies.take()) == 1
    return worker, replies


def test_every_backend_is_checked() -> None:
    """A new backend must show that it copies messages too."""
    assert subclasses(WorkerHandle) == set(BACKENDS)


@pytest.mark.parametrize("backend", list(BACKENDS), ids=lambda b: b.__name__)
@testing.live(timeout="20 seconds")
def test_a_change_after_send_does_not_reach_the_other_side(backend: type[WorkerHandle]):
    worker, replies = yield from _started(BACKENDS[backend]())
    items = [0] * 10
    yield from worker.send(items)
    items.append(99)
    assert (yield from replies.take()) == 10
    yield from worker.send("send")
    received: Any = yield from replies.take()
    yield from fx.sleep("50 millis")
    assert received == [0, 0, 0]


@testing.live
def test_a_thread_worker_gets_a_transferred_value_itself():
    worker, replies = yield from _started(BACKENDS[ThreadWorker]())
    yield from worker.send((_MOVED,), [_MOVED])
    yield from worker.send((bytearray(b"copied"),))
    assert [(yield from replies.take()), (yield from replies.take())] == [True, False]


@testing.live
def test_a_message_a_thread_worker_cannot_copy_fails_the_send():
    worker, _replies = yield from _started(BACKENDS[ThreadWorker]())
    error = yield from worker.send(lambda: None).flip()
    assert isinstance(error.reason, WorkerSendError)
