"""``for_each`` / ``all``: what an outside interrupt reports, and when the
input is read. Effect's ``forEach`` is ``suspend(() => ...)`` and, on
interruption, waits for its workers and keeps their failures."""

import pyfect as fx
from pyfect.cause import Interrupt
from pyfect.duration import seconds
from pyfect.queue import Queue
from pyfect.testing import run_test as run


def test_an_external_interrupt_keeps_a_worker_defect():
    """Effect Effect.test.ts: preserves interruption when a child cleanup
    dies."""
    defect = ValueError("cleanup defect")

    @fx.gen
    def program():
        started = fx.Deferred[None]()

        def work(i: int) -> fx.Effect[None]:
            if i == 0:
                return started.succeed(None).and_then(fx.callback(lambda _: fx.die(defect)))
            return fx.never

        fiber = yield from fx.for_each([0, 1], work, concurrency=2).fork(start_immediately=True)
        yield from started.wait()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert ex.cause.defects == (defect,)


def test_unbounded_concurrency_forks_even_a_single_item():
    """Effect's ``forEach`` picks the sequential loop by the concurrency
    option alone (``resolveConcurrency(c) === 1``), never by how many items
    there are: one item under ``"unbounded"`` still runs in a child fiber, so an
    outside interrupt reports only the caller's interruption, not the child's
    own interrupt from its finalizer. Found by tests/runtime_diff."""

    @fx.gen
    def program():
        child = fx.never.ensuring(fx.interrupt())
        fiber = yield from fx.for_each([0], lambda _: child, concurrency="unbounded").fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        return fiber.id, (yield from fiber.await_exit())

    fiber_id, ex = run(program)
    assert isinstance(ex, fx.Failure)
    interruptors = [r.fiber_id for r in ex.cause.reasons if isinstance(r, Interrupt)]
    assert fiber_id not in interruptors
    assert len(ex.cause.reasons) == 1


def test_an_external_interrupt_keeps_a_recorded_sibling_failure():
    """Effect Effect.test.ts: preserves a recorded sibling failure on
    external interruption."""

    @fx.gen
    def program():
        started = fx.Deferred[None]()
        cleanup_started = fx.Deferred[None]()
        release = fx.Deferred[None]()

        def work(i: int) -> fx.Effect[None, str]:
            if i == 0:
                cleanup = cleanup_started.succeed(None).and_then(release.wait())
                return started.succeed(None).and_then(fx.never).on_interrupt(cleanup)
            return started.wait().and_then(fx.fail("sibling failure"))

        fiber = yield from fx.for_each([0, 1], work, concurrency=2).fork(start_immediately=True)
        yield from cleanup_started.wait()
        fiber.interrupt_as_unsafe(None)
        yield from release.succeed(None)
        return (yield from fiber.await_exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert ex.cause.failures == ("sibling failure",)


def test_an_external_interrupt_waits_for_every_worker_to_finish():
    """The interrupted for_each completes only after each worker's cleanup."""
    log: list[str] = []

    def work(i: int) -> fx.Effect[None]:
        cleanup = fx.sleep(seconds(i + 1)).and_then(fx.sync(lambda: log.append(f"w{i} cleaned")))
        return fx.never.on_interrupt(cleanup)

    @fx.gen
    def program():
        fiber = yield from fx.for_each([0, 1], work, concurrency=2).fork(start_immediately=True)
        yield from fx.yield_now()
        interrupter = yield from fiber.interrupt().fork()
        yield from fx.testing.adjust("2 seconds")
        yield from interrupter.join()
        log.append("interrupt returned")
        return (yield from fiber.await_exit())

    ex = run(program)
    assert log == ["w0 cleaned", "w1 cleaned", "interrupt returned"]
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def test_for_each_reads_the_iterable_when_it_runs():
    """Effect effect.ts: ``forEach`` reads the iterable inside ``suspend``."""
    for concurrency in (None, 2):
        items = {"a": 1}
        eff = fx.for_each(items.values(), fx.succeed, concurrency=concurrency)
        items["b"] = 2
        assert run(eff) == [1, 2]


def test_a_one_shot_iterable_is_consumed_by_the_first_run():
    for concurrency in (None, 2):
        eff = fx.for_each((x for x in [1, 2]), fx.succeed, concurrency=concurrency)
        assert run(eff) == [1, 2]
        assert run(eff) == []


def test_offer_all_reads_the_iterable_when_it_runs():
    @fx.gen
    def program():
        q = yield from Queue[int].unbounded()
        items = [1]
        offer = q.offer_all(items)
        items.append(2)
        yield from offer
        return (yield from q.take_all())

    assert list(run(program)) == [1, 2]
