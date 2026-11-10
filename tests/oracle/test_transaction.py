"""Ports of the ``transaction (composable transactions)`` block of Effect's
``Effect.test.ts``. Effect v4.0.6 has no ``TxRef.test.ts``; ``TxRef`` is
covered here and in ``tests/test_transaction.py``.

Each test's docstring is the Effect test title. Effect's metadata times are
milliseconds; pyfect's are seconds, as in schedule metadata.
"""

import math
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import testing


def _yield_times(n: int) -> fx.Effect[None]:
    return fx.yield_now().repeat(times=n).as_void()


# --- basic behavior -----------------------------------------------------------


@testing.effect
def test_should_create_transaction_boundaries_when_no_transaction_is_active():
    """should create transaction boundaries when no transaction is active"""
    ref1 = fx.TxRef(0)
    ref2 = fx.TxRef(100)

    yield from fx.tx(ref1.set(10))
    yield from fx.tx(ref2.set(200))

    assert (yield from fx.tx(ref1.get())) == 10
    assert (yield from fx.tx(ref2.get())) == 200


@testing.effect
def test_should_publish_child_transaction_writes_after_the_enclosing_transaction_completes():
    """should publish child transaction writes after the enclosing transaction completes"""
    ref = fx.TxRef(0)
    gate = yield from fx.Deferred[None].make()
    child = yield from fx.tx(gate.wait().and_then(fx.tx(ref.set(42))).fork())

    yield from gate.succeed(None)
    yield from child.join()

    assert (yield from ref.get()) == 42


@testing.effect
def test_should_allow_tx_ref_modify_outside_an_existing_transaction():
    """should allow TxRef.modify outside an existing transaction"""
    ref = fx.TxRef(0)

    result = yield from ref.modify(lambda current: (current + 1, current + 10))
    value = yield from fx.tx(ref.get())

    assert result == 1
    assert value == 10


@testing.effect
def test_should_roll_back_nested_changes_when_the_outer_transaction_fails():
    """should roll back nested changes when the outer transaction fails"""
    ref1 = fx.TxRef(0)
    ref2 = fx.TxRef(100)

    @fx.fn
    def body():
        yield from ref1.set(10)
        yield from fx.tx(ref2.set(200))
        return (yield from fx.fail("parent failed"))

    parent_error = yield from fx.tx(body()).flip()

    assert parent_error == "parent failed"
    assert (yield from fx.tx(ref1.get())) == 0
    assert (yield from fx.tx(ref2.get())) == 100


@testing.effect
def test_should_allow_catching_nested_failures_in_the_same_transaction():
    """should allow catching nested failures in the same transaction"""
    ref1 = fx.TxRef(0)
    ref2 = fx.TxRef(100)

    @fx.fn
    def child():
        yield from ref2.set(200)
        return (yield from fx.fail("child failed"))

    @fx.fn
    def body():
        yield from ref1.set(10)
        child_result = yield from fx.tx(child()).result()
        yield from ref1.set(20)
        assert isinstance(child_result, fx.Err)

    yield from fx.tx(body())

    assert (yield from fx.tx(ref1.get())) == 20
    assert (yield from fx.tx(ref2.get())) == 200


# --- transaction nesting ------------------------------------------------------


@testing.effect
def test_should_handle_multiple_levels_of_nested_composed_transactions():
    """should handle multiple levels of nested composed transactions"""
    ref1 = fx.TxRef(0)
    ref2 = fx.TxRef(0)
    ref3 = fx.TxRef(0)

    @fx.fn
    def inner():
        yield from ref2.set(2)
        yield from fx.tx(ref3.set(3))

    @fx.fn
    def outer():
        yield from ref1.set(1)
        yield from fx.tx(inner())

    yield from fx.tx(outer())

    assert (yield from fx.tx(ref1.get())) == 1
    assert (yield from fx.tx(ref2.get())) == 2
    assert (yield from fx.tx(ref3.get())) == 3


# --- transaction composition behavior ------------------------------------------


