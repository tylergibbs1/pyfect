"""Ref, Deferred, Queue, Semaphore."""

import time

import pyfect as fx
from pyfect.testing import run_test as run


def test_ref_updates_are_atomic_across_fibers():
    @fx.gen
    def program():
        ref = yield from fx.Ref.make(0)
        yield from fx.for_each(
            range(100),
            lambda _: ref.update(lambda n: n + 1).and_then(fx.yield_now()),
            concurrency=10,
        )
        return (yield from ref.get())

    assert run(program) == 100


def test_ref_modify_returns_a_result_and_updates():
    @fx.gen
    def program():
        ref = yield from fx.Ref.make([1, 2, 3])
        head = yield from ref.modify(lambda xs: (xs[0], xs[1:]))
        return head, (yield from ref.get())

    assert run(program) == (1, [2, 3])


def test_deferred_wakes_every_waiter_with_the_same_result():
    @fx.gen
    def program():
        d = yield from fx.Deferred[int].make()
        waiters = yield from fx.for_each(range(3), lambda _: d.wait().fork())
        yield from fx.yield_now()
        first = yield from d.succeed(7)
        second = yield from d.succeed(8)
        results = yield from fx.for_each(waiters, lambda f: f.join())
        return results, first, second

    assert run(program) == ([7, 7, 7], True, False)


def test_deferred_failure_propagates():
    @fx.gen
    def program():
        d = yield from fx.Deferred[int, str].make()
        yield from d.fail("nope")
        return (yield from d.wait())

    ex = fx.testing.run_test_exit(program)
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("nope",)


def test_bounded_queue_applies_backpressure():
    log: list[str] = []

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(2)

        @fx.gen
        def producer():
            for i in range(4):
                yield from q.offer(i)
                log.append(f"offered {i}")

        fiber = yield from producer.fork()
        yield from fx.yield_now()
        log.append("consumer starts")
        taken: list[int] = []
        for _ in range(4):
            taken.append((yield from q.take()))  # noqa: PERF401
        yield from fiber.join()
        return taken

    assert run(program) == [0, 1, 2, 3]
    assert log[:3] == ["offered 0", "offered 1", "consumer starts"]


def test_dropping_and_sliding_queues():
    @fx.gen
    def program():
        dropping = yield from fx.Queue[int].dropping(2)
        sliding = yield from fx.Queue[int].sliding(2)
        accepted = yield from fx.for_each(range(3), dropping.offer)
        for i in range(3):
            yield from sliding.offer(i)
        return accepted, (yield from dropping.take_all()), (yield from sliding.take_all())

    assert run(program) == ([True, True, False], [0, 1], [1, 2])


def test_ended_queue_drains_then_fails_with_done():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].unbounded()
        yield from q.offer_all([1, 2])
        yield from q.end()
        late = yield from q.offer(3)
        a = yield from q.take()
        b = yield from q.take()
        c = yield from q.take().exit()
        return late, a, b, c

    late, a, b, c = run(program.pipe(fx.catch_tag(fx.Done, fx.die)))
    assert (late, a, b) == (False, 1, 2)
    assert isinstance(c, fx.Failure) and isinstance(c.cause.failures[0], fx.Done)


def test_ending_a_queue_wakes_waiting_takers():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].unbounded()
        taker = yield from q.take().exit().fork()
        yield from fx.yield_now()
        yield from q.end()
        return (yield from taker.join())

    ex = run(program)
    assert isinstance(ex, fx.Failure) and isinstance(ex.cause.failures[0], fx.Done)


def test_a_taker_interrupted_right_after_its_wake_up_passes_it_on():
    @fx.gen
    def program():
        q = yield from fx.Queue[str].unbounded()
        doomed = yield from q.take().fork()
        survivor = yield from q.take().fork()
        yield from fx.yield_now()
        # In one step: queue the interrupt, then wake `doomed`. The interrupt
        # lands after the wake-up but before `doomed` can retry its take.
        yield from fx.sync(lambda: doomed.interrupt_as_unsafe(None)).and_then(q.offer("item"))
        assert isinstance((yield from doomed.await_exit()), fx.Failure)
        return (yield from survivor.join())

    assert run(program) == "item"


@fx.testing.effect
def test_a_semaphore_waiter_interrupted_right_after_its_wake_up_passes_it_on():
    """A release wakes only the waiters its permits serve, so a woken waiter
    interrupted before it retries must hand the wake-up to the next one.
    A one-step budget makes it yield between the wake-up and the retry."""
    for use_take in (True, False):
        sem = yield from fx.Semaphore.make(1)
        yield from sem.take(1)
        waiting = sem.take(1).as_void() if use_take else sem.with_permits(fx.void)
        doomed = yield from waiting.pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1)).fork()
        for _ in range(20):  # one step per turn, until it parks
            yield from fx.yield_now()
        survivor = yield from waiting.fork(start_immediately=True)

        yield from sem.release(1).and_then(fx.sync(lambda d=doomed: d.interrupt_as_unsafe(None)))
        for _ in range(20):
            yield from fx.yield_now()

        assert isinstance(doomed.poll_unsafe(), fx.Failure), use_take
        assert isinstance(survivor.poll_unsafe(), fx.Success), use_take


