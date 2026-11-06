"""Ports of Effect's ``Fiber.test.ts``.

Each test's docstring is the Effect test title (Effect's ``Latch.await`` is
``wait()``). Omitted, with the reason:

- "is a fiber": ``Fiber.isFiber`` is ``isinstance(x, fx.Fiber)``.
- "delivers a pending interrupt when interruptibleMask restores
  interruptibility" is ported in ``tests/oracle/test_effect_combinators.py``.
"""

from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.tracer import CurrentStackFrame, InterruptorStackTrace, StackFrame, StackTrace


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def test_run_in_closes_the_latest_registration_first_when_a_fiber_is_registered_twice():
    """runIn closes the latest registration first when a fiber is registered twice"""
    events: list[str] = []
    scope = fx.CloseableScope()

    @fx.gen
    def program():
        interrupted = fx.sync(lambda: events.append("interrupted"))
        fiber = yield from fx.never.ensuring(interrupted).fork_daemon(start_immediately=True)
        fiber.run_in(scope)
        yield from scope.add_finalizer(lambda _: fx.sync(lambda: events.append("finalizer")))
        fiber.run_in(scope)
        yield from scope.close(fx.exit.succeed(None))

    fx.run_blocking(program)
    assert events == ["interrupted", "finalizer"]


@testing.effect
def test_run_in_does_not_wait_for_the_fiber_that_closes_the_scope():
    """runIn does not wait for the fiber that closes the scope"""
    scope = fx.CloseableScope()
    fiber = yield from scope.close(fx.exit.succeed(None)).as_("closed").fork_daemon()
    fiber.run_in(scope)
    assert (yield from fiber.await_exit()) == fx.Success("closed")


@testing.effect
def test_notifies_all_observers_when_an_observer_cancels_during_exit():
    """notifies all observers when an observer cancels during exit"""
    fiber = yield from fx.never.fork_daemon()
    observed: list[int] = []

    def cancelling(_: fx.Exit[Never, Never]) -> None:
        observed.append(1)
        cancel()

    cancel = fiber.add_observer_unsafe(cancelling)
    fiber.add_observer_unsafe(lambda _: observed.append(2))
    fiber.interrupt_as_unsafe(None)
    assert observed == [1, 2]


@testing.effect
def test_stops_notifying_an_observer_once_it_is_removed():
    """stops notifying an observer once it is removed"""
    fiber = yield from fx.never.fork_daemon()
    observed: list[int] = []
    cancels = [fiber.add_observer_unsafe(lambda _, i=i: observed.append(i)) for i in range(3)]
    cancels[1]()
    cancels[1]()
    fiber.interrupt_as_unsafe(None)
    assert observed == [0, 2]


# --- joinAll --------------------------------------------------------------------------------


@testing.effect
def test_join_all_leaves_other_joins_running_when_one_is_interrupted():
    """leaves other joins running when one is interrupted"""
    latch = yield from fx.Latch.make()
    fibers = yield from fx.for_each(
        [1, 2], lambda n: latch.wait().as_(n).fork(start_immediately=True)
    )
    interrupted = yield from fx.Fiber.join_all(fibers).fork(start_immediately=True)
    kept = yield from fx.Fiber.join_all(fibers).fork(start_immediately=True)
    yield from interrupted.interrupt()
    yield from latch.open()
    assert (yield from kept.join()) == [1, 2]


@testing.effect
def test_join_all_cleans_up_observers_on_interruption():
    """cleans up observers on interruption"""
    fibers = yield from fx.for_each([0, 1], lambda _: fx.never.fork())

    def observer_counts() -> list[int]:
        return [len(f._observers) for f in fibers]  # pyright: ignore[reportPrivateUsage]

    before = observer_counts()
    join_fiber = yield from fx.Fiber.join_all(fibers).fork(start_immediately=True)
    assert observer_counts() == [count + 1 for count in before]
    yield from join_fiber.interrupt()
    assert observer_counts() == before


# --- interruptAll / interruptAllAs ----------------------------------------------------------