@testing.effect
def test_should_compose_nested_tx_calls_into_the_same_transaction():
    """should compose nested tx calls into the same transaction"""
    ref1 = fx.TxRef(0)
    ref2 = fx.TxRef(0)

    @fx.fn
    def body():
        yield from ref1.set(10)
        yield from fx.tx(ref2.set(20))

    yield from fx.tx(body())

    assert (yield from fx.tx(ref1.get())) == 10
    assert (yield from fx.tx(ref2.get())) == 20


@testing.effect
def test_should_rollback_the_entire_composed_transaction_on_failure():
    """should rollback the entire composed transaction on failure"""
    ref = fx.TxRef(0)

    @fx.fn
    def nested():
        yield from ref.set(20)
        return (yield from fx.fail("nested failure"))

    @fx.fn
    def body():
        yield from ref.set(10)
        return (yield from fx.tx(nested()))

    tx_error = yield from fx.tx(body()).flip()

    assert tx_error == "nested failure"
    assert (yield from fx.tx(ref.get())) == 0


@testing.effect
def test_should_preserve_nested_writes_when_nested_failure_is_caught():
    """should preserve nested writes when nested failure is caught"""
    ref = fx.TxRef(0)

    @fx.fn
    def nested():
        yield from ref.set(20)
        return (yield from fx.fail("transaction nested failure"))

    @fx.fn
    def body():
        yield from ref.set(10)
        child_error = yield from fx.tx(nested()).flip()
        assert child_error == "transaction nested failure"

    yield from fx.tx(body())

    assert (yield from fx.tx(ref.get())) == 20


# --- retry --------------------------------------------------------------------


@testing.effect
def test_should_preserve_a_retry_cleanup_failure_when_a_read_ref_changes_during_cleanup():
    """should preserve a retry cleanup failure when a read ref changes during cleanup"""
    ref = fx.TxRef(0)
    cleaning = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()

    def cleanup(_: fx.Exit[Any, Any]) -> fx.Effect[None, str]:
        return cleaning.succeed(None).and_then(release.wait()).and_then(fx.fail("release-error"))

    @fx.fn
    def body():
        if (yield from ref.get()) != 0:
            return
        return (yield from fx.tx_retry.on_exit_if(lambda _: True, cleanup))

    transaction = yield from fx.tx(body()).fork()

    yield from cleaning.wait()
    yield from fx.tx(ref.set(1))
    yield from release.succeed(None)

    error = yield from transaction.join().flip()
    assert error == "release-error"


@testing.effect
def test_should_rerun_when_a_read_ref_changed_while_the_transaction_was_suspended():
    """should rerun when a read ref changed while the transaction was suspended"""
    ref = fx.TxRef(0)
    read = yield from fx.Deferred[None].make()
    committed = yield from fx.Deferred[None].make()

    @fx.fn
    def body():
        value = yield from ref.get()
        if value == 0:
            yield from read.succeed(None)
            yield from committed.wait()
            return (yield from fx.tx_retry)
        return value

    transaction = yield from fx.tx(body()).fork()

    yield from read.wait()
    yield from fx.tx(ref.set(1))
    yield from committed.succeed(None)

    joined = yield from transaction.join().timeout_option("1 second").fork()
    yield from testing.adjust("1 second")

    assert (yield from joined.join()) == fx.Some(1)


@testing.effect
def test_commits_wake_the_waiters_of_refs_they_write_not_refs_they_read():
    """commits wake the waiters of refs they write, not refs they read"""
    gate = fx.TxRef(0)
    other = fx.TxRef(0)
    runs = 0

    @fx.fn
    def wait_for_gate():
        nonlocal runs
        runs += 1
        value = yield from gate.get()
        if value == 0:
            return (yield from fx.tx_retry)
        return value

    waiter = yield from fx.tx(wait_for_gate()).fork(start_immediately=True)

    @fx.fn
    def read_gate_write_other():
        yield from gate.get()
        yield from other.set(1)

    yield from fx.tx(read_gate_write_other())
    yield from _yield_times(10)
    assert runs == 1, "reading a ref should not wake its waiters"

    yield from fx.tx(gate.set(0))
    yield from _yield_times(10)
    assert runs == 2, "writing the same value should wake its waiters"

    yield from fx.tx(gate.set(1))
    assert (yield from waiter.join()) == 1


