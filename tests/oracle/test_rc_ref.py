"""Ports of Effect's ``RcRef.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)``, ``forkChild({ startImmediately })``
is ``fork(start_immediately=True)`` and durations are seconds. Effect pins
some interleavings with one ``MaxOpsBeforeYield`` budget; pyfect's op
counts differ, so those ports sweep a range of budgets, which places a
yield at every step.
"""

from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die
from pyfect.duration import Seconds


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


class _Counter:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self) -> int:
        self.acquired += 1
        return self.acquired

    def release(self) -> None:
        self.released += 1

    def gated(self, gate: fx.Deferred[None]) -> fx.Effect[int, Never, fx.Scope]:
        """``resource``, acquired once ``gate`` opens."""
        return fx.acquire_release(
            gate.wait().map(lambda _: self.acquire()), lambda _a, _e: fx.sync(self.release)
        )

    def resource(self) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.sync(self.acquire), lambda _a, _e: fx.sync(self.release))


def _in[A, E](scope: fx.CloseableScope, eff: fx.Effect[A, E, fx.Scope]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.Scope, scope))


@testing.effect
def test_deallocation():
    """deallocation"""
    counter = _Counter()
    ref_scope = fx.CloseableScope()
    ref = yield from _in(ref_scope, fx.RcRef.make(counter.resource().as_("foo")))

    assert counter.acquired == 0
    assert (yield from fx.scoped(ref.get())) == "foo"
    assert (counter.acquired, counter.released) == (1, 1)

    scope_a = fx.CloseableScope()
    scope_b = fx.CloseableScope()
    yield from _in(scope_a, ref.get())
    yield from _in(scope_b, ref.get())
    assert (counter.acquired, counter.released) == (2, 1)
    yield from scope_b.close(fx.Success(None))
    assert (counter.acquired, counter.released) == (2, 1)
    yield from scope_a.close(fx.Success(None))
    assert (counter.acquired, counter.released) == (2, 2)

    scope_c = fx.CloseableScope()
    yield from _in(scope_c, ref.get())
    assert (counter.acquired, counter.released) == (3, 2)

    yield from ref_scope.close(fx.Success(None))
    assert (counter.acquired, counter.released) == (3, 3)

    assert _interrupted((yield from fx.scoped(ref.get()).exit()))


@testing.effect
def test_releasing_an_invalidated_borrower_preserves_the_replacement_resource():
    """releasing an invalidated borrower preserves the replacement resource"""
    counter = _Counter()
    released: list[int] = []
    owner, scope_a, scope_b, scope_c = (fx.CloseableScope() for _ in range(4))
    ref = yield from _in(
        owner,
        fx.RcRef.make(
            fx.acquire_release(
                fx.sync(counter.acquire), lambda n, _: fx.sync(lambda: released.append(n))
            )
        ),
    )

    first = yield from _in(scope_a, ref.get())
    yield from ref.invalidate()
    replacement = yield from _in(scope_b, ref.get())
    yield from scope_a.close(fx.Success(None))
    following = yield from _in(scope_c, ref.get())
    yield from owner.close(fx.Success(None))
    released_at_owner_close = list(released)
    yield from scope_b.close(fx.Success(None))
    yield from scope_c.close(fx.Success(None))

    assert (first, replacement, following) == (1, 2, 2)
    assert released_at_owner_close == [1, 2]
    assert released == [1, 2]


@testing.effect
def test_releasing_a_borrower_after_owner_shutdown_does_not_reopen_the_reference():
    """releasing a borrower after owner shutdown does not reopen the reference"""
    counter = _Counter()
    owner = fx.CloseableScope()
    borrower = fx.CloseableScope()
    ref = yield from _in(owner, fx.RcRef.make(fx.sync(counter.acquire)))

    yield from _in(borrower, ref.get())
    yield from owner.close(fx.Success(None))
    yield from borrower.close(fx.Success(None))
    ex = yield from fx.scoped(ref.get()).exit()

    assert _interrupted(ex)
    assert counter.acquired == 1