def _cleanup_waits_for(latch: fx.Latch, cleaned: list[bool]) -> fx.Effect[Never]:
    return fx.never.on_interrupt(latch.wait().and_then(fx.sync(lambda: cleaned.append(True))))


@testing.effect
def test_interrupt_all_awaits_fibers_passed_as_a_one_shot_iterable():
    """interruptAll awaits fibers passed as a one-shot iterable"""
    cleaned: list[bool] = []
    latch = yield from fx.Latch.make()
    fiber = yield from _cleanup_waits_for(latch, cleaned).fork(start_immediately=True)
    yield from latch.open().fork()
    yield from fx.Fiber.interrupt_all(f for f in [fiber])
    assert cleaned == [True]


@testing.effect
def test_interrupt_all_as_awaits_fibers_passed_as_a_one_shot_iterable():
    """interruptAllAs awaits fibers passed as a one-shot iterable"""
    cleaned: list[bool] = []
    latch = yield from fx.Latch.make()
    fiber = yield from _cleanup_waits_for(latch, cleaned).fork(start_immediately=True)
    yield from latch.open().fork()
    yield from fx.Fiber.interrupt_all_as((f for f in [fiber]), 0)
    assert cleaned == [True]
    exit_ = fiber.poll_unsafe()
    assert isinstance(exit_, fx.Failure) and exit_.cause.interruptors == frozenset({0})


# --- interruption delivery ------------------------------------------------------------------


@testing.effect
def test_delivers_a_synchronous_self_interrupt_instead_of_completing_to_success():
    """delivers a synchronous self-interrupt instead of completing to success"""

    def interrupt_self() -> int:
        current = fx.Fiber.get_current()
        assert current is not None
        current.interrupt_as_unsafe(None)
        return 42

    child = yield from fx.sync(interrupt_self).fork(start_immediately=True)
    assert _interrupted((yield from child.await_exit()))


@testing.effect
def test_runs_an_async_interrupt_finalizer_exactly_once_in_order():
    """runs an async interrupt finalizer exactly once, in order"""
    events: list[str] = []

    def acquire() -> fx.Effect[None]:
        current = fx.Fiber.get_current()
        assert current is not None
        current.interrupt_as_unsafe(None)
        events.append("acquired")
        return fx.void

    finalizer = (
        fx.sync(lambda: events.append("finalizer-start"))
        .and_then(fx.yield_now())
        .and_then(fx.sync(lambda: events.append("finalizer-end")))
    )

    @fx.gen
    def child_body():
        yield from fx.suspend(acquire).on_interrupt(finalizer)
        events.append("unreachable")

    child = yield from child_body.fork(start_immediately=True)
    ex = yield from child.await_exit()
    events.append("awaited")
    assert _interrupted(ex)
    assert events == ["acquired", "finalizer-start", "finalizer-end", "awaited"]


def test_get_current_is_none_outside_a_fiber():
    assert fx.Fiber.get_current() is None
    fiber = fx.run_blocking(fx.sync(fx.Fiber.get_current).fork().flat_map(lambda f: f.join()))
    assert isinstance(fiber, fx.Fiber)


@testing.effect
def test_retains_distinct_target_and_interruptor_stack_frames():
    """retains distinct target and interruptor stack frames"""
    target_frame = StackFrame("target-frame", lambda: "at target-call-site.py:1", None)
    interruptor_frame = StackFrame(
        "interruptor-frame", lambda: "at interruptor-call-site.py:2", None
    )
    target = yield from fx.never.pipe(fx.provide_service(CurrentStackFrame, target_frame)).fork(
        start_immediately=True
    )

    yield from target.interrupt().pipe(fx.provide_service(CurrentStackFrame, interruptor_frame))

    ex = yield from target.await_exit()
    assert isinstance(ex, fx.Failure)
    annotations = fx.cause.reason_annotations(ex.cause.reasons[0])
    assert annotations.get_unsafe(StackTrace) is target_frame
    assert annotations.get_unsafe(InterruptorStackTrace) is interruptor_frame
    assert "interruptor-call-site.py:2" in ex.cause.pretty()
