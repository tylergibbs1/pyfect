"""Ports of Effect's ``Semaphore.test.ts`` (which also tests
``PartitionedSemaphore``).

Each test's docstring is the Effect test title. Effect's module-level
functions are methods here; ``withPermits(n)(eff)`` is
``with_permits(eff, n)`` and the partitioned ``withPermits(key, n)(eff)`` is
``with_permits(key, eff, n)``.

Effect's tests that interrupt "at any operation" pause the fiber from a
custom ``shouldYield``. These ports sweep ``MaxOpsBeforeYield`` budgets, which
place the pause at every step; ``test_custom_dispatchers.py`` runs Effect's own
form.
"""

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.duration import seconds
from pyfect.scheduler import CurrentScheduler, MixedScheduler

from ._task_queue import TaskQueue


def _concurrently(*effects: fx.Effect[Any]) -> fx.Effect[None]:
    return fx.for_each(effects, lambda eff: eff, concurrency="unbounded").as_void()


def _with_budget[A, E](eff: fx.Effect[A, E], budget: int) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))


def _push(messages: list[str], message: str) -> fx.Effect[None]:
    return fx.sync(lambda: messages.append(message))


# --- PartitionedSemaphore -----------------------------------------------------------------


@testing.effect
def test_basic_single_partition_operation():
    """basic single partition operation"""
    sem = yield from fx.PartitionedSemaphore[str].make(4)
    messages: list[str] = []
    tasks = [
        sem.with_permits("partition-1", _push(messages, f"process: {n}").delay("2 seconds"), 2)
        for n in range(4)
    ]
    yield from _concurrently(*tasks).fork()

    yield from testing.adjust("3 seconds")
    assert len(messages) == 2

    yield from testing.adjust("3 seconds")
    assert len(messages) == 4


@testing.effect
def test_multiple_partitions_share_total_permits():
    """multiple partitions share total permits"""
    sem = yield from fx.PartitionedSemaphore[str].make(4)
    messages: list[str] = []
    yield from _concurrently(
        sem.with_permits("partition-1", _push(messages, "p1-task1").delay("2 seconds"), 2),
        sem.with_permits("partition-2", _push(messages, "p2-task1").delay("2 seconds"), 2),
        sem.with_permits("partition-1", _push(messages, "p1-task2").delay("2 seconds"), 2),
    ).fork()

    yield from testing.adjust("3 seconds")
    assert len(messages) == 2

    yield from testing.adjust("3 seconds")
    assert len(messages) == 3


@testing.effect
def test_round_robin_fairness_across_partitions():
    """round-robin fairness across partitions"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    messages: list[str] = []

    yield from sem.with_permits(
        "partition-1", _push(messages, "p1-initial").delay("2 seconds"), 2
    ).fork()
    yield from testing.adjust("1 millis")

    yield from _concurrently(
        *(sem.with_permits("partition-1", _push(messages, f"p1-task{i}")) for i in (1, 2, 3))
    ).fork()
    yield from testing.adjust("1 millis")

    yield from _concurrently(
        *(sem.with_permits("partition-2", _push(messages, f"p2-task{i}")) for i in (1, 2, 3))
    ).fork()
    yield from testing.adjust("3 seconds")

    assert messages == [
        "p1-initial",
        "p1-task1",
        "p2-task1",
        "p1-task2",
        "p2-task2",
        "p1-task3",
        "p2-task3",
    ]


@testing.effect
def test_requesting_more_permits_than_total_returns_never():
    """requesting more permits than total returns never"""
    sem = yield from fx.PartitionedSemaphore[str].make(4)
    fiber = yield from sem.with_permits("partition-1", fx.succeed(42), 5).fork()

    yield from testing.adjust("10 seconds")

    assert fiber.poll_unsafe() is None


@testing.effect
def test_single_permit_operations():
    """single permit operations"""
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    messages: list[str] = []
    yield from _concurrently(
        *(
            sem.with_permits("partition-1", _push(messages, f"task: {n}").delay("1 second"))
            for n in range(3)
        )
    ).fork()

    yield from testing.adjust("1500 millis")
    assert len(messages) == 1

    yield from testing.adjust("1 second")
    assert len(messages) == 2

    yield from testing.adjust("1 second")
    assert len(messages) == 3


@testing.effect
def test_different_permit_sizes_on_same_partition():
    """different permit sizes on same partition"""
    sem = yield from fx.PartitionedSemaphore[str].make(5)
    messages: list[str] = []
    yield from _concurrently(
        sem.with_permits("partition-1", _push(messages, "large").delay("2 seconds"), 3),
        sem.with_permits("partition-1", _push(messages, "small-1").delay("2 seconds"), 1),
        sem.with_permits("partition-1", _push(messages, "small-2").delay("2 seconds"), 1),
    ).fork()

    yield from testing.adjust("3 seconds")
    assert len(messages) == 3


@testing.effect
def test_interruption_releases_permits():
    """interruption releases permits"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    messages: list[str] = []
    fiber = yield from sem.with_permits(
        "partition-1", _push(messages, "long-task").delay("10 seconds"), 2
    ).fork()

    yield from testing.adjust("1 second")
    yield from fiber.interrupt()

    yield from sem.with_permits("partition-1", _push(messages, "after-interrupt"), 2)

    assert messages == ["after-interrupt"]