@testing.effect
def test_acquisition_completing_after_owner_shutdown_cannot_reopen_the_reference():
    """acquisition completing after owner shutdown cannot reopen the reference"""
    owner = fx.CloseableScope()
    borrower = fx.CloseableScope()
    started = yield from fx.Deferred[None].make()
    finish = yield from fx.Deferred[None].make()
    released: list[int] = []

    @fx.gen
    def acquire():
        value = yield from fx.acquire_release(
            fx.succeed(1), lambda v, _: fx.sync(lambda: released.append(v))
        )
        yield from started.succeed(None)
        yield from finish.wait()
        return value

    ref = yield from _in(owner, fx.RcRef.make(acquire))
    pending = yield from _in(borrower, ref.get()).fork(start_immediately=True)
    yield from started.wait()
    queued = yield from _in(borrower, ref.get()).fork(start_immediately=True)

    yield from owner.close(fx.Success(None))
    before = yield from fx.scoped(ref.get()).exit()
    yield from finish.succeed(None)
    pending_exit = yield from pending.await_exit()
    queued_exit = yield from queued.await_exit()
    after = yield from fx.scoped(ref.get()).exit()
    released_before_borrower_close = list(released)
    yield from borrower.close(fx.Success(None))

    assert _interrupted(before)
    assert _interrupted(pending_exit)
    assert _interrupted(queued_exit)
    assert _interrupted(after)
    assert released_before_borrower_close == [1]
    assert released == [1]


@testing.effect
def test_releases_resources_acquired_before_acquisition_failure():
    """releases resources acquired before acquisition failure"""
    counter = _Counter()
    ref_scope = fx.CloseableScope()
    borrower_scope = fx.CloseableScope()
    ref = yield from _in(ref_scope, fx.RcRef.make(counter.resource().and_then(fx.fail("boom"))))

    get_exit = yield from _in(borrower_scope, ref.get()).exit()
    borrower_close_exit = yield from borrower_scope.close(fx.Success(None)).exit()
    ref_close_exit = yield from ref_scope.close(fx.Success(None)).exit()

    assert get_exit == fx.exit.fail("boom")
    assert borrower_close_exit == fx.Success(None)
    assert ref_close_exit == fx.Success(None)
    assert (counter.acquired, counter.released) == (1, 1)


@testing.effect
def test_shares_one_generation_between_concurrent_first_borrowers():
    """shares one generation between concurrent first borrowers"""
    counter = _Counter()
    first_started = yield from fx.Deferred[None].make()
    release_first = yield from fx.Deferred[None].make()
    ref_scope, scope_a, scope_b = (fx.CloseableScope() for _ in range(3))

    @fx.gen
    def make_generation():
        generation = {"id": counter.acquire()}
        if generation["id"] == 1:
            yield from first_started.succeed(None)
            yield from release_first.wait()
        return generation

    ref = yield from _in(
        ref_scope,
        fx.RcRef.make(fx.acquire_release(make_generation, lambda _a, _e: fx.sync(counter.release))),
    )

    fiber_a = yield from _in(scope_a, ref.get()).fork(start_immediately=True)
    yield from first_started.wait()
    fiber_b = yield from _in(scope_b, ref.get()).fork(start_immediately=True)
    yield from release_first.succeed(None)

    exit_a = yield from fiber_a.await_exit()
    exit_b = yield from fiber_b.await_exit()
    generation_a = yield from fiber_a.join()
    generation_b = yield from fiber_b.join()
    close_a = yield from scope_a.close(fx.Success(None)).exit()
    close_b = yield from scope_b.close(fx.Success(None)).exit()
    ref_close = yield from ref_scope.close(fx.Success(None)).exit()

    assert exit_a == fx.Success(generation_a)
    assert exit_b == fx.Success(generation_a)
    assert generation_a is generation_b
    assert close_a == close_b == ref_close == fx.Success(None)
    assert (counter.acquired, counter.released) == (1, 1)


@testing.effect
def test_idle_time_to_live_reuses_and_releases_resources():
    """idleTimeToLive reuses and releases resources"""
    counter = _Counter()
    ref = yield from fx.RcRef.make(counter.resource().as_("foo"), idle_time_to_live="10 millis")

    assert counter.acquired == 0
    assert (yield from fx.scoped(ref.get())) == "foo"
    assert (counter.acquired, counter.released) == (1, 0)

    yield from testing.adjust("5 millis")
    assert (yield from fx.scoped(ref.get())) == "foo"
    assert (counter.acquired, counter.released) == (1, 0)

    yield from testing.adjust("9 millis")
    assert counter.released == 0
    yield from testing.adjust("1 millis")
    assert counter.released == 1

    assert (yield from fx.scoped(ref.get())) == "foo"
    assert (counter.acquired, counter.released) == (2, 1)

    yield from testing.adjust("10 millis")
    assert counter.released == 2


