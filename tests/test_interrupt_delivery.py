"""When an interrupt lands. Effect delivers ``interruptUnsafe`` synchronously:
a fiber that has not started never runs its body, a fiber that interrupts
itself stops at its next step, and a parked fiber is woken at once."""

from collections.abc import Callable
from typing import Never, assert_type

import pyfect as fx
from pyfect.cause import Fail, Interrupt
from pyfect.testing import run_test as run


def test_a_fiber_interrupted_before_it_starts_never_runs_its_body():
    """Effect internal/effect.ts: ``forkUnsafe`` only schedules the child;
    ``interruptUnsafe`` on a fiber that is not running evaluates the
    interrupt at once, and the scheduled start then returns early."""
    ran: list[str] = []

    @fx.gen
    def program():
        me = yield from fx.fiber_id()
        fiber = yield from fx.sync(lambda: ran.append("body")).fork()
        yield from fiber.interrupt()
        return me, (yield from fiber.await_exit())

    me, ex = run(program)
    assert ran == []
    assert isinstance(ex, fx.Failure) and ex.cause.reasons == (Interrupt(me),)


def test_an_unstarted_uninterruptible_body_does_not_run_either():
    """The fiber itself starts interruptible (Effect ``forkChild`` default);
    the body's uninterruptible region has not been entered yet."""
    ran: list[str] = []

    @fx.gen
    def program():
        fiber = yield from fx.sync(lambda: ran.append("body")).uninterruptible().fork()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert ran == []
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted_only