@testing.effect
def test_interruption_with_partial_permit_acquisition_releases_all_taken_permits():
    """interruption with partial permit acquisition releases all taken permits"""
    sem = yield from fx.PartitionedSemaphore[str].make(3)
    messages: list[str] = []

    fiber1 = yield from sem.with_permits(
        "partition-1", _push(messages, "first").delay("5 seconds"), 2
    ).fork()
    yield from testing.adjust("1 millis")

    fiber2 = yield from sem.with_permits("partition-2", _push(messages, "second"), 3).fork()
    yield from testing.adjust("1 millis")
    yield from fiber2.interrupt()

    yield from sem.with_permits("partition-3", _push(messages, "can-acquire-one"), 1)
    assert messages == ["can-acquire-one"]

    yield from testing.adjust("5 seconds")
    yield from fiber1.join()
    assert messages == ["can-acquire-one", "first"]

    yield from sem.with_permits("partition-4", _push(messages, "all-three"), 3)
    assert messages == ["can-acquire-one", "first", "all-three"]


@testing.effect
def test_exact_permit_match():
    """exact permit match"""
    sem = yield from fx.PartitionedSemaphore[str].make(4)
    messages: list[str] = []
    yield from _concurrently(
        sem.with_permits("partition-1", _push(messages, "exact-match").delay("2 seconds"), 4),
        sem.with_permits("partition-2", _push(messages, "waiting").delay("2 seconds"), 1),
    ).fork()

    yield from testing.adjust("3 seconds")
    assert messages == ["exact-match"]

    yield from testing.adjust("3 seconds")
    assert len(messages) == 2


@testing.effect
def test_many_partitions():
    """many partitions"""
    sem = yield from fx.PartitionedSemaphore[str].make(3)
    messages: list[str] = []
    yield from _concurrently(
        *(
            sem.with_permits(
                f"partition-{i % 5}", _push(messages, f"p{i % 5}-task").delay("1 second")
            )
            for i in range(10)
        )
    ).fork()

    for expected in (3, 6, 9, 10):
        yield from testing.adjust(seconds(1.5 if expected == 3 else 1))
        assert len(messages) == expected


@testing.effect
def test_partial_permit_allocation():
    """partial permit allocation"""
    sem = yield from fx.PartitionedSemaphore[str].make(3)
    messages: list[str] = []

    yield from sem.with_permits(
        "partition-1", _push(messages, "first").delay("2 seconds"), 2
    ).fork()
    yield from testing.adjust("100 millis")

    fiber = yield from sem.with_permits("partition-2", _push(messages, "second"), 2).fork()
    yield from testing.adjust("100 millis")

    assert fiber.poll_unsafe() is None
    assert messages == []

    yield from testing.adjust("3 seconds")
    assert messages == ["first", "second"]


@testing.effect
def test_zero_permits_requested():
    """zero permits requested"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    executed: list[bool] = []

    yield from sem.with_permits("partition-1", fx.sync(lambda: executed.append(True)), 0)

    assert executed == [True]


@testing.effect
def test_sequential_tasks_in_same_partition():
    """sequential tasks in same partition"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    messages: list[str] = []

    for i in (1, 2, 3):
        yield from sem.with_permits("partition-1", _push(messages, f"task-{i}"), 2)

    assert messages == ["task-1", "task-2", "task-3"]