@testing.effect
def test_a_write_of_negative_zero_over_zero_is_published_and_wakes_its_waiters():
    """a write of -0 over 0 is published and wakes its waiters"""
    zero = fx.TxRef(0.0)

    @fx.fn
    def body():
        value = yield from zero.get()
        if value == 0 and math.copysign(1.0, value) > 0:
            return (yield from fx.tx_retry)
        return math.copysign(math.inf, value)

    negative_zero = yield from fx.tx(body()).fork(start_immediately=True)
    yield from fx.tx(zero.set(-0.0))

    yield from _yield_times(10)
    assert negative_zero.poll_unsafe() == fx.Success(-math.inf), "-0 over 0 never woke its waiter"


# --- transaction metadata -----------------------------------------------------


class _AdvancingClock:
    """A clock whose wall time moves one millisecond on every read."""

    def __init__(self, base: fx.clock.ClockService) -> None:
        self._base = base
        self._ms = 1000

    def now_nanos_unsafe(self) -> int:
        self._ms += 1
        return (self._ms - 1) * 1_000_000

    def current_time_millis_unsafe(self) -> float:
        return self.now_nanos_unsafe() / 1_000_000

    def monotonic_unsafe(self) -> float:
        return self._base.monotonic_unsafe()

    def monotonic_nanos_unsafe(self) -> int:
        return self._base.monotonic_nanos_unsafe()

    def sleep(self, seconds: fx.duration.Duration) -> fx.Effect[None]:
        return self._base.sleep(seconds)


@testing.effect
def test_starts_with_zero_durations_when_the_clock_advances_between_reads():
    """starts with zero durations when the clock advances between reads"""
    base = yield from fx.Clock()

    @fx.fn
    def body():
        metadata = yield from fx.Transaction()
        assert (metadata.elapsed, metadata.elapsed_since_previous) == (0, 0)
        assert metadata.start == metadata.now

    yield from fx.tx(body()).pipe(fx.provide_service(fx.Clock, _AdvancingClock(base)))


@dataclass(frozen=True)
class _Snapshot:
    attempt: int
    retry_reason: fx.transaction.TransactionRetryReason | None
    start: float
    now: float
    elapsed: float
    elapsed_since_previous: float
    nested_same: bool


@testing.effect
def test_tracks_nested_metadata_across_retries_and_conflicts():
    """tracks nested metadata across retries and conflicts"""
    ref = fx.TxRef(0)
    started = yield from fx.Deferred[None].make()
    ready_for_conflict = yield from fx.Deferred[None].make()
    resume = yield from fx.Deferred[None].make()
    snapshots: list[_Snapshot] = []

    @fx.fn
    def inner(outer: fx.transaction.TransactionMeta):
        meta = yield from fx.Transaction()
        return meta is outer

    @fx.fn
    def body():
        outer = yield from fx.Transaction()
        nested_same = yield from fx.tx(inner(outer))
        snapshots.append(
            _Snapshot(
                attempt=outer.attempt,
                retry_reason=outer.retry_reason,
                start=outer.start,
                now=outer.now,
                elapsed=outer.elapsed,
                elapsed_since_previous=outer.elapsed_since_previous,
                nested_same=nested_same,
            )
        )
        yield from ref.get()
        if outer.attempt == 1:
            yield from started.succeed(None)
            return (yield from fx.tx_retry)
        if outer.attempt == 2:
            yield from ready_for_conflict.succeed(None)
            yield from resume.wait()

    fiber = yield from fx.tx(body()).fork()

    yield from started.wait()
    yield from testing.adjust("1 second")
    yield from ref.set(1)
    yield from ready_for_conflict.wait()
    yield from testing.adjust("500 millis")
    yield from ref.set(2)
    yield from resume.succeed(None)
    yield from fiber.join()

    assert snapshots == [
        _Snapshot(1, None, 0, 0, 0, 0, nested_same=True),
        _Snapshot(2, "retry", 0, 1_000, 1_000, 1_000, nested_same=True),
        _Snapshot(3, "conflict", 0, 1_500, 1_500, 500, nested_same=True),
    ]