def test_a_synchronous_self_interrupt_stops_the_fiber():
    """Effect Fiber.test.ts: delivers a synchronous self-interrupt instead of
    completing to success."""

    @fx.gen
    def child():
        me = yield from fx.current_fiber()
        me.unsafe_interrupt_as(None)
        return 42

    @fx.gen
    def program():
        fiber = yield from child.fork()
        return (yield from fiber.await_exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted


def test_a_map_callback_that_interrupts_its_own_fiber_skips_the_next_map():
    """Effect Effect.test.ts: a map callback that interrupts its own fiber
    skips the next map."""
    ran: list[int] = []
    eff = (
        fx.succeed(0)
        .flat_map(lambda _: fx.current_fiber())
        .map(lambda me: me.unsafe_interrupt_as(None))
        .map(lambda _: ran.append(1))
    )
    ex = fx.testing.run_test_exit(eff)
    assert ran == []
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted


def test_a_self_interrupt_runs_the_interrupt_finalizer_once_in_order():
    """Effect Fiber.test.ts: runs an async interrupt finalizer exactly once,
    in order."""
    events: list[str] = []

    def acquire(me: fx.Fiber[object, object]) -> fx.Effect[None]:
        def body() -> fx.Effect[None]:
            me.unsafe_interrupt_as(None)
            events.append("acquired")
            return fx.void

        return fx.suspend(body)

    finalizer = (
        fx.sync(lambda: events.append("finalizer-start"))
        .and_then(fx.yield_now())
        .and_then(fx.sync(lambda: events.append("finalizer-end")))
    )

    @fx.gen
    def child():
        me = yield from fx.current_fiber()
        yield from acquire(me).on_interrupt(finalizer)
        events.append("unreachable")

    @fx.gen
    def program():
        fiber = yield from child.fork()
        ex = yield from fiber.await_exit()
        events.append("awaited")
        return ex

    ex = run(program)
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted
    assert events == ["acquired", "finalizer-start", "finalizer-end", "awaited"]


def test_a_parked_fiber_is_finished_before_interrupt_returns_control():
    """Interrupting a parked fiber unwinds it synchronously, so its
    finalizer has run by the time the interrupter's next step runs."""
    log: list[str] = []

    @fx.gen
    def program():
        fiber = yield from fx.never.ensuring(fx.sync(lambda: log.append("finalizer"))).fork()
        yield from fx.yield_now()
        yield from fx.sync(lambda: fiber.unsafe_interrupt_as(None))
        log.append("next step")
        return fiber.unsafe_poll()

    ex = run(program)
    assert log == ["finalizer", "next step"]
    assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted_only


def test_interrupt_returns_none():
    """Effect Fiber.ts: ``interrupt`` is ``Effect<void>``; the exit is read
    with ``await``."""

    @fx.gen
    def program():
        fiber = yield from fx.never.fork()
        yield from fx.yield_now()
        result = yield from fiber.interrupt()
        assert_type(result, None)
        return result

    assert run(program) is None


def test_the_exit_is_final_once_an_interrupt_finishes_a_fiber():
    """Effect internal/effect.ts: ``evaluate`` returns at once when the fiber
    already has an exit, so the start scheduled by ``fork`` changes nothing."""

    @fx.gen
    def program():
        fiber = yield from fx.never.fork()
        fiber.unsafe_interrupt_as(None)
        first = fiber.unsafe_poll()
        yield from fx.yield_now()
        return first, fiber.unsafe_poll()

    first, later = run(program)
    assert first is not None and later is first


def test_interrupting_a_deep_tree_of_fibers_finishes_it():
    """Each fiber interrupts its children as it finishes. A deep tree must
    unwind without nesting one fiber's run inside another's (Python's stack
    is far shallower than JavaScript's). Where a too-deep stack breaks
    depends on how deep the caller already is, so try several starting
    depths."""
    depth = 300

    def nest(n: int, leaf: fx.Effect[None]) -> fx.Effect[None]:
        if n == 0:
            return fx.never.ensuring(leaf)
        return fx.suspend(lambda: nest(n - 1, leaf).fork().flat_map(lambda f: f.join()))

    def interrupt_tree() -> tuple[fx.Exit[None, object], list[str]]:
        log: list[str] = []

        @fx.gen
        def program():
            fiber = yield from nest(depth, fx.sync(lambda: log.append("leaf"))).fork()
            for _ in range(depth + 2):
                yield from fx.yield_now()
            yield from fiber.interrupt()
            return (yield from fiber.await_exit())

        return run(program), log

    def at_stack_depth(extra: int) -> tuple[fx.Exit[None, object], list[str]]:
        return interrupt_tree() if extra == 0 else at_stack_depth(extra - 1)

    for extra in range(24):
        ex, log = at_stack_depth(extra)
        assert isinstance(ex, fx.Failure) and ex.cause.is_interrupted_only
        assert log == ["leaf"]


def test_a_resume_that_lands_before_the_interrupt_keeps_its_failure_alone():
    """In Effect a resume runs the fiber at once, so a fiber resumed with a
    failure has finished before the interrupt arrives: its exit is the
    failure alone. pyfect queues the resume; an interrupt arriving meanwhile
    waits for the resumed run, as if it had come after it."""
    resumes: list[Callable[[fx.Effect[None, str]], None]] = []

    def register(resume: Callable[[fx.Effect[None, str]], None]) -> None:
        resumes.append(resume)

    @fx.gen
    def program():
        fiber = yield from fx.callback(register).fork()
        yield from fx.yield_now()
        resumes[0](fx.fail("boom"))
        fiber.unsafe_interrupt_as(None)
        return (yield from fiber.await_exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure) and ex.cause.reasons == (Fail("boom"),)


def _resumed_then_interrupted[A](
    after_resume: fx.Effect[A], resume_with: fx.Effect[None]
) -> fx.Exit[A, Never]:
    """Resume a parked fiber, then interrupt it before the resume runs."""
    resumes: list[Callable[[fx.Effect[None]], None]] = []

    def register(resume: Callable[[fx.Effect[None]], None]) -> None:
        resumes.append(resume)

    @fx.gen
    def program():
        fiber = yield from fx.callback(register).and_then(after_resume).fork()
        yield from fx.yield_now()
        resumes[0](resume_with)
        fiber.unsafe_interrupt_as(None)
        return (yield from fiber.await_exit())

    return run(program)


def test_a_fiber_resumed_before_an_interrupt_finishes_when_it_can():
    """Effect: the resumed run completes before the interrupt lands, which
    then finds the fiber done."""
    ex = _resumed_then_interrupted(fx.succeed("done"), fx.void)
    assert ex == fx.Success("done")


def test_an_interrupt_after_a_queued_resume_stops_the_fiber_at_its_next_wait():
    """Effect: the resumed run goes on until it parks again; the interrupt
    then cancels that wait (running its canceler)."""
    log: list[str] = []

    def park(_resume: Callable[[fx.Effect[None]], None]) -> fx.Effect[None]:
        log.append("parked")
        return fx.sync(lambda: log.append("canceled"))

    ex = _resumed_then_interrupted(fx.callback(park), fx.void)
    assert isinstance(ex, fx.Failure) and ex.cause.reasons == (Interrupt(None),)
    assert log == ["parked", "canceled"]


def test_an_uninterruptible_wait_resumed_before_an_interrupt_finishes_its_run():
    """Effect runs the resume at once, so leaving the uninterruptible region
    happens before the interrupt arrives; the fiber then finishes."""
    resumes: list[Callable[[fx.Effect[None]], None]] = []

    def register(resume: Callable[[fx.Effect[None]], None]) -> None:
        resumes.append(resume)

    @fx.gen
    def program():
        body = fx.callback(register).uninterruptible().and_then(fx.succeed("done"))
        fiber = yield from body.fork()
        yield from fx.yield_now()
        resumes[0](fx.void)
        fiber.unsafe_interrupt_as(None)
        return (yield from fiber.await_exit())

    assert run(program) == fx.Success("done")
