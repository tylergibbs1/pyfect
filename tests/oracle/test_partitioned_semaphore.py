"""Ports of Effect's ``PartitionedSemaphore.test.ts``.

Each test's docstring is the Effect test title. Effect's module-level
functions are methods here. Tests that pause a fiber from a custom
``shouldYield`` sweep ``MaxOpsBeforeYield`` budgets instead, which places
the pause at every step (see ``tests/oracle/test_semaphore.py``).
"""

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.partitioned_semaphore import _GiveBackOnFailure  # pyright: ignore[reportPrivateUsage]

from ._task_queue import TaskQueue


def _with_budget[A, E](eff: fx.Effect[A, E], budget: int) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))


def _succeeded(fiber: fx.Fiber[Any, Any]) -> bool:
    return isinstance(fiber.poll_unsafe(), fx.Success)


@testing.effect
def test_multi_permit_waiters_in_different_partitions_do_not_deadlock():
    """multi-permit waiters in different partitions do not deadlock"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    completed: list[str] = []
    yield from sem.take("holder", 2)
    for key in ("x", "y"):
        task = sem.with_permits(key, fx.sync(lambda key=key: completed.append(key)), 2)
        yield from task.fork_daemon(start_immediately=True)
    yield from sem.release(2)
    assert completed == ["x", "y"]
    assert (yield from sem.available) == 2


@testing.effect
def test_a_partly_served_waiter_keeps_its_turn():
    # Effect 4.1.2: permits released one at a time finish the waiter being
    # served before the next partition gets any (values from Node).
    sem = yield from fx.PartitionedSemaphore[str].make(2)
    completed: list[str] = []
    yield from sem.take("holder", 2)
    for key in ("x", "y"):
        task = sem.with_permits(key, fx.sync(lambda key=key: completed.append(key)), 2)
        yield from task.fork_daemon(start_immediately=True)
    yield from sem.release(1)
    assert completed == []
    yield from sem.release(1)
    assert completed == ["x", "y"]


@testing.effect
def test_a_resumed_waiter_can_immediately_reacquire_released_permits():
    """a resumed waiter can immediately reacquire released permits"""
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    yield from sem.take("holder", 1)

    @fx.gen
    def waiting():
        yield from sem.take("waiter", 1)
        released = yield from sem.release(1)
        available = yield from sem.available
        reacquired = yield from sem.with_permits_if_available(fx.succeed("ok"))
        return released, available, reacquired

    waiter = yield from waiting.fork(start_immediately=True)
    yield from sem.release(1)
    assert (yield from waiter.join()) == (1, 1, fx.Some("ok"))
    assert (yield from sem.available) == 1


@testing.effect
def test_drains_a_long_queue_of_synchronous_with_permit_tasks():
    """drains a long queue of synchronous withPermit tasks"""
    queue = TaskQueue()
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    yield from sem.take("holder", 1)
    completed: list[int] = []
    for i in range(10_000):
        task = sem.with_permits(str(i), fx.sync(lambda i=i: completed.append(i)))
        yield from queue.provide(task).fork_daemon(start_immediately=True)
    assert completed == []

    yield from queue.provide(sem.release(1))
    yield from queue.run_all()
    assert len(completed) == 10_000
    assert (yield from sem.available) == 1


@testing.effect
def test_module_level_combinators_delegate_to_the_instance_api():
    """module-level combinators delegate to the instance api"""
    sem = yield from fx.PartitionedSemaphore[str].make(2)

    assert sem.capacity == 2
    assert (yield from sem.available) == 2

    yield from sem.take("a", 1)
    assert (yield from sem.available) == 1

    assert (yield from sem.with_permits("a", fx.succeed(1))) == 1
    assert (yield from sem.release(1)) == 2
    assert (yield from sem.with_permits("b", fx.succeed(2), 2)) == 2
    assert (yield from sem.with_permits_if_available(fx.succeed("ok"))) == fx.Some("ok")

    assert (yield from fx.succeed(3).pipe(lambda eff: sem.with_permits("c", eff))) == 3
    assert (yield from fx.succeed(4).pipe(lambda eff: sem.with_permits("c", eff, 1))) == 4
    assert (yield from fx.succeed("pipe").pipe(sem.with_permits_if_available)) == fx.Some("pipe")


@testing.effect
def test_zero_permits_run_immediately():
    """zero permits run immediately"""
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    executed: list[bool] = []

    yield from sem.with_permits("a", fx.sync(lambda: executed.append(True)), 0)

    assert executed == [True]
    assert (yield from sem.available) == 1


@testing.effect
def test_with_permits_if_available_does_not_block_or_run_when_unavailable():
    """withPermitsIfAvailable does not block or run when unavailable"""
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    executed: list[bool] = []

    yield from sem.take("a", 1)
    result = yield from sem.with_permits_if_available(
        fx.sync(lambda: executed.append(True)).as_("ok")
    )

    assert result is None
    assert executed == []


@testing.effect
def test_interrupting_a_partially_satisfied_waiter_releases_all_acquired_permits():
    """interrupting a partially satisfied waiter releases all acquired permits"""
    sem = yield from fx.PartitionedSemaphore[str].make(4)

    yield from sem.take("a", 3)
    waiter = yield from sem.take("b", 3).fork()
    yield from fx.yield_now()

    yield from sem.release(1)
    assert (yield from sem.available) == 0
    yield from waiter.interrupt()
    assert (yield from sem.available) == 2
    yield from sem.release(2)

    assert (yield from sem.available) == 4
    yield from sem.take("c", 4)


def _maps(k: int) -> fx.Effect[None]:
    eff = fx.void
    for _ in range(k):
        eff = eff.map(lambda x: x)
    return eff


def _inside_take(fiber: fx.Fiber[Any, Any]) -> bool:
    """The fiber holds a permit its ``take`` has not returned yet."""
    stack = fiber._stack  # pyright: ignore[reportPrivateUsage]
    return any(isinstance(frame, _GiveBackOnFailure) for frame in stack)


@testing.effect
def test_interrupting_an_immediately_satisfied_take_before_completion_restores_permits():
    """interrupting an immediately satisfied take before completion restores permits"""
    # Effect pauses the taker right after it takes the permit. ``maps``
    # steps before the take move it across every point where a budget can
    # pause it, including those between continuations, where the take has
    # its permit but has not returned yet. Once it has returned, the permit
    # is the caller's to give back.
    paused_inside = 0
    for budget in (1, 31, 63):
        for k in range(70):
            sem = yield from fx.PartitionedSemaphore[str].make(1)
            take = _maps(k).and_then(sem.take("a", 1))
            taker = yield from _with_budget(take, budget).fork(start_immediately=True)
            inside = _inside_take(taker)
            taker.interrupt_as_unsafe(None)
            ex = yield from taker.await_exit()

            if inside:
                paused_inside += 1
                assert isinstance(ex, fx.Failure), (budget, k)
                assert (yield from sem.available) == 1, (budget, k)
            elif isinstance(ex, fx.Success):
                assert (yield from sem.available) == 0, (budget, k)

    assert paused_inside > 0, "some step pauses the taker inside its take"


@testing.effect
def test_competing_takes_cannot_acquire_the_same_permit_across_scheduler_yields():
    """competing takes cannot acquire the same permit across scheduler yields"""
    for budget in range(1, 40):
        sem = yield from fx.PartitionedSemaphore[str].make(1)
        first = yield from _with_budget(sem.take("first", 1), budget).fork(start_immediately=True)
        second = yield from sem.take("second", 1).fork(start_immediately=True)
        assert (yield from sem.available) >= 0
        for _ in range(budget):
            yield from fx.yield_now()

        both = _succeeded(first) and _succeeded(second)
        assert not both, budget
        assert (yield from sem.available) >= 0, budget

        taken = _succeeded(first) + _succeeded(second)
        yield from first.interrupt()
        yield from second.interrupt()
        yield from sem.release(taken)
        assert (yield from sem.available) == 1, budget


@testing.effect
def test_interrupting_with_permits_if_available_before_cleanup_is_installed_restores_permits():
    """interrupting withPermitsIfAvailable before cleanup is installed restores permits"""
    for budget in range(1, 40):
        sem = yield from fx.PartitionedSemaphore[str].make(1)
        ran: list[bool] = []
        user = fx.sync(lambda ran=ran: ran.append(True))
        fiber = yield from _with_budget(sem.with_permits_if_available(user), budget).fork(
            start_immediately=True
        )
        fiber.interrupt_as_unsafe(None)
        ex = yield from fiber.await_exit()

        assert isinstance(ex, fx.Failure) or ran, budget
        assert (yield from sem.available) == 1, budget


@fx.fn
def _interrupt_resumed_waiter(key: str, budget: int, *, bare_take: bool):
    """Interrupt the woken waiter for the only permit, pausing it at step
    ``budget`` of its resumed run; the waiter's and the next waiter's exits."""
    sem = yield from fx.PartitionedSemaphore[str].make(1)
    yield from sem.take("holder", 1)
    waiting = sem.take("same", 1) if bare_take else sem.with_permits("same", fx.never)
    first = yield from _with_budget(waiting, budget).fork(start_immediately=True)
    for _ in range(budget):
        yield from fx.yield_now()

    yield from sem.release(1)
    nxt = yield from sem.take(key, 1).fork(start_immediately=True)
    yield from first.interrupt()
    for _ in range(3):
        yield from fx.yield_now()

    ex = nxt.poll_unsafe()
    yield from nxt.interrupt()
    return first.poll_unsafe(), ex


def _check_resumed_waiter_interrupts(key: str) -> fx.Effect[None]:
    """Effect pauses the woken ``take`` before it returns. Small budgets do
    that here; with larger ones the take returns first and keeps the permit,
    which Effect's test does not cover. ``with_permits(never)`` never
    returns, so there every pause must pass the permit on."""

    @fx.gen
    def check():
        paused_inside = 0
        for budget in range(1, 40):
            first, nxt = yield from _interrupt_resumed_waiter(key, budget, bare_take=True)
            if isinstance(first, fx.Failure):
                paused_inside += 1
                assert nxt == fx.Success(None), budget
            else:
                assert first == fx.Success(None) and nxt is None, budget
        assert paused_inside > 0, "some budget pauses the take before it returns"

        for budget in range(1, 40):
            _, nxt = yield from _interrupt_resumed_waiter(key, budget, bare_take=False)
            assert nxt == fx.Success(None), budget

    return check


@testing.effect
def test_interrupting_a_resumed_waiter_preserves_the_next_other_key_waiter():
    """interrupting a resumed waiter preserves the next other-key waiter"""
    yield from _check_resumed_waiter_interrupts("other")


@testing.effect
def test_interrupting_a_resumed_waiter_preserves_the_next_same_key_waiter():
    """interrupting a resumed waiter preserves the next same-key waiter"""
    yield from _check_resumed_waiter_interrupts("same")
