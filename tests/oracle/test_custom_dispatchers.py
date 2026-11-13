# pyright: basic, reportPrivateUsage=false
"""Effect's tests that drive a fiber through a custom ``Scheduler``
(``makeDispatcher`` holding tasks in a list, ``shouldYield`` choosing the pause),
ported from ``Semaphore.test.ts``, ``Latch.test.ts``,
``PartitionedSemaphore.test.ts``, ``Queue.test.ts`` and ``Pool.test.ts``. Earlier
ports of some of them sweep ``MaxOpsBeforeYield`` budgets instead; these run the
original form on ``EffectScheduler``."""

import asyncio
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect._fiber import Fiber
from pyfect.exit import Failure, Success
from pyfect.partitioned_semaphore import PartitionedSemaphore
from pyfect.queue import Queue
from pyfect.scheduler import (
    CurrentScheduler,
    EffectScheduler,
    ExecutionMode,
    MixedScheduler,
    SchedulerDispatcher,
)


class _Held:
    """Holds every task in ``tasks``, for the test to run."""

    def __init__(self, tasks: list[Callable[[], None]]) -> None:
        self._tasks = tasks

    def schedule_task(self, task: Callable[[], None], priority: int) -> None:
        self._tasks.append(task)

    def flush(self) -> None:
        pass


class _Custom(EffectScheduler):
    """``{ executionMode, makeDispatcher, shouldYield }``."""

    execution_mode: ExecutionMode = "async"

    def __init__(
        self,
        should_yield: Callable[[Fiber[Any, Any]], bool],
        tasks: list[Callable[[], None]] | None = None,
    ) -> None:
        self._should_yield = should_yield
        self._tasks = tasks
        self._mixed = MixedScheduler()

    def should_yield(self, fiber: Fiber[Any, Any]) -> bool:
        return self._should_yield(fiber)

    def make_dispatcher(self) -> SchedulerDispatcher:
        return self._mixed.make_dispatcher() if self._tasks is None else _Held(self._tasks)


def _on(
    scheduler: EffectScheduler,
) -> Callable[[fx.Effect[Any, Any, Any]], fx.Effect[Any, Any, Any]]:
    return fx.provide_service(CurrentScheduler, scheduler)


def _drain(tasks: list[Callable[[], None]]) -> None:
    while tasks:
        tasks.pop(0)()


def _never_yields(_: Fiber[Any, Any]) -> bool:
    return False


@testing.effect
def test_take_interruption_does_not_leak_permits():
    """take interruption does not leak permits"""
    tasks: list[Callable[[], None]] = []
    pause = [False]

    def should_yield(_: Fiber[Any, Any]) -> bool:
        if pause[0]:
            pause[0] = False
            return True
        return False

    scheduler = _Custom(should_yield, tasks)
    step = fx.sync(lambda: tasks.pop(0)() if tasks else None)

    sem = yield from fx.Semaphore.make(0)
    waiter = yield from sem.take(1).pipe(_on(scheduler)).fork()

    yield from fx.yield_now()
    yield from sem.release(1).pipe(_on(scheduler))
    assert waiter.poll_unsafe() is None

    pause[0] = True
    yield from step
    assert waiter.poll_unsafe() is None

    yield from waiter.interrupt()
    yield from step

    assert (yield from sem.with_permits_if_available(fx.void)) is not None


@testing.effect
def test_with_permits_interrupted_at_any_operation_does_not_leak_permits():
    """withPermits interrupted at any operation does not leak permits"""
    operations = [0]
    counted = MixedScheduler()

    def count(fiber: Fiber[Any, Any]) -> bool:
        operations[0] += 1
        return counted.should_yield(fiber)

    sem0 = yield from fx.Semaphore.make(1)
    baseline = yield from sem0.with_permits(fx.void).pipe(_on(_Custom(count))).fork()
    yield from baseline.await_exit()
    assert operations[0] > 1

    recovered: list[bool] = []
    ran: list[int] = []
    for at in range(1, operations[0] + 1):
        sem = yield from fx.Semaphore.make(1)
        base = MixedScheduler()
        seen = [0]

        def should_yield(
            fiber: Fiber[Any, Any],
            base: MixedScheduler = base,
            seen: list[int] = seen,
            at: int = at,
        ) -> bool:
            seen[0] += 1
            if seen[0] == at:
                fiber.interrupt_as_unsafe(None)
            return base.should_yield(fiber)

        holder = (
            yield from sem.with_permits(fx.sync(lambda at=at: ran.append(at)))
            .pipe(_on(_Custom(should_yield)))
            .fork()
        )
        yield from holder.await_exit()
        recovered.append((yield from sem.with_permits_if_available(fx.void)) is not None)

    assert recovered == [True] * operations[0]
    assert ran


