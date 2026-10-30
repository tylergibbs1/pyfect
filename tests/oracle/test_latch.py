"""Ports of Effect's ``Latch.test.ts``.

Each test's docstring is the Effect test title. A resume in Effect runs the
woken fiber at once; in pyfect it goes through the scheduler, so a port
yields where Effect's fiber would already have run.
"""

from typing import Any

import pyfect as fx
from pyfect import testing

from ._task_queue import TaskQueue


def _interrupted(ex: fx.Exit[Any, Any]) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _yield_twice() -> fx.Effect[None]:
    return fx.yield_now().and_then(fx.yield_now())


@testing.effect
def test_release_wakes_current_waiters_and_keeps_the_latch_closed():
    """release wakes current waiters and keeps the latch closed"""
    latch = yield from fx.Latch.make(False)
    waiter = yield from latch.wait().fork(start_immediately=True)
    assert waiter.poll_unsafe() is None

    yield from latch.release()
    yield from _yield_twice()

    assert waiter.poll_unsafe() is not None
    assert not latch.is_open()


@testing.effect
def test_is_open_reflects_the_state_of_the_latch():
    """isOpen reflects the state of the latch"""
    latch = yield from fx.Latch.make(False)
    assert not latch.is_open()

    yield from latch.open()
    yield from fx.yield_now()

    assert latch.is_open()


@testing.effect
def test_open_then_close_does_not_resume_waiters_registered_after_close():
    """open then close does not resume waiters registered after close"""
    latch = fx.Latch(False)
    before = yield from latch.wait().fork(start_immediately=True)

    yield from latch.open()
    yield from latch.close()
    after = yield from latch.wait().fork(start_immediately=True)
    yield from _yield_twice()

    assert before.poll_unsafe() is not None
    assert after.poll_unsafe() is None


@testing.effect
def test_release_while_a_flush_is_pending_covers_the_new_waiters():
    """release while a flush is pending covers the new waiters"""
    latch = yield from fx.Latch.make(False)
    queue = TaskQueue()

    first = yield from latch.wait().fork(start_immediately=True)
    yield from queue.provide(latch.release())
    assert len(queue.tasks) == 1

    second = yield from latch.wait().fork(start_immediately=True)
    yield from queue.provide(latch.release())
    assert len(queue.tasks) == 1

    queue.run_next()
    yield from first.join()
    yield from second.join()
    assert not latch.is_open()


@testing.effect
def test_release_does_not_resume_waiters_registered_after_the_release():
    """release does not resume waiters registered after the release"""
    latch = yield from fx.Latch.make(False)
    covered = yield from latch.wait().fork(start_immediately=True)

    yield from latch.release()
    late = yield from latch.wait().fork(start_immediately=True)
    yield from _yield_twice()

    assert covered.poll_unsafe() is not None
    assert late.poll_unsafe() is None


@testing.effect
def test_unsafe_open_does_not_resume_waiters_registered_after_a_reentrant_close():
    """openUnsafe does not resume waiters registered after a reentrant close"""
    latch = fx.Latch(False)
    queue = TaskQueue()
    second: list[fx.Fiber[None]] = []

    @fx.gen
    def first():
        yield from latch.wait()
        latch.close_unsafe()
        second.append((yield from latch.wait().fork(start_immediately=True)))
        return (yield from fx.never)

    yield from first.fork(start_immediately=True)
    yield from queue.provide(latch.release())
    latch.open_unsafe()
    # Effect runs the first waiter inside open_unsafe; here it runs next.
    yield from _yield_twice()
    assert second[0].poll_unsafe() is None
    assert len(queue.tasks) == 1

    queue.run_next()
    yield from _yield_twice()
    assert second[0].poll_unsafe() is None


@testing.effect
def test_interrupting_a_waiter_removes_it_from_a_pending_flush():
    """interrupting a waiter removes it from a pending flush"""
    latch = yield from fx.Latch.make(False)
    queue = TaskQueue()
    resumed: list[str] = []

    waiter = yield from latch.when_open(fx.sync(lambda: resumed.append("waiter"))).fork(
        start_immediately=True
    )
    yield from queue.provide(latch.release())
    assert len(queue.tasks) == 1

    yield from waiter.interrupt()
    assert _interrupted((yield from waiter.await_exit()))

    queue.run_next()
    yield from _yield_twice()
    assert resumed == []
    assert not latch.is_open()


@testing.effect
def test_await_is_interruptible_and_cleans_up_interrupted_waiters():
    """await is interruptible and cleans up interrupted waiters"""
    latch = yield from fx.Latch.make(False)
    queue = TaskQueue()
    resumed: list[str] = []

    interrupted = yield from latch.when_open(fx.sync(lambda: resumed.append("interrupted"))).fork(
        start_immediately=True
    )
    assert interrupted.poll_unsafe() is None

    yield from interrupted.interrupt()
    assert _interrupted((yield from interrupted.await_exit()))

    yield from queue.provide(latch.release())
    assert len(queue.tasks) == 0

    live = yield from latch.when_open(fx.sync(lambda: resumed.append("live"))).fork(
        start_immediately=True
    )
    assert live.poll_unsafe() is None

    yield from queue.provide(latch.release())
    assert len(queue.tasks) == 1
    assert live.poll_unsafe() is None

    queue.run_next()
    yield from live.join()

    assert resumed == ["live"]
    assert not latch.is_open()
