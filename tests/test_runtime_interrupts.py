"""Who an interruption names and what it carries, and how fibers that are
uninterruptible, parked or not yet started take one."""

import threading
from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import scope as scope_
from pyfect.cause import Interrupt, reason_annotations
from pyfect.tracer import InterruptorStackTrace


class _Note(fx.Tag[str]):
    pass


def _interrupt(ex: fx.Exit[Any, Any]) -> Interrupt:
    assert isinstance(ex, fx.Failure)
    reasons = [r for r in ex.cause.reasons if isinstance(r, Interrupt)]
    assert len(reasons) == 1
    return reasons[0]


def _interruptor_frame(reason: Interrupt) -> str | None:
    frame = reason_annotations(reason).get_option(InterruptorStackTrace)
    return None if frame is None else frame.value.name


def _note(reason: Interrupt) -> str | None:
    note = reason_annotations(reason).get_option(_Note)
    return None if note is None else note.value


def test_children_are_interrupted_by_their_parent_with_its_frame():
    exits: list[fx.Exit[Any, Any]] = []

    @fx.fn_untraced
    def parent():
        yield from fx.never.on_exit(lambda ex: fx.sync(lambda: exits.append(ex))).fork(
            start_immediately=True
        )
        return fx.Fiber.get_current()

    @fx.gen
    def program():
        # Forked inside the span, the parent fiber runs in its frame to the end.
        fiber = yield from parent().fork().with_span("outer")
        parent_fiber = yield from fiber.join()
        assert parent_fiber is not None
        return parent_fiber.id

    parent_id = fx.run_blocking(program)
    reason = _interrupt(exits[0])
    assert reason.fiber_id == parent_id
    assert _interruptor_frame(reason) == "outer"


def test_interrupt_as_names_the_given_fiber_and_adds_the_annotations():
    @fx.gen
    def program():
        notes = fx.Context.make(_Note, "why")
        plain = yield from fx.never.fork(start_immediately=True)
        yield from plain.interrupt_as(42, notes)
        in_span = yield from fx.never.fork(start_immediately=True)
        yield from in_span.interrupt_as(43, notes).with_span("interruptor")
        return (yield from plain.await_exit()), (yield from in_span.await_exit())

    plain, in_span = fx.run_blocking(program)
    assert (_interrupt(plain).fiber_id, _note(_interrupt(plain))) == (42, "why")
    assert _interruptor_frame(_interrupt(plain)) is None
    # The interrupting fiber's own frame and the given annotations, both.
    reason = _interrupt(in_span)
    assert (reason.fiber_id, _note(reason), _interruptor_frame(reason)) == (
        43,
        "why",
        "interruptor",
    )


def test_an_interrupt_from_another_thread_keeps_its_interruptor_and_annotations():
    @fx.gen
    def program():
        target = yield from fx.never.fork(start_immediately=True)
        notes = fx.Context.make(_Note, "from a thread")
        thread = threading.Thread(target=lambda: target.interrupt_as_unsafe(7, notes))
        yield from fx.sync(thread.start)
        ex = yield from target.await_exit()
        yield from fx.sync(thread.join)
        return ex

    reason = _interrupt(fx.run_blocking(program))
    assert (reason.fiber_id, _note(reason)) == (7, "from a thread")


def test_a_fiber_run_in_a_closed_scope_is_interrupted_by_itself():
    @fx.gen
    def program():
        scope = yield from scope_.make()
        yield from scope.close(fx.exit.void)
        fiber = yield from fx.never.fork(start_immediately=True)
        fiber.run_in(scope)
        return fiber.id, (yield from fiber.await_exit())

    fiber_id, ex = fx.run_blocking(program)
    assert _interrupt(ex).fiber_id == fiber_id


def test_an_uninterruptible_fiber_interrupted_before_it_starts_still_runs():
    ran: list[str] = []

    @fx.gen
    def program():
        fiber = yield from fx.sync(lambda: ran.append("body")).fork(uninterruptible=True)
        fiber.interrupt_as_unsafe(None)
        return (yield from fiber.await_exit())

    assert fx.run_blocking(program) == fx.exit.void
    assert ran == ["body"]


def test_an_uninterruptible_fiber_paused_at_a_yield_resumes_in_turn_when_interrupted():
    order: list[str] = []

    @fx.gen
    def program():
        fiber = yield from (
            fx.yield_now()
            .and_then(fx.sync(lambda: order.append("child")))
            .uninterruptible()
            .fork(start_immediately=True)
        )
        fiber.interrupt_as_unsafe(None)
        order.append("parent")
        return (yield from fiber.await_exit())

    fx.run_blocking(program)
    # Not run early by the interrupt: the child goes on when its turn comes.
    assert order == ["parent", "child"]


def test_a_fiber_that_interrupts_itself_while_parking_runs_the_canceler():
    canceled: list[str] = []

    def register(resume: Callable[[fx.Effect[int]], None]) -> fx.Effect[None]:
        fiber = fx.Fiber.get_current()
        assert fiber is not None
        fiber.interrupt_as_unsafe(fiber.id)
        return fx.sync(lambda: canceled.append("canceled"))

    ex = fx.run_blocking_exit(fx.callback(register))
    assert canceled == ["canceled"]
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.reasons[0], Interrupt)


def test_a_fiber_is_interruptible_again_after_a_canceled_wait():
    after: list[str] = []

    def register(resume: Callable[[fx.Effect[int]], None]) -> fx.Effect[None]:
        return fx.void

    @fx.gen
    def child():
        yield from fx.callback(register).exit()
        # The interrupt is still pending and the fiber interruptible: it
        # stops here rather than running on.
        yield from fx.sync(lambda: after.append("after"))

    @fx.gen
    def program():
        fiber = yield from child.fork(start_immediately=True)
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    ex = fx.run_blocking(program)
    assert isinstance(ex, fx.Failure)
    assert after == []