@testing.effect
def test_queued_with_permits_interrupted_at_any_operation_does_not_leak_permits():
    """queued withPermits interrupted at any operation does not leak permits"""
    operations = [0]
    baseline_sem = yield from fx.Semaphore.make(1)
    baseline_tasks: list[Callable[[], None]] = []
    baseline_holder = yield from baseline_sem.with_permits(fx.never).fork()
    yield from fx.yield_now()

    def count(_: Fiber[Any, Any]) -> bool:
        operations[0] += 1
        return False

    yield from (
        baseline_sem.with_permits(fx.void)
        .pipe(_on(_Custom(count, baseline_tasks)))
        .fork(start_immediately=True)
    )
    yield from baseline_holder.interrupt()
    yield from fx.yield_now()
    _drain(baseline_tasks)
    assert operations[0] > 1

    recovered: list[bool] = []
    ran: list[int] = []
    for at in range(1, operations[0] + 1):
        sem = yield from fx.Semaphore.make(1)
        tasks: list[Callable[[], None]] = []
        seen = [0]

        def should_yield(fiber: Fiber[Any, Any], seen: list[int] = seen, at: int = at) -> bool:
            seen[0] += 1
            if seen[0] == at:
                fiber.interrupt_as_unsafe(None)
            return False

        holder = yield from sem.with_permits(fx.never).fork()
        yield from fx.yield_now()
        yield from (
            sem.with_permits(fx.sync(lambda at=at: ran.append(at)))
            .pipe(_on(_Custom(should_yield, tasks)))
            .fork(start_immediately=True)
        )
        yield from holder.interrupt()
        yield from fx.yield_now()
        _drain(tasks)
        recovered.append((yield from sem.with_permits_if_available(fx.void)) is not None)

    assert recovered == [True] * operations[0]
    assert ran


@testing.effect
def test_release_while_a_flush_is_pending_covers_the_new_waiters():
    """release while a flush is pending covers the new waiters"""
    latch = yield from fx.Latch.make(False)
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)

    first = yield from latch.wait().fork(start_immediately=True)
    yield from latch.release().pipe(_on(scheduler))
    assert len(tasks) == 1

    second = yield from latch.wait().fork(start_immediately=True)
    yield from latch.release().pipe(_on(scheduler))
    assert len(tasks) == 1

    tasks.pop(0)()
    yield from first.join()
    yield from second.join()
    assert not latch.is_open()


@testing.effect
def test_open_unsafe_does_not_resume_waiters_registered_after_a_reentrant_close():
    """openUnsafe does not resume waiters registered after a reentrant close"""
    latch = fx.Latch(False)
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)
    second: list[Fiber[None, Any]] = []

    def body() -> Any:
        yield from latch.wait()
        latch.close_unsafe()
        second.append((yield from latch.wait().fork(start_immediately=True)))
        return (yield from fx.never)

    yield from fx.gen(body).fork(start_immediately=True)
    yield from latch.release().pipe(_on(scheduler))
    latch.open_unsafe()
    assert second[0].poll_unsafe() is None
    assert len(tasks) == 1
    tasks.pop(0)()
    assert second[0].poll_unsafe() is None


@testing.effect
def test_interrupting_a_waiter_removes_it_from_a_pending_flush():
    """interrupting a waiter removes it from a pending flush"""
    latch = yield from fx.Latch.make(False)
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)
    resumed: list[str] = []

    def body() -> Any:
        yield from latch.wait()
        resumed.append("waiter")

    waiter = yield from fx.gen(body).fork(start_immediately=True)
    yield from latch.release().pipe(_on(scheduler))
    assert len(tasks) == 1

    yield from waiter.interrupt()
    exit_ = yield from waiter.await_exit()
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_interrupts

    tasks.pop(0)()
    assert resumed == []
    assert not latch.is_open()


@testing.effect
def test_await_is_interruptible_and_cleans_up_interrupted_waiters():
    """await is interruptible and cleans up interrupted waiters"""
    latch = yield from fx.Latch.make(False)
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)
    resumed: list[str] = []

    def waits(name: str) -> Any:
        def body() -> Any:
            yield from latch.wait()
            resumed.append(name)

        return fx.gen(body)

    interrupted = yield from waits("interrupted").fork(start_immediately=True)
    assert interrupted.poll_unsafe() is None
    yield from interrupted.interrupt()
    exit_ = yield from interrupted.await_exit()
    assert isinstance(exit_, Failure)
    assert exit_.cause.has_interrupts

    yield from latch.release().pipe(_on(scheduler))
    assert len(tasks) == 0

    live = yield from waits("live").fork(start_immediately=True)
    assert live.poll_unsafe() is None
    yield from latch.release().pipe(_on(scheduler))
    assert len(tasks) == 1
    assert live.poll_unsafe() is None
    tasks.pop(0)()
    yield from live.join()
    assert resumed == ["live"]