class _RecordingClock:
    def __init__(self, inner: fx.clock.ClockService) -> None:
        self.inner = inner
        self.sleeps: list[float] = []

    def current_time_millis_unsafe(self) -> float:
        return self.inner.current_time_millis_unsafe()

    def monotonic_unsafe(self) -> float:
        return self.inner.monotonic_unsafe()

    def now_nanos_unsafe(self) -> int:
        return self.inner.now_nanos_unsafe()

    def monotonic_nanos_unsafe(self) -> int:
        return self.inner.monotonic_nanos_unsafe()

    def sleep(self, seconds: Seconds) -> fx.Effect[None]:
        self.sleeps.append(seconds)
        return self.inner.sleep(seconds)


@testing.effect
def test_idle_time_to_live_0_releases_resources_after_a_zero_duration_sleep():
    """idleTimeToLive 0 releases resources after a zero-duration sleep"""
    clock = _RecordingClock((yield from fx.Clock()))
    counter = _Counter()
    ref = yield from fx.RcRef.make(counter.resource(), idle_time_to_live=0).pipe(
        fx.provide_service(fx.Clock, clock)
    )

    yield from fx.scoped(ref.get())
    assert clock.sleeps == [0]
    assert counter.released == 1


@testing.effect
def test_an_interrupted_first_get_does_not_pin_the_resource():
    """an interrupted first get does not pin the resource"""
    for ops in range(1, 64):
        counter = _Counter()
        ref = yield from fx.RcRef.make(counter.resource())
        fiber = yield from (
            fx.scoped(ref.get())
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
            .fork(start_immediately=True)
        )
        yield from fiber.interrupt()
        yield from fx.scoped(ref.get())
        assert counter.acquired == counter.released, f"{ops} ops"


@testing.effect
def test_an_interrupted_get_of_an_acquired_resource_does_not_pin_it():
    """an interrupted get of an acquired resource does not pin it"""
    for ops in range(1, 64):
        counter = _Counter()
        ref = yield from fx.RcRef.make(counter.resource())
        holder = yield from fx.scoped(ref.get().and_then(fx.never)).fork(start_immediately=True)
        fiber = yield from (
            fx.scoped(ref.get())
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
            .fork(start_immediately=True)
        )
        yield from fiber.interrupt()
        yield from holder.interrupt()
        assert counter.released == 1, f"{ops} ops"


@testing.effect
def test_invalidating_a_resource_while_a_get_revives_it_releases_the_resource():
    """invalidating a resource while a get revives it releases the resource"""
    for ops in range(1, 64):
        counter = _Counter()
        ref = yield from fx.RcRef.make(counter.resource(), idle_time_to_live="1 minute").pipe(
            fx.provide_service(fx.MaxOpsBeforeYield, ops)
        )
        yield from fx.scoped(ref.get())
        getter = yield from fx.scoped(ref.get()).fork(start_immediately=True)
        yield from ref.invalidate()
        yield from getter.join()
        assert counter.released == 1, f"{ops} ops"


@testing.effect
def test_closing_the_ref_while_an_idle_resource_is_being_released_runs_every_finalizer():
    """closing the ref while an idle resource is being released runs every finalizer"""
    gate = yield from fx.Deferred[None].make()
    counter = _Counter()
    scope = fx.CloseableScope()

    @fx.gen
    def acquire():
        yield from fx.add_finalizer(lambda _: fx.sync(counter.release))
        yield from fx.add_finalizer(lambda _: gate.wait().and_then(fx.sync(counter.release)))

    ref = yield from _in(scope, fx.RcRef.make(acquire, idle_time_to_live="1 second"))
    yield from fx.scoped(ref.get())
    yield from testing.adjust("1 second")
    closing = yield from scope.close(fx.Success(None)).fork(start_immediately=True)
    yield from gate.succeed(None)
    yield from closing.join()
    assert counter.released == 2


