"""Forking into a scope (``fork_in``, ``fork_scoped``, ``Fiber.run_in``) and
``scoped_with``: when the child starts, whether closing the scope can stop
it, what a fork into a closed scope records, and the order finalizers run
in when a fiber is tied to a scope again."""

from typing import Any

import pytest

import pyfect as fx
from pyfect import cause, exit, scope, testing
from pyfect.exit import Failure, Success


def _logging(log: list[str], name: str) -> fx.Effect[None]:
    return fx.sync(lambda: log.append(name))


@testing.effect
def test_fork_in_starts_the_child_later_unless_asked_to_start_it_at_once():
    log: list[str] = []
    s = yield from scope.make()
    yield from scope.fork_in(_logging(log, "later"), s)
    yield from scope.fork_in(_logging(log, "at once"), s, start_immediately=True)
    log.append("parent")
    yield from fx.yield_now()
    assert log == ["at once", "parent", "later"]


@testing.effect
def test_fork_scoped_starts_the_child_later_unless_asked_to_start_it_at_once():
    log: list[str] = []

    def program() -> fx.Effect[None, Any, scope.Scope]:
        @fx.fn
        def body():
            yield from scope.fork_scoped(_logging(log, "later"))
            yield from scope.fork_scoped(_logging(log, "at once"), start_immediately=True)
            log.append("parent")
            yield from fx.yield_now()

        return body()

    yield from scope.scoped(program())
    assert log == ["at once", "parent", "later"]


def _yield_then_log(log: list[str]) -> fx.Effect[None]:
    return fx.yield_now().flat_map(lambda _: _logging(log, "finished"))


@testing.effect
def test_closing_the_scope_interrupts_a_child_unless_it_was_forked_uninterruptible():
    for uninterruptible in (False, True):
        log: list[str] = []
        s = yield from scope.make()
        child = _yield_then_log(log)
        fiber = yield from (
            scope.fork_in(child, s, start_immediately=True, uninterruptible=True)
            if uninterruptible
            else scope.fork_in(child, s, start_immediately=True)
        )
        yield from s.close(exit.void)
        ex = yield from fiber.await_exit()
        assert (log == ["finished"]) is uninterruptible
        assert isinstance(ex, Success) is uninterruptible


@testing.effect
def test_fork_scoped_passes_on_uninterruptible():
    log: list[str] = []
    s = yield from scope.make()
    yield from scope.fork_scoped(
        _yield_then_log(log), start_immediately=True, uninterruptible=True
    ).pipe(scope.provide(s))
    yield from s.close(exit.void)
    yield from fx.yield_now()
    assert log == ["finished"]


@testing.effect
def test_a_fork_into_a_closed_scope_is_interrupted_by_the_forking_fiber_naming_the_scope():
    def program() -> fx.Effect[fx.Exit[None, Any]]:
        closed = scope.CloseableScope()
        return (
            closed.close(exit.void)
            .flat_map(lambda _: scope.fork_in(fx.void, closed))
            .flat_map(lambda fiber: fiber.await_exit())
            .with_span("forker", capture_stack_trace=False)
        )

    parent = yield from fx.fiber_id()
    ex = yield from program()
    assert isinstance(ex, Failure)
    assert ex.cause.interruptors == {parent}
    (note,) = ex.cause.raisable().__notes__
    assert note == (
        f"interrupted by fiber #{parent} because the Scope is closed"
        " (used after the scope that owns it closed)\n"
        "    at forker"
    )


def test_tying_a_fiber_to_a_scope_again_moves_it_to_close_first():
    log: list[str] = []

    @fx.fn
    def program():
        s = yield from scope.make()
        fiber = yield from fx.never.on_interrupt(_logging(log, "fiber")).fork()
        yield from fx.yield_now()
        yield from fx.sync(lambda: fiber.run_in(s))
        yield from s.add_finalizer(lambda _: _logging(log, "finalizer"))
        yield from fx.sync(lambda: fiber.run_in(s))
        yield from s.close(exit.void)

    fx.run_sync(program())
    assert log == ["fiber", "finalizer"]


def test_scoped_with_hands_f_a_scope_it_closes_with_the_exit():
    exits: list[fx.Exit[Any, Any]] = []

    def f(s: scope.CloseableScope) -> fx.Effect[int]:
        return s.add_finalizer(lambda ex: fx.sync(lambda: exits.append(ex))).as_(1)

    assert fx.run_sync(scope.scoped_with(f)) == 1
    assert exits == [Success(1)]


def test_each_scope_combinator_names_the_argument_that_is_no_effect():
    not_effect: Any = 5
    s = scope.CloseableScope()
    calls = {
        "eff": [
            lambda: scope.scoped(not_effect),
            lambda: scope.provide(s)(not_effect),
            lambda: scope.use(s)(not_effect),
            lambda: scope.fork_scoped(not_effect),
            lambda: scope.fork_in(not_effect, s),
        ],
        "acquire": [
            lambda: scope.acquire_release(not_effect, lambda _a, _ex: fx.void),
            lambda: scope.acquire_use_release(not_effect, fx.succeed, lambda _a, _ex: fx.void),
        ],
        "finalizer": [
            lambda: fx.void.ensuring(not_effect),
            lambda: fx.void.on_interrupt(not_effect),
        ],
    }
    for name, makers in calls.items():
        for make in makers:
            with pytest.raises(TypeError, match=rf"^{name} must be an Effect, got int: 5$"):
                make()


def test_on_exit_primitive_interruptible_hands_f_the_exit_and_keeps_the_result():
    seen: list[fx.Exit[Any, Any]] = []

    def record(ex: fx.Exit[Any, Any]) -> None:
        seen.append(ex)

    assert fx.run_sync_exit(fx.succeed(1).on_exit_primitive(record, True)) == Success(1)
    failed = fx.run_sync_exit(fx.fail("a").on_exit_primitive(record, True))
    assert failed == Failure(cause.fail("a"))
    assert seen == [Success(1), Failure(cause.fail("a"))]


@testing.effect
def test_interruptible_lets_an_interrupt_in_inside_an_uninterruptible_region():
    log: list[str] = []
    child = fx.yield_now().interruptible().flat_map(lambda _: _logging(log, "ran on"))
    fiber = yield from child.uninterruptible().fork(start_immediately=True)
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    assert isinstance(ex, Failure) and ex.cause.has_interrupts_only
    assert log == []