# --- Semaphore ----------------------------------------------------------------------------


@testing.effect
def test_take_interruption_does_not_leak_permits():
    """take interruption does not leak permits"""
    # Effect's form, pausing the woken waiter from ``shouldYield``, is in
    # ``test_custom_dispatchers.py``. Here the waiter is interrupted after the
    # release counted the permit for it but before the wake task runs.
    queue = TaskQueue()
    sem = yield from fx.Semaphore.make(0)
    waiter = yield from queue.provide(sem.take(1)).fork()
    yield from fx.yield_now()
    yield from queue.run_all()

    yield from queue.provide(sem.release(1))
    assert waiter.poll_unsafe() is None

    waiter.interrupt_as_unsafe(None)
    yield from queue.run_all()
    ex = yield from waiter.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts

    assert (yield from sem.with_permits_if_available(fx.void)) is not None


@testing.effect
def test_with_permits_interruption_does_not_leak_permits():
    """withPermits interruption does not leak permits"""
    sem = yield from fx.Semaphore.make(1)
    acquired: list[bool] = []
    waiter = yield from sem.with_permits(fx.sync(lambda: acquired.append(True)), 2).fork()

    yield from fx.yield_now()
    assert waiter.poll_unsafe() is None

    yield from waiter.interrupt()
    assert acquired == []

    assert (yield from sem.with_permits_if_available(fx.void)) is not None

    yield from sem.with_permits(fx.sync(lambda: acquired.append(True)))
    assert acquired == [True]


@testing.effect
def test_with_permits_interrupted_at_any_operation_does_not_leak_permits():
    """withPermits interrupted at any operation does not leak permits"""
    recovered: list[bool] = []
    ran: list[int] = []

    for budget in range(1, 40):
        sem = yield from fx.Semaphore.make(1)
        holder = yield from _with_budget(
            sem.with_permits(fx.sync(lambda b=budget: ran.append(b))), budget
        ).fork(start_immediately=True)
        holder.interrupt_as_unsafe(None)
        yield from holder.await_exit()
        recovered.append((yield from sem.with_permits_if_available(fx.void)) is not None)

    assert all(recovered)
    assert ran, "some budget lets the effect run under the permit"
    assert ran[0] > 1, "small budgets interrupt it before it runs"


@testing.effect
def test_queued_with_permits_interrupted_at_any_operation_does_not_leak_permits():
    """queued withPermits interrupted at any operation does not leak permits"""
    recovered: list[bool] = []
    ran: list[int] = []

    for budget in range(1, 40):
        sem = yield from fx.Semaphore.make(1)
        holder = yield from sem.with_permits(fx.never).fork()
        yield from fx.yield_now()

        queued = yield from _with_budget(
            sem.with_permits(fx.sync(lambda b=budget: ran.append(b))), budget
        ).fork(start_immediately=True)
        yield from holder.interrupt()
        yield from fx.yield_now()
        queued.interrupt_as_unsafe(None)
        yield from queued.await_exit()

        recovered.append((yield from sem.with_permits_if_available(fx.void)) is not None)

    assert all(recovered)
    assert ran, "some budget lets the queued effect run under the permit"
    assert ran[0] > 1, "small budgets interrupt it before it runs"


@testing.effect
def test_take_if_available_acquires_permits_when_they_are_available():
    """takeIfAvailable acquires permits when they are available"""
    sem = yield from fx.Semaphore.make(2)

    assert (yield from sem.take_if_available(2)) is True
    assert (yield from sem.take_if_available(1)) is False
    assert (yield from sem.release(2)) == 2


@testing.effect
def test_take_if_available_returns_immediately_when_permits_are_unavailable():
    """takeIfAvailable returns immediately when permits are unavailable"""
    sem = yield from fx.Semaphore.make(1)

    yield from sem.take(1)
    assert (yield from sem.take_if_available(1)) is False

    yield from sem.release(1)
    assert (yield from sem.take_if_available(1)) is True