@testing.effect
def test_shares_an_acquisition_until_every_get_is_interrupted_then_starts_fresh():
    """shares an acquisition until every get is interrupted, then starts fresh"""
    acquired = 0
    started = yield from fx.Deferred[None].make()
    finalizing = yield from fx.Deferred[None].make()
    finish_finalizer = yield from fx.Deferred[None].make()

    def acquire() -> fx.Effect[int]:
        nonlocal acquired
        acquired += 1
        if acquired > 1:
            return fx.succeed(acquired)
        return (
            started.succeed(None)
            .and_then(fx.never)
            .on_interrupt(finalizing.succeed(None).and_then(finish_finalizer.wait()))
        )

    ref = yield from fx.RcRef.make(fx.suspend(acquire))

    first = yield from fx.scoped(ref.get()).fork(start_immediately=True)
    yield from started.wait()
    second = yield from fx.scoped(ref.get()).fork(start_immediately=True)
    yield from first.interrupt()
    assert not (yield from finalizing.is_done())

    # A get made while the abandoned acquisition finalizes starts a fresh one.
    interrupt_second = yield from second.interrupt().fork(start_immediately=True)
    yield from finalizing.wait()
    fresh = yield from fx.scoped(ref.get()).fork(start_immediately=True)
    yield from finish_finalizer.succeed(None)
    yield from interrupt_second.join()
    assert (yield from fresh.await_exit()) == fx.Success(2)


@pytest.mark.parametrize("interrupt_all", [False, True])
@testing.effect
def test_releases_references_of_waiters_interrupted_after_the_acquisition_publishes_them(
    interrupt_all: bool,
):
    """releases references of waiters interrupted after the acquisition publishes them
    (interrupt all: %s)"""
    # Sweep the op budget so the acquisition yields at every step between
    # publishing its references and its fiber completing.
    for ops in range(1, 65):
        counter = _Counter()
        gate = yield from fx.Deferred[None].make()
        ref = yield from fx.RcRef.make(counter.gated(gate))

        def with_budget[A, E](eff: fx.Effect[A, E], n: int = ops) -> fx.Effect[A, E]:
            return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, n))

        holder_scope = fx.CloseableScope()
        holder = yield from with_budget(_in(holder_scope, ref.get())).fork(start_immediately=True)
        waiter = yield from with_budget(fx.scoped(ref.get())).fork(start_immediately=True)
        for _ in range(200):
            yield from fx.yield_now()
        yield from gate.succeed(None)
        yield from waiter.interrupt()
        if interrupt_all:
            yield from holder.interrupt()
        yield from holder.await_exit()
        yield from holder_scope.close(fx.Success(None))

        assert (counter.acquired, counter.released) == (1, 1), f"{ops} ops"
        assert (yield from fx.scoped(ref.get())) == 2, f"{ops} ops"


@testing.effect
def test_closing_the_ref_interrupts_a_pending_acquisition_and_closes_its_scope():
    """closing the ref interrupts a pending acquisition and closes its scope"""
    counter = _Counter()
    started = yield from fx.Deferred[None].make()
    ref_scope = fx.CloseableScope()

    @fx.gen
    def acquire():
        yield from fx.add_finalizer(lambda _: fx.sync(counter.release))
        yield from started.succeed(None)
        return (yield from fx.never)

    ref = yield from _in(ref_scope, fx.RcRef.make(acquire))
    getter = yield from fx.scoped(ref.get()).fork(start_immediately=True)
    yield from started.wait()
    yield from ref_scope.close(fx.Success(None))

    assert counter.released == 1
    assert _interrupted((yield from getter.await_exit()))


# --- Effect 4.1.2: background release defects at UnhandledLogLevel ---------------


def _logged_defects(logged: list[fx.logger.Options]) -> list[tuple[fx.LogLevel, list[str]]]:
    return [
        (event.log_level, [str(r.defect) for r in event.cause.reasons if isinstance(r, Die)])
        for event in logged
    ]


def _capturing_warn[A, E](
    logged: list[fx.logger.Options], eff: fx.Effect[A, E, Any]
) -> fx.Effect[A, E, Any]:
    capture = fx.Logger.make(logged.append)
    return eff.pipe(fx.provide(fx.logger.layer([capture]))).pipe(
        fx.provide_service(fx.UnhandledLogLevel, fx.LogLevel.WARN)
    )


def _dying_release(released: list[str], key: str) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(
        fx.succeed(key),
        lambda _a, _e: fx.sync(lambda: released.append(key)).and_then(
            fx.die(Exception(f"release {key}"))
        ),
    )


@testing.effect
def test_reports_idle_expiry_defects_at_unhandled_log_level():
    """reports idle expiry defects at UnhandledLogLevel"""
    logged: list[fx.logger.Options] = []

    @fx.gen
    def body():
        released: list[str] = []
        ref = yield from fx.RcRef.make(_dying_release(released, "a"), idle_time_to_live="1 second")
        yield from fx.scoped(ref.get())
        yield from testing.adjust("1 second")
        assert released == ["a"]
        assert _logged_defects(logged) == [(fx.LogLevel.WARN, ["release a"])]

    yield from _capturing_warn(logged, body)
