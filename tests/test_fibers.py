"""Forking, joining, interruption, supervision. Runs under the test clock,
so sleeps are instant and ordering is deterministic."""

import threading
import time
from collections.abc import Callable
from typing import Never

import pyfect as fx
from pyfect import testing
from pyfect.cause import Interrupt
from pyfect.testing import run_test as run


def logger() -> tuple[list[str], Callable[[str], fx.Effect[None]]]:
    log: list[str] = []
    return log, lambda msg: fx.sync(lambda: log.append(msg))


def test_fork_and_join():
    @fx.gen
    def program():
        fiber = yield from fx.succeed(21).map(lambda n: n * 2).fork()
        return (yield from fiber.join())

    assert run(program) == 42


def test_join_takes_on_a_failure():
    @fx.gen
    def program():
        fiber = yield from fx.fail("bad").fork()
        return (yield from fiber.join())

    ex = fx.testing.run_test_exit(program)
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("bad",)


def test_fork_works_without_asyncio():
    @fx.gen
    def program():
        a = yield from fx.sleep("10 millis").as_("a").fork()
        b = yield from fx.sleep("10 millis").as_("b").fork()
        return (yield from a.join()) + (yield from b.join())

    assert fx.run_blocking(program) == "ab"


def test_interrupt_runs_finalizers_and_reports_interruption():
    log, say = logger()

    @fx.gen
    def program():
        fiber = yield from fx.never.ensuring(say("finalizer")).fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert log == ["finalizer"]
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


def test_interruption_cannot_be_caught():
    log: list[str] = []

    def handler(_: object) -> fx.Effect[None]:
        log.append("handler called")
        return fx.void

    @fx.gen
    def program():
        child = fx.never.catch_all(handler).catch_cause(handler)
        fiber = yield from child.fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert log == []


def test_uninterruptible_regions_finish_before_the_interrupt_lands():
    log, say = logger()

    @fx.gen
    def program():
        work = (
            fx.sleep("5 seconds")
            .and_then(say("region done"))
            .uninterruptible()
            .and_then(say("after"))
        )
        fiber = yield from work.fork()
        yield from fx.yield_now()
        interrupted = yield from fiber.interrupt().fork()
        yield from fx.testing.adjust("5 seconds")
        yield from interrupted.join()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert log == ["region done"]
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def test_uninterruptible_mask_restore_reenables_interruption():
    log, say = logger()

    @fx.gen
    def program():
        work = fx.uninterruptible_mask(
            lambda restore: restore(fx.never).ensuring(say("cleanup")).and_then(say("unreachable"))
        )
        fiber = yield from work.fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert log == ["cleanup"]


def test_children_are_interrupted_when_the_parent_finishes():
    log, say = logger()

    @fx.gen
    def parent():
        yield from fx.never.on_interrupt(say("child interrupted")).fork()
        yield from fx.yield_now()
        return "parent done"

    assert run(parent) == "parent done"
    assert log == ["child interrupted"]


def test_daemon_fibers_outlive_their_parent():
    log, say = logger()

    @fx.gen
    def program():
        @fx.gen
        def parent():
            yield from fx.sleep("1 second").and_then(say("daemon ran")).fork_daemon()
            return "parent done"

        yield from parent
        yield from fx.testing.adjust("1 second")

    run(program)
    assert log == ["daemon ran"]


def test_interrupting_a_parent_interrupts_its_children():
    log, say = logger()

    @fx.gen
    def program():
        @fx.gen
        def parent():
            yield from fx.never.on_interrupt(say("grandchild")).fork()
            yield from fx.never

        fiber = yield from parent.fork()
        yield from fx.yield_now()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert log == ["grandchild"]


def test_interrupt_is_attributed_to_the_interrupting_fiber():
    @fx.gen
    def program():
        me = yield from fx.fiber_id()
        fiber = yield from fx.never.fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()
        return me, (yield from fiber.await_exit())

    me, ex = run(program)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Interrupt(me),)


def test_callback_canceler_runs_on_interrupt():
    log, say = logger()
    pending = fx.callback(lambda resume: say("canceled"))

    @fx.gen
    def program():
        fiber = yield from pending.fork()
        yield from fx.yield_now()
        yield from fiber.interrupt()

    run(program)
    assert log == ["canceled"]


def test_callback_can_resume_synchronously():
    assert run(fx.callback(lambda resume: resume(fx.succeed(7)))) == 7