@fx.testing.effect
def test_a_semaphore_waiter_too_large_for_a_release_keeps_its_place():
    sem = yield from fx.Semaphore.make(3)
    yield from sem.take(3)
    order: list[str] = []

    def waiter(name: str, n: int) -> fx.Effect[None]:
        return sem.with_permits(fx.sync(lambda: order.append(name)).and_then(fx.never), n)

    for name, n in (("a", 2), ("b", 1), ("c", 2)):
        yield from waiter(name, n).fork(start_immediately=True)

    yield from sem.release(1)  # serves b; a needs two
    yield from fx.yield_now()
    yield from sem.release(2)  # a is still ahead of c
    yield from fx.yield_now()

    assert order == ["b", "a"]


def test_a_release_wakes_only_the_waiters_its_permits_can_serve():
    """Waking every waiter on each release makes N contending fibers cost
    O(N^2): each woken fiber that finds the permit taken parks again. Effect
    resumes a waiter at once, so the first one takes the permit and the rest
    stay parked; here a release wakes as many as its free permits serve."""

    @fx.gen
    def program():
        sem = yield from fx.Semaphore.make(1)
        yield from fx.all(
            *[sem.with_permits(fx.yield_now()) for _ in range(3000)], concurrency="unbounded"
        )

    start = time.perf_counter()
    run(program)
    # Linear is about 0.1 s here; waking every waiter took over 20 s.
    assert time.perf_counter() - start < 3


def test_semaphore_limits_concurrency():
    running = 0
    peak = 0

    def enter() -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)

    def leave() -> None:
        nonlocal running
        running -= 1

    @fx.gen
    def program():
        sem = yield from fx.Semaphore.make(2)
        task = sem.with_permits(
            fx.sync(enter).and_then(fx.sleep("1 second")).and_then(fx.sync(leave))
        )
        fiber = yield from fx.for_each(range(6), lambda _: task, concurrency="unbounded").fork()
        yield from fx.testing.adjust("3 seconds")
        yield from fiber.join()
        return (yield from sem.available)

    assert run(program) == 2
    assert peak == 2


def test_semaphore_permits_return_on_interrupt():
    @fx.gen
    def program():
        sem = yield from fx.Semaphore.make(1)
        holder = yield from sem.with_permits(fx.never).fork()
        waiter = yield from sem.with_permits(fx.never).fork()
        yield from fx.yield_now()
        yield from waiter.interrupt()
        yield from holder.interrupt()
        return (yield from sem.available)

    assert run(program) == 1


def test_semaphore_take_and_release_return_counts():
    """Effect: Semaphore.test.ts 'module-level combinators delegate to the instance api'."""

    @fx.gen
    def program():
        sem = yield from fx.Semaphore.make(3)
        return (yield from sem.take(2)), (yield from sem.release(1))

    assert run(program) == (2, 2)


def test_with_permits_interrupted_at_a_yield_gives_its_permit_back():
    @fx.fn
    def program(delay: int):
        sem = yield from fx.Semaphore.make(1)
        holder = yield from sem.with_permits(fx.never).fork()
        yield from fx.for_each(range(delay), lambda _: fx.yield_now())
        yield from holder.interrupt()
        return (yield from sem.available)

    for budget in range(1, 16):
        for delay in range(5):
            budgeted = program(delay).pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            assert run(budgeted) == 1, (budget, delay)


def test_with_permits_takes_its_permits_uninterruptibly():
    """As Effect's ``withPermits``: only the wait is interruptible, so no
    yield between taking the permit and guarding it can lose it. ``maps``
    steps before the take move it onto every yield point a budget allows,
    including the ones between continuations."""

    def maps(k: int) -> fx.Effect[None]:
        eff = fx.void
        for _ in range(k):
            eff = eff.map(lambda x: x)
        return eff

    @fx.fn
    def program(k: int):
        sem = yield from fx.Semaphore.make(1)
        holder = yield from maps(k).and_then(sem.with_permits(fx.never)).fork()
        yield from fx.yield_now()
        yield from holder.interrupt()
        return (yield from sem.available)

    for budget in (31, 63):
        for k in range(40):
            budgeted = program(k).pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            assert run(budgeted) == 1, (budget, k)


@fx.testing.effect
def test_semaphore_resize_wakes_waiters_and_shrinking_holds_takers_back():
    sem = yield from fx.Semaphore.make(1)
    yield from sem.take(1)
    waiter = yield from sem.take(1).fork(start_immediately=True)

    yield from sem.resize(2)
    assert (yield from waiter.join()) == 1

    yield from sem.resize(1)
    assert (yield from sem.available) == -1
    assert (yield from sem.take_if_available(1)) is False
    assert (yield from sem.release_all()) == 1


@fx.testing.effect
def test_a_semaphore_waiter_paused_before_it_parks_still_sees_the_release():
    # The budget pauses the waiter at every step in turn, including between its
    # "not enough permits" check and its park; the release lands in that gap.
    for budget in range(1, 20):
        for use_take in (True, False):
            sem = yield from fx.Semaphore.make(1)
            yield from sem.take(1)
            waiting = sem.take(1).as_void() if use_take else sem.with_permits(fx.void)
            waiter = yield from waiting.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget)).fork(
                start_immediately=True
            )
            yield from sem.release(1)
            for _ in range(50):
                yield from fx.yield_now()
            assert waiter.poll_unsafe() is not None, budget


@fx.testing.effect
def test_a_queue_taker_paused_before_it_parks_still_sees_the_offer():
    for budget in range(1, 20):
        queue = yield from fx.Queue[int].bounded(4)
        taker = (
            yield from queue.take()
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        yield from queue.offer(1)
        for _ in range(50):
            yield from fx.yield_now()
        assert taker.poll_unsafe() is not None, budget