@testing.effect
def test_drains_a_long_queue_of_synchronous_with_permit_tasks():
    """drains a long queue of synchronous withPermit tasks"""
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)
    sem = yield from PartitionedSemaphore[str].make(1)
    yield from sem.take("holder", 1)
    completed = [0]
    for i in range(10_000):
        yield from (
            sem.with_permits(str(i), fx.sync(lambda: completed.__setitem__(0, completed[0] + 1)))
            .pipe(_on(scheduler))
            .fork_daemon(start_immediately=True)
        )
    assert completed[0] == 0
    yield from sem.release(1).pipe(_on(scheduler))
    _drain(tasks)
    assert completed[0] == 10_000
    assert (yield from sem.available) == 1


def _pausing_on_no_permits(
    sem: PartitionedSemaphore[str],
) -> tuple[Callable[..., bool], list[bool]]:
    paused = [False]

    def should_yield(_: Fiber[Any, Any]) -> bool:
        if paused[0]:
            return False
        paused[0] = fx.run_sync(sem.available) == 0
        return paused[0]

    return should_yield, paused


@testing.effect
def test_interrupting_an_immediately_satisfied_take_before_completion_restores_permits():
    """interrupting an immediately satisfied take before completion restores permits

    As in Effect, the scheduler is asked (and says yes) before the op that hands
    the take's result on. The interrupt that lands in that pause waits until the
    claimed permit has reached the take's continuation (CLAUDE.md, decided
    results), which gives it back as the take fails."""
    sem = yield from PartitionedSemaphore[str].make(1)
    tasks: list[Callable[[], None]] = []
    should_yield, paused = _pausing_on_no_permits(sem)

    taker = (
        yield from sem.take("a", 1)
        .pipe(_on(_Custom(should_yield, tasks)))
        .fork(start_immediately=True)
    )
    assert paused[0]
    taker.interrupt_as_unsafe(None)
    _drain(tasks)
    exit_ = yield from taker.await_exit()

    assert isinstance(exit_, Failure)
    assert (yield from sem.available) == 1


@testing.effect
def test_competing_takes_cannot_acquire_the_same_permit_across_scheduler_yields():
    """competing takes cannot acquire the same permit across scheduler yields"""
    for yield_point in range(20):
        sem = yield from PartitionedSemaphore[str].make(1)
        tasks: list[Callable[[], None]] = []
        checks = [0]

        def should_yield(
            _: Fiber[Any, Any], checks: list[int] = checks, at: int = yield_point
        ) -> bool:
            checks[0] += 1
            return checks[0] == at

        first = (
            yield from sem.take("first", 1)
            .pipe(_on(_Custom(should_yield, tasks)))
            .fork(start_immediately=True)
        )
        second = yield from sem.take("second", 1).fork(start_immediately=True)
        assert (yield from sem.available) >= 0
        _drain(tasks)
        # A fiber resumed by a task run inside this fiber runs right after
        # this run (``Fiber._drive``), where Effect runs it in the task.
        yield from fx.yield_now()

        first_ok = isinstance(first.poll_unsafe(), Success)
        second_ok = isinstance(second.poll_unsafe(), Success)
        assert not (first_ok and second_ok), yield_point
        assert (yield from sem.available) >= 0, yield_point

        yield from first.interrupt()
        yield from second.interrupt()
        yield from sem.release(int(first_ok) + int(second_ok))
        assert (yield from sem.available) == 1, yield_point


@testing.effect
def test_interrupting_with_permits_if_available_before_cleanup_is_installed_restores_permits():
    """interrupting withPermitsIfAvailable before cleanup is installed restores permits"""
    sem = yield from PartitionedSemaphore[str].make(1)
    tasks: list[Callable[[], None]] = []
    should_yield, paused = _pausing_on_no_permits(sem)
    ran: list[bool] = []

    fiber = (
        yield from sem.with_permits_if_available(fx.sync(lambda: ran.append(True)))
        .pipe(_on(_Custom(should_yield, tasks)))
        .fork(start_immediately=True)
    )
    assert paused[0]
    fiber.interrupt_as_unsafe(None)
    _drain(tasks)
    exit_ = yield from fiber.await_exit()

    assert isinstance(exit_, Failure)
    assert ran == []
    assert (yield from sem.available) == 1