def test_callback_resumed_from_another_thread():
    import threading

    def register(resume: Callable[[fx.Effect[str]], None]) -> None:
        threading.Timer(0.01, lambda: resume(fx.succeed("from thread"))).start()

    assert fx.run_blocking(fx.callback(register)) == "from thread"


def test_blocking_runs_off_the_scheduler_thread():
    import threading

    main = threading.get_ident()

    @fx.gen
    def program():
        other = yield from fx.blocking(threading.get_ident)
        return other != main

    assert fx.run_blocking(program) is True


def test_a_busy_fiber_does_not_starve_others():
    log, say = logger()

    def spin(n: int) -> fx.Effect[None]:
        return fx.void if n == 0 else fx.suspend(lambda: spin(n - 1))

    @fx.gen
    def program():
        fiber = yield from say("other fiber ran").fork()
        yield from spin(10_000).and_then(say("spinner done"))
        yield from fiber.join()

    run(program)
    assert log == ["other fiber ran", "spinner done"]


@testing.effect
def test_an_interrupted_await_all_removes_its_observer():
    """As ``join_all`` (Effect's "cleans up observers on interruption"), an
    abandoned ``await_all`` leaves no observer on the fiber it waited for."""
    fibers = yield from fx.for_each([0, 1], lambda _: fx.never.fork())

    def observer_counts() -> list[int]:
        return [len(f._observers) for f in fibers]  # pyright: ignore[reportPrivateUsage]

    before = observer_counts()
    waiter = yield from fx.Fiber.await_all(fibers).fork(start_immediately=True)
    assert observer_counts() == [before[0] + 1, before[1]]
    yield from waiter.interrupt()
    assert observer_counts() == before


@testing.effect
def test_join_all_stops_at_a_fiber_that_already_failed():
    """Effect's ``fiberJoinAll`` stops adding observers once a fiber has
    failed, so the fibers after it are left without one."""
    failed = yield from fx.fail("boom").fork(start_immediately=True)
    waiting = yield from fx.never.fork()
    ex = yield from fx.Fiber.join_all([failed, waiting]).exit()
    assert ex == fx.exit.fail("boom")
    assert waiting._observers == []  # pyright: ignore[reportPrivateUsage]


@testing.effect
def test_a_finishing_parent_interrupts_its_children_in_fork_order():
    """Effect keeps a fiber's children in an insertion-ordered ``Set``, so
    their interrupt finalizers run in the order they were forked (checked
    against Effect under Node)."""
    log: list[int] = []

    def child(i: int) -> fx.Effect[Never]:
        return fx.never.on_interrupt(fx.sync(lambda: log.append(i)))

    @fx.gen
    def parent():
        for i in range(50):
            yield from child(i).fork(start_immediately=True)
        yield from fx.never

    fiber = yield from parent.fork(start_immediately=True)
    yield from fiber.interrupt()
    assert log == list(range(50))


def test_a_join_from_another_thread_sees_an_exit_landing_as_it_registers():
    """The fiber finishes on its own run's thread while a run on another
    thread is registering its wait: the waiter checks the exit again once
    registered, so it is not left with an observer nobody calls."""
    started = threading.Event()
    release = threading.Event()
    holder: list[fx.Fiber[int, Never]] = []

    def owner() -> None:
        def body():
            fiber = yield from fx.sync(release.wait).as_(7).fork()
            holder.append(fiber)
            started.set()
            # Not a join: that would go through the list patched below.
            while fiber.poll_unsafe() is None:
                yield from fx.sleep("1 millis")

        fx.run_blocking(fx.gen(body))

    thread = threading.Thread(target=owner)
    thread.start()
    started.wait(5)
    fiber = holder[0]

    class FinishingAsAppended(list[object]):
        """The observer list the joiner appends to: the fiber finishes (on
        its own thread) between the joiner's check and its append."""

        def append(self, item: object) -> None:
            release.set()
            deadline = time.monotonic() + 5
            while fiber.poll_unsafe() is None and time.monotonic() < deadline:
                time.sleep(0.001)
            super().append(item)

    fiber._observers = FinishingAsAppended(fiber._observers)  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    ex = fx.run_blocking_exit(fiber.await_exit().timeout("2 seconds"))
    thread.join(5)
    assert ex == fx.Success(fx.Success(7))