@testing.effect
def test_module_level_combinators_delegate_to_the_instance_api():
    """module-level combinators delegate to the instance api"""
    sem = yield from fx.Semaphore.make(1)

    assert (yield from sem.take(1)) == 1
    assert (yield from sem.release(1)) == 1

    yield from sem.resize(2)

    assert (yield from sem.with_permits(fx.succeed(1))) == 1
    assert (yield from sem.with_permits(fx.succeed(2), 2)) == 2
    assert (yield from sem.with_permits_if_available(fx.succeed("ok"))) == fx.Some("ok")

    assert (yield from fx.succeed(3).pipe(sem.with_permits)) == 3
    assert (yield from fx.succeed(4).pipe(lambda eff: sem.with_permits(eff, 1))) == 4
    assert (yield from fx.succeed("pipe").pipe(sem.with_permits_if_available)) == fx.Some("pipe")

    assert (yield from sem.release_all()) == 2


# --- take_scoped (Effect 4.1.2) -------------------------------------------------------------


@testing.effect
def test_take_scoped_holds_permits_until_the_scope_closes():
    """takeScoped holds permits until the scope closes"""
    sem = yield from fx.Semaphore.make(2)
    scope = yield from fx.scope.make()

    yield from sem.take_scoped(2).pipe(fx.scope.provide(scope))
    assert not (yield from sem.take_if_available(1))

    yield from scope.close(fx.exit.void)
    assert (yield from sem.take_if_available(2))


@testing.effect
def test_take_scoped_takes_no_permits_when_interrupted_while_waiting():
    """takeScoped takes no permits when interrupted while waiting"""
    sem = yield from fx.Semaphore.make(1)
    yield from sem.take(1)
    # The scope stays open, so only the interruption can end the acquisition.
    scope = yield from fx.scope.make()
    waiter = (
        yield from sem.take_scoped(1).pipe(fx.scope.provide(scope)).fork(start_immediately=True)
    )

    yield from waiter.interrupt()
    yield from sem.release(1)
    assert (yield from sem.take_if_available(1))


# --- Effect 4.1.2 -------------------------------------------------------------------------


@testing.effect
def test_take_admits_requests_in_fifo_order_when_a_holder_immediately_reacquires():
    """take admits requests in FIFO order when a holder immediately reacquires"""
    sem = yield from fx.Semaphore.make(1)
    asked = 0
    admitted: list[int] = []

    def body() -> Any:
        nonlocal asked
        ticket = asked
        asked += 1
        yield from fx.acquire_release(sem.take(1), lambda _a, _e: sem.release(1))
        admitted.append(ticket)
        yield from fx.sleep("10 millis")

    use = fx.scoped(fx.gen(body))
    chained = yield from use.repeat(times=2).fork()
    others = yield from fx.for_each((1, 2, 3), lambda at: use.delay(f"{at} millis").fork())
    yield from testing.adjust("100 millis")
    yield from chained.join()
    yield from fx.Fiber.join_all(others)
    assert admitted == [0, 1, 2, 3, 4, 5]


@testing.effect
def test_admits_queued_requests_covered_by_a_release_in_one_dispatcher_turn():
    """admits queued requests covered by a release in one dispatcher turn"""
    turns: list[Callable[[], None]] = []

    def _no_cancel() -> None:
        pass

    def hold(run: Callable[[], None]) -> Callable[[], None]:
        turns.append(run)
        return _no_cancel

    on_scheduler = fx.provide_service(CurrentScheduler, MixedScheduler("async", hold))
    sem = yield from fx.Semaphore.make(2)
    yield from sem.take(2)
    admitted: list[int] = []

    def waiter(ticket: int) -> fx.Effect[fx.Fiber[None, Never]]:
        taken = sem.take(1).and_then(fx.sync(lambda: admitted.append(ticket)))
        return taken.pipe(on_scheduler).fork(start_immediately=True)

    waiters = yield from fx.for_each((0, 1), waiter)
    yield from sem.release(2).pipe(on_scheduler)

    def run_turn() -> None:
        turns.pop(0)()

    yield from fx.sync(run_turn)
    assert admitted == [0, 1]
    yield from fx.Fiber.join_all(waiters)
