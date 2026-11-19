"""``fx.on_thread``: an effect as the root fiber of a run of its own on another
thread, taking on its result, seeing the caller's services, and interrupted
with the caller (Python-only: JavaScript runs every fiber on one thread)."""

import threading
import warnings

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die, Fail
from pyfect.exit import Failure, Success


class Greeting(fx.Tag[str]):
    pass


def test_the_value_comes_back() -> None:
    assert fx.run_blocking(fx.on_thread(fx.succeed(1).map(lambda n: n + 1))) == 2


def test_a_typed_failure_and_a_defect_come_back_as_they_are() -> None:
    failed = fx.run_blocking_exit(fx.on_thread(fx.fail("nope")))
    assert isinstance(failed, Failure)
    assert [type(r) for r in failed.cause.reasons] == [Fail]
    assert failed == fx.run_blocking_exit(fx.fail("nope"))

    boom = ValueError("boom")
    died = fx.run_blocking_exit(fx.on_thread(fx.die(boom)))
    assert isinstance(died, Failure)
    [reason] = died.cause.reasons
    assert isinstance(reason, Die)
    assert reason.defect is boom


def test_the_effect_runs_on_another_thread() -> None:
    @fx.gen
    def program():
        inner = yield from fx.on_thread(fx.sync(threading.get_ident))
        return inner != threading.get_ident()

    assert fx.run_blocking(program)


def test_the_effect_sees_the_callers_services() -> None:
    @fx.gen
    def greet():
        greeting = yield from Greeting()
        return f"{greeting}, world"

    eff = fx.on_thread(greet).pipe(fx.provide_service(Greeting, "hello"))
    assert fx.run_blocking(eff) == "hello, world"


def test_the_callers_run_keeps_serving_its_fibers_meanwhile() -> None:
    ticked = threading.Event()

    @fx.gen
    def heartbeat():
        for _ in range(3):
            yield from fx.sleep("1 millis")
        ticked.set()

    @fx.gen
    def program():
        yield from heartbeat.fork()
        # Blocks the thread it runs on until the heartbeat, on the caller's
        # run, has ticked: inline it would wait the full 4 seconds.
        return (yield from fx.on_thread(fx.sync(lambda: ticked.wait(4))))

    assert fx.run_blocking(program)


def test_interrupting_the_caller_interrupts_the_effect_and_waits_for_its_finalizers() -> None:
    started = threading.Event()
    events: list[str] = []

    @fx.gen
    def cleanup():
        yield from fx.sleep("20 millis")
        events.append("finalized")

    inner = fx.sync(started.set).and_then(fx.never).ensuring(cleanup)

    @fx.gen
    def program():
        fiber = yield from fx.on_thread(inner).fork()
        yield from fx.blocking(lambda: started.wait(4))
        yield from fiber.interrupt()
        events.append("interrupt returned")
        return (yield from fiber.await_exit())

    ex = fx.run_blocking(program)
    assert ex.has_interrupts
    assert events == ["finalized", "interrupt returned"]


def test_the_effect_can_sleep_on_the_callers_test_clock() -> None:
    @fx.gen
    def program():
        clock = yield from testing.test_clock()
        fiber = yield from fx.on_thread(fx.sleep("1 second").as_(7)).fork()
        # The sleep starts on the other thread: wait until the clock has it.
        while clock.pending_sleeps == 0:
            yield from fx.yield_now()
        yield from testing.adjust("1 second")
        return (yield from fiber.join())

    clock = testing.TestClock.layer(warning_delay="100 millis")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert fx.run_blocking(program.pipe(fx.provide(clock))) == 7


def test_a_successful_effect_leaves_no_interrupt_behind() -> None:
    assert fx.run_blocking_exit(fx.on_thread(fx.void)) == Success(None)