def _interrupting_a_resumed_waiter(key: str) -> Any:
    tasks: list[Callable[[], None]] = []
    pause = [False]

    def should_yield(_: Fiber[Any, Any]) -> bool:
        if not pause[0]:
            return False
        pause[0] = False
        return True

    sem = yield from PartitionedSemaphore[str].make(1)
    yield from sem.take("holder", 1)
    first = (
        yield from sem.take("same", 1)
        .pipe(_on(_Custom(should_yield, tasks)))
        .fork(start_immediately=True)
    )

    pause[0] = True
    yield from sem.release(1)
    next_ = yield from sem.take(key, 1).fork(start_immediately=True)
    yield from first.interrupt()
    _drain(tasks)

    exit_ = next_.poll_unsafe()
    yield from next_.interrupt()
    assert isinstance(exit_, Success)


@testing.effect
def test_interrupting_a_resumed_waiter_preserves_the_next_other_key_waiter():
    """interrupting a resumed waiter preserves the next other-key waiter"""
    yield from _interrupting_a_resumed_waiter("other")


@testing.effect
def test_interrupting_a_resumed_waiter_preserves_the_next_same_key_waiter():
    """interrupting a resumed waiter preserves the next same-key waiter"""
    yield from _interrupting_a_resumed_waiter("same")


@testing.effect
def test_flush_unsafe_coalesces_scheduled_releases_across_repeated_offers():
    """flushUnsafe coalesces scheduled releases across repeated offers"""
    tasks: list[Callable[[], None]] = []
    scheduler = _Custom(_never_yields, tasks)
    queue: Queue[int] = yield from Queue.unbounded().pipe(_on(scheduler))
    for _ in range(10):
        yield from queue.take().fork()
    yield from fx.yield_now()

    for i in range(8):
        queue.offer_unsafe(i)
        queue.flush_unsafe()

    assert len(tasks) == 1
    yield from queue.shutdown()


@testing.effect
def test_flush_is_a_no_op_after_shutdown():
    """flush is a no-op after shutdown"""
    queue: Queue[int] = yield from Queue.unbounded()
    yield from queue.shutdown()

    queue.flush_unsafe()
    yield from queue.flush()

    assert (yield from queue.offer(1)) is False


@testing.effect
def test_flush_keeps_a_buffered_message_when_no_taker_is_waiting():
    """flush keeps a buffered message when no taker is waiting"""
    queue: Queue[int] = yield from Queue.unbounded()
    queue.offer_unsafe(1)

    yield from queue.flush()

    assert (yield from queue.take()) == 1


@testing.effect
def test_pool_wakes_the_next_waiter_when_a_woken_waiter_has_yet_to_take_its_item():
    """wakes the next waiter when a woken waiter has yet to take its item"""
    acquired = [0]

    def acquire() -> int:
        acquired[0] += 1
        return acquired[0]

    pool = yield from fx.Pool.make(fx.sync(acquire), size=2)
    owners = [fx.CloseableScope(), fx.CloseableScope()]
    for owner in owners:
        yield from pool.get().pipe(fx.provide_service(fx.Scope, owner))
    hold = [False]
    mixed = MixedScheduler()

    def should_yield(fiber: Fiber[Any, Any]) -> bool:
        return hold[0] or mixed.should_yield(fiber)

    first = (
        yield from pool.use(lambda _: fx.never)
        .pipe(_on(_Custom(should_yield)))
        .fork(start_immediately=True)
    )
    second = yield from pool.use(fx.succeed).fork(start_immediately=True)
    hold[0] = True
    yield from owners[0].close(Success(None))
    yield from fx.yield_now()
    yield from owners[1].close(Success(None))
    yield from fx.yield_now()
    hold[0] = False
    assert isinstance((yield from second.join()), int)
    yield from first.interrupt()


def test_a_mixed_scheduler_wakes_a_taker_on_an_offer_from_outside_any_fiber():
    """Queue.offerUnsafe outside a fiber: scheduleReleaseTaker goes through
    MixedScheduler's dispatcher, whose setImmediate needs no running fiber."""

    async def main() -> int:
        make: fx.Effect[Queue[int]] = Queue.unbounded()
        queue = await fx.run_async(make.pipe(_on(MixedScheduler())))
        taker = asyncio.create_task(fx.run_async(queue.take()))
        await asyncio.sleep(0.01)
        queue.offer_unsafe(1)
        return await asyncio.wait_for(taker, 2)

    assert asyncio.run(main()) == 1
