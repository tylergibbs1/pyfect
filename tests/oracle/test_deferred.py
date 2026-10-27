"""Ports of Effect's ``Deferred.test.ts``.

Each test's docstring is the Effect test title. Effect's ``Deferred.await``
is ``wait()``; ``poll`` gives the stored effect or ``None``.
"""

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.exit import fail as fail_exit
from pyfect.exit import interrupt as interrupt_exit


def _counter(step: int, box: list[int]) -> fx.Effect[int]:
    def bump() -> int:
        box[0] += step
        return box[0]

    return fx.sync(bump)


def _waiters(d: fx.Deferred[Any, Any]) -> int:
    return len(d._waiters)  # pyright: ignore[reportPrivateUsage]


# --- success ----------------------------------------------------------------------------------


@testing.effect
def test_succeed_should_propagate_the_value():
    """succeed - should propagate the value"""
    d = yield from fx.Deferred[int].make()
    assert (yield from d.succeed(1)) is True
    assert (yield from d.succeed(1)) is False
    assert (yield from d.wait()) == 1


@testing.effect
def test_complete_should_memoize_the_result_of_the_provided_effect():
    """complete - should memoize the result of the provided effect"""
    box = [0]
    d = yield from fx.Deferred[int].make()
    assert (yield from d.complete(_counter(1, box))) is True
    assert (yield from d.complete(_counter(1, box))) is False
    assert box == [1]
    assert (yield from d.wait()) == 1
    assert (yield from d.wait()) == 1
    assert box == [1]


@testing.effect
def test_complete_with_should_not_memoize_the_provided_effect():
    """completeWith - should not memoize the provided effect"""
    box = [0]
    d = yield from fx.Deferred[int].make()
    assert (yield from d.complete_with(_counter(1, box))) is True
    assert (yield from d.complete_with(_counter(10, box))) is False
    assert box == [0]
    assert (yield from d.wait()) == 1
    assert (yield from d.wait()) == 2
    assert box == [2]


# --- failure ----------------------------------------------------------------------------------


@testing.effect
def test_fail_should_propagate_the_failure():
    """fail - should propagate the failure"""
    d = yield from fx.Deferred[int, str].make()
    assert (yield from d.fail("boom")) is True
    assert (yield from d.succeed(1)) is False
    assert (yield from d.wait().exit()) == fail_exit("boom")


@testing.effect
def test_complete_should_memoize_the_failure_of_the_provided_effect():
    """complete - should memoize the failure of the provided effect"""
    d = yield from fx.Deferred[int, str].make()
    assert (yield from d.complete(fx.fail("boom"))) is True
    assert (yield from d.complete(fx.fail("boom2"))) is False
    assert (yield from d.wait().exit()) == fail_exit("boom")
    assert (yield from d.wait().exit()) == fail_exit("boom")


@testing.effect
def test_complete_with_should_memoize_the_provided_effect():
    """completeWith - should memoize the provided effect"""
    failures = iter(["boom", "boom2"])
    d = yield from fx.Deferred[int, str].make()
    assert (yield from d.complete_with(fx.fail_sync(lambda: next(failures)))) is True
    assert (yield from d.complete_with(fx.fail_sync(lambda: "boom3"))) is False
    assert (yield from d.wait().exit()) == fail_exit("boom")
    assert (yield from d.wait().exit()) == fail_exit("boom2")


# --- interruption -----------------------------------------------------------------------------


@testing.effect
def test_interrupt_should_propagate_the_interruption():
    """interrupt - should propagate the interruption"""
    d = yield from fx.Deferred[int].make()
    assert (yield from d.interrupt_with(-1)) is True
    assert (yield from d.interrupt()) is False
    assert (yield from d.wait().exit()) == interrupt_exit(-1)


@testing.effect
def test_await_interrupting_a_suspended_waiter_removes_it():
    """await - interrupting a suspended waiter removes it"""
    d = yield from fx.Deferred[int].make()
    interrupted = yield from d.wait().fork(start_immediately=True)
    live = yield from d.wait().fork(start_immediately=True)

    assert _waiters(d) == 2
    yield from interrupted.interrupt()
    ex = yield from interrupted.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert _waiters(d) == 1

    assert (yield from d.succeed(42)) is True
    assert (yield from live.join()) == 42


@testing.effect
def test_await_interrupting_a_waiter_after_completion_does_not_die():
    """await - interrupting a waiter after completion does not die"""
    d = yield from fx.Deferred[int].make()
    interrupted = yield from d.wait().fork(start_immediately=True)
    live = yield from d.wait().fork(start_immediately=True)
    assert _waiters(d) == 2

    # Effect's ``doneUnsafe(deferred, effect)`` is ``complete_with``; nothing
    # runs between it and the interrupt.
    yield from d.complete_with(fx.yield_now().as_(42))
    assert _waiters(d) == 0
    interrupted.unsafe_interrupt_as(None)

    ex = yield from interrupted.await_exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert not ex.cause.has_dies
    assert (yield from live.join()) == 42


@testing.effect
def test_done_with_an_interrupt_cause_resumes_every_suspended_waiter():
    """done with an interrupt cause resumes every suspended waiter"""
    d = yield from fx.Deferred[int].make()
    first = yield from d.wait().fork(start_immediately=True)
    second = yield from d.wait().fork(start_immediately=True)
    assert _waiters(d) == 2

    assert (yield from d.done(interrupt_exit())) is True

    settled = yield from (
        fx.Fiber.await_all([first, second]).timeout_option(1).fork(start_immediately=True)
    )
    yield from testing.adjust(1)
    exits = yield from settled.join()
    assert exits is not None, "every waiter should settle"
    for ex in exits.value:
        assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts


# --- polling ----------------------------------------------------------------------------------


@testing.effect
def test_poll_should_return_option_none_when_the_deferred_is_incomplete():
    """poll - should return Option.none when the deferred is incomplete"""
    d = yield from fx.Deferred[int].make()
    assert (yield from d.poll()) is None


@testing.effect
def test_poll_should_return_option_some_when_the_deferred_was_completed():
    """poll - should return Option.some when the deferred was completed"""
    d = yield from fx.Deferred[int].make()
    yield from d.succeed(1)
    polled = yield from d.poll()
    assert polled is not None
    assert (yield from polled) == 1


@testing.effect
def test_poll_should_return_option_some_when_the_deferred_was_failed():
    """poll - should return Option.some when the deferred was failed"""
    d = yield from fx.Deferred[int, str].make()
    yield from d.fail("boom")
    polled = yield from d.poll()
    assert polled is not None
    assert (yield from polled.exit()) == fail_exit("boom")


@testing.effect
def test_poll_should_return_option_some_when_the_deferred_was_interrupted():
    """poll - should return Option.some when the deferred was interrupted"""
    d = yield from fx.Deferred[int, str].make()
    yield from d.interrupt_with(-1)
    polled = yield from d.poll()
    assert polled is not None
    assert (yield from polled.exit()) == interrupt_exit(-1)


# --- done -------------------------------------------------------------------------------------


@testing.effect
def test_is_done_should_return_true_when_suceeded():
    """isDone - should return true when suceeded"""
    d = yield from fx.Deferred[int].make()
    yield from d.succeed(1)
    assert (yield from d.is_done()) is True


@testing.effect
def test_is_done_should_return_true_when_failed():
    """isDone - should return true when failed"""
    d = yield from fx.Deferred[int, str].make()
    yield from d.fail("boom")
    assert (yield from d.is_done()) is True
