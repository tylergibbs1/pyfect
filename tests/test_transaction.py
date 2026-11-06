"""pyfect-specific transaction behavior: interruption, conflicts under
contention, defects, and the ``TxRef`` surface."""

# pyright: reportPrivateUsage=false

import threading
import time

import pyfect as fx
from pyfect import testing


@testing.effect
def test_concurrent_increments_all_commit():
    ref = fx.TxRef(0)

    @fx.fn
    def increment():
        value = yield from ref.get()
        yield from fx.yield_now()
        yield from ref.set(value + 1)

    yield from fx.for_each(range(50), lambda _: fx.tx(increment()), concurrency="unbounded")

    assert (yield from ref.get()) == 50


@testing.effect
def test_a_conflict_reruns_the_body_with_reason_conflict():
    ref = fx.TxRef(0)
    reasons: list[fx.transaction.TransactionRetryReason | None] = []
    paused = yield from fx.Deferred[None].make()
    proceed = yield from fx.Deferred[None].make()

    @fx.fn
    def body():
        meta = yield from fx.Transaction()
        reasons.append(meta.retry_reason)
        value = yield from ref.get()
        if meta.attempt == 1:
            yield from paused.succeed(None)
            yield from proceed.wait()
        yield from ref.set(value + 10)

    fiber = yield from fx.tx(body()).fork()
    yield from paused.wait()
    yield from ref.set(5)
    yield from proceed.succeed(None)
    yield from fiber.join()

    assert reasons == [None, "conflict"]
    assert (yield from ref.get()) == 15


@testing.effect
def test_interrupting_a_retrying_transaction_unregisters_its_waiter():
    ref = fx.TxRef(0)

    @fx.fn
    def body():
        if (yield from ref.get()) == 0:
            return (yield from fx.tx_retry)
        return "done"

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    assert len(ref._pending) == 1

    yield from fiber.interrupt()

    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only
    assert ref._pending == {}


@testing.effect
def test_an_interrupted_transaction_commits_nothing():
    ref = fx.TxRef(0)
    started = yield from fx.Deferred[None].make()

    @fx.fn
    def body():
        yield from ref.set(1)
        yield from started.succeed(None)
        yield from fx.never

    fiber = yield from fx.tx(body()).fork()
    yield from started.wait()
    yield from fiber.interrupt()

    assert (yield from ref.get()) == 0
    assert ref.version == 0


@testing.effect
def test_a_raising_update_is_a_defect_and_commits_nothing():
    ref = fx.TxRef(1)
    other = fx.TxRef("a")

    def boom(_: int) -> int:
        raise ValueError("boom")

    ex = yield from fx.tx(other.set("b").and_then(ref.update(boom))).exit()

    assert isinstance(ex, fx.Failure) and ex.cause.has_dies
    assert (yield from other.get()) == "a"


@testing.effect
def test_versions_count_changing_commits_only():
    ref = fx.TxRef(1)
    yield from ref.set(1)
    assert ref.version == 0
    yield from ref.set(2)
    assert ref.version == 1
    yield from ref.update(lambda n: n + 1)
    assert ref.version == 2
    assert (yield from ref.get()) == 3


@testing.effect
def test_the_journal_records_reads_and_writes():
    read = fx.TxRef(1)
    written = fx.TxRef(2)

    @fx.fn
    def body():
        yield from read.get()
        yield from written.set(3)
        meta = yield from fx.Transaction()
        return {
            ref: (entry.version, entry.value, entry.written) for ref, entry in meta.journal.items()
        }

    journal = yield from fx.tx(body())

    assert journal == {read: (0, 1, False), written: (0, 3, True)}


@testing.effect
def test_modify_returns_its_result_and_stores_the_new_value():
    ref = yield from fx.TxRef.make([1, 2])
    head = yield from ref.modify(lambda items: (items[0], items[1:]))
    assert head == 1
    assert (yield from ref.get()) == [2]


@testing.effect
def test_an_interrupt_in_the_step_that_wakes_a_retrying_transaction_wins():
    """Effect's commit schedules its wakes, so an interrupt sent in the
    committing step still finds the waiter parked (checked under Node)."""
    ref = fx.TxRef(0)
    runs = 0

    @fx.fn
    def body():
        nonlocal runs
        runs += 1
        if (yield from ref.get()) == 0:
            return (yield from fx.tx_retry)
        return "done"

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from fx.yield_now()
    yield from fx.tx(ref.set(1)).and_then(fiber.interrupt())

    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only
    assert runs == 1
    assert ref._pending == {}


def test_a_commit_in_another_run_wakes_a_retrying_transaction():
    """The wake goes to the waiter's scheduler: the committing run may end
    right after its commit and never run another task."""
    ref = fx.TxRef(0)

    @fx.fn
    def body():
        if (yield from ref.get()) == 0:
            return (yield from fx.tx_retry)
        return (yield from ref.get())

    results: list[int] = []
    waiter = threading.Thread(
        target=lambda: results.append(fx.run_blocking(fx.tx(body()))), daemon=True
    )
    waiter.start()
    while not ref._pending:
        time.sleep(0.001)
    fx.run_blocking(ref.set(5))
    waiter.join(5)

    assert results == [5]
