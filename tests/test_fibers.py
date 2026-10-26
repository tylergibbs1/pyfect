"""Forking, joining, interruption, supervision. Runs under the test clock,
so sleeps are instant and ordering is deterministic."""

from collections.abc import Callable

import pyfect as fx
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
        a = yield from fx.sleep(0.01).as_("a").fork()
        b = yield from fx.sleep(0.01).as_("b").fork()
        return (yield from a.join()) + (yield from b.join())

    assert fx.run_sync(program) == "ab"


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
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted_only


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
        work = fx.sleep(5).and_then(say("region done")).uninterruptible().and_then(say("after"))
        fiber = yield from work.fork()
        yield from fx.yield_now()
        interrupted = yield from fiber.interrupt().fork()
        yield from fx.testing.adjust(5)
        yield from interrupted.join()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert log == ["region done"]
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted


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
            yield from fx.sleep(1).and_then(say("daemon ran")).fork_daemon()
            return "parent done"

        yield from parent
        yield from fx.testing.adjust(1)

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

    assert fx.run_sync(fx.callback(register)) == "from thread"


def test_blocking_runs_off_the_scheduler_thread():
    import threading

    main = threading.get_ident()

    @fx.gen
    def program():
        other = yield from fx.blocking(threading.get_ident)
        return other != main

    assert fx.run_sync(program) is True


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
