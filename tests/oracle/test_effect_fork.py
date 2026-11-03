"""Ports of the forking sections of Effect's ``Effect.test.ts``:
awaitAllChildren, fork, forkDaemon, forkIn and forkScoped.

Each test's docstring is the Effect test title. ``forkChild`` is ``fork``,
``forkDetach`` is ``fork_daemon``, and ``Scope.provide(scope)`` is
``fx.scope.provide(scope)``. A resume goes through the scheduler
in pyfect where Effect runs the resumed fiber at once, so "does not await
preexisting children in the same fiber" yields once more before polling.
"""

from typing import Any, Literal, Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.result import Ok

type _ForkOptions = Literal["start_immediately", "uninterruptible"]


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _interrupted_only(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only


# --- awaitAllChildren -----------------------------------------------------------------------


@testing.effect
def test_completes_immediately_when_no_children_are_forked():
    """completes immediately when no children are forked"""
    assert (yield from fx.succeed(1).await_all_children()) == 1


@testing.effect
def test_awaits_children_forked_by_the_wrapped_effect():
    """awaits children forked by the wrapped effect"""
    latch = fx.Deferred[None]()

    @fx.gen
    def body():
        yield from latch.wait().fork()
        return 1

    fiber = yield from body.await_all_children().fork(start_immediately=True)
    yield from fx.yield_now()
    assert fiber.poll_unsafe() is None
    yield from latch.succeed(None)
    assert (yield from fiber.join()) == 1


def _parent_with_child(
    child_started: fx.Deferred[None],
    child_fiber: fx.Deferred[fx.Fiber[None]],
    release_child: fx.Deferred[None],
    then: fx.Effect[int, str],
) -> fx.Effect[int, str]:
    @fx.gen
    def child():
        yield from child_started.succeed(None)
        yield from release_child.wait()

    @fx.gen
    def parent():
        forked = yield from child.fork(start_immediately=True)
        yield from child_fiber.succeed(forked)
        return (yield from then)

    return parent


def _interrupt_while_awaiting_children(
    then: fx.Effect[int, str], *, uninterruptible: bool = False
) -> fx.Effect[tuple[fx.Exit[int, str] | None, fx.Exit[None, Never] | None, fx.Exit[int, str]]]:
    @fx.gen
    def program():
        child_started = fx.Deferred[None]()
        child_fiber = fx.Deferred[fx.Fiber[None]]()
        release_child = fx.Deferred[None]()
        awaiting = _parent_with_child(
            child_started, child_fiber, release_child, then
        ).await_all_children()
        if uninterruptible:
            awaiting = awaiting.uninterruptible()
        fiber = yield from awaiting.fork(start_immediately=True)
        child = yield from child_fiber.wait()
        yield from child_started.wait()
        fiber.interrupt_as_unsafe(None)
        yield from fx.yield_now()
        yield from fx.yield_now()
        polled = fiber.poll_unsafe()
        child_polled = child.poll_unsafe()
        yield from release_child.succeed(None)
        final = yield from fiber.await_exit()
        return polled, child_polled, final

    return program


@testing.effect
def test_can_be_interrupted_while_awaiting_children_after_success():
    """can be interrupted while awaiting children after success"""
    ex, child_ex, _ = yield from _interrupt_while_awaiting_children(fx.succeed(1))
    assert _interrupted_only(ex)
    assert _interrupted_only(child_ex)


@testing.effect
def test_can_be_interrupted_while_awaiting_children_after_failure():
    """can be interrupted while awaiting children after failure"""
    ex, child_ex, _ = yield from _interrupt_while_awaiting_children(fx.fail("boom"))
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts
    assert ex.cause.find_error() == Ok("boom")
    assert _interrupted_only(child_ex)


@testing.effect
def test_respects_an_enclosing_uninterruptible_region_while_awaiting_children():
    """respects an enclosing uninterruptible region while awaiting children"""
    ex, child_ex, final = yield from _interrupt_while_awaiting_children(
        fx.succeed(1), uninterruptible=True
    )
    assert ex is None
    assert child_ex is None
    assert _interrupted_only(final)


@testing.effect
def test_does_not_await_children_forked_outside_the_wrapped_effect():
    """does not await children forked outside the wrapped effect"""
    preexisting = yield from fx.never.fork(start_immediately=True)
    fiber = yield from fx.succeed(1).await_all_children().fork(start_immediately=True)
    yield from fx.yield_now()
    assert fiber.poll_unsafe() == fx.Success(1)
    yield from preexisting.interrupt()


@testing.effect
def test_does_not_await_preexisting_children():
    """does not await preexisting children"""
    preexisting = yield from fx.never.fork(start_immediately=True)
    assert (yield from fx.succeed(1).await_all_children()) == 1
    yield from preexisting.interrupt()


@testing.effect
def test_does_not_await_preexisting_children_in_the_same_fiber():
    """does not await preexisting children in the same fiber"""
    preexisting_latch = fx.Deferred[None]()
    scoped_latch = fx.Deferred[None]()

    @fx.gen
    def inner():
        yield from scoped_latch.wait().fork()
        return 1

    @fx.gen
    def outer():
        yield from preexisting_latch.wait().fork()
        return (yield from inner.await_all_children())

    fiber = yield from outer.fork(start_immediately=True)
    yield from fx.yield_now()
    assert fiber.poll_unsafe() is None
    yield from scoped_latch.succeed(None)
    yield from fx.yield_now()
    yield from fx.yield_now()
    assert fiber.poll_unsafe() == fx.Success(1)


# --- fork / forkDaemon ----------------------------------------------------------------------


def _parent_forking(daemon: bool, flags: dict[str, bool]) -> fx.Effect[Any]:
    child = fx.never.on_interrupt(fx.sync(lambda: flags.__setitem__("child", True)))
    forked = child.fork_daemon() if daemon else child.fork(start_immediately=True)
    return (
        forked.and_then(fx.never)
        .on_interrupt(fx.sync(lambda: flags.__setitem__("parent", True)))
        .fork(start_immediately=True)
    )


@testing.effect
def test_fork_is_interrupted_with_parent():
    """fork is interrupted with parent"""
    flags = {"child": False, "parent": False}
    fiber = yield from _parent_forking(False, flags)
    yield from fiber.interrupt()
    assert flags == {"child": True, "parent": True}


@testing.effect
def test_fork_daemon_is_not_interrupted_with_parent():
    """forkDaemon is not interrupted with parent"""
    flags = {"child": False, "parent": False}
    fiber = yield from _parent_forking(True, flags)
    yield from fiber.interrupt()
    assert flags == {"child": False, "parent": True}


# --- forkIn / forkScoped --------------------------------------------------------------------


def _fork_with(
    eff: fx.Effect[None], option: _ForkOptions, fork: str, scope: fx.CloseableScope
) -> fx.Effect[fx.Fiber[None]]:
    start_immediately = option == "start_immediately"
    uninterruptible = option == "uninterruptible"
    if fork == "fork_in":
        return eff.fork_in(
            scope, start_immediately=start_immediately, uninterruptible=uninterruptible
        )
    return eff.fork_scoped(
        start_immediately=start_immediately, uninterruptible=uninterruptible
    ).pipe(fx.scope.provide(scope))


@pytest.mark.parametrize("fork", ["fork_in", "fork_scoped"])
@pytest.mark.parametrize("option", ["start_immediately", "uninterruptible"])
@testing.effect
def test_does_not_run_work_in_an_already_closed_scope(option: _ForkOptions, fork: str):
    """forkIn / forkScoped "does not run work in an already-closed scope with ${options}" """
    scope = fx.CloseableScope()
    yield from scope.close(fx.exit.succeed(None))
    ran: list[bool] = []
    fiber = yield from _fork_with(fx.sync(lambda: ran.append(True)), option, fork, scope)
    ex = yield from fiber.await_exit()
    assert (ran, _interrupted(ex)) == ([], True)


@pytest.mark.parametrize("fork", ["fork_in", "fork_scoped"])
@testing.effect
def test_is_interrupted_when_scope_is_closed(fork: str):
    """forkIn / forkScoped "is interrupted when scope is closed" """
    interrupted: list[bool] = []
    scope = fx.CloseableScope()
    eff = fx.never.on_interrupt(fx.sync(lambda: interrupted.append(True))).as_void()
    yield from _fork_with(eff, "start_immediately", fork, scope)
    yield from scope.close(fx.exit.succeed(None))
    assert interrupted == [True]


@testing.effect
def test_does_not_wait_for_the_fiber_that_closes_a_parallel_scope():
    """does not wait for the fiber that closes a parallel scope"""
    scope = fx.CloseableScope("parallel")
    sibling = yield from fx.never.fork_in(scope)
    closer = yield from scope.close(fx.exit.succeed(None)).as_("closed").fork_in(scope)
    assert (yield from closer.await_exit()) == fx.Success("closed")
    assert _interrupted((yield from sibling.await_exit()))


# --- fork options ---------------------------------------------------------------------------


@testing.effect
def test_start_immediately_runs_the_child_before_the_parent_goes_on():
    log: list[str] = []
    yield from fx.sync(lambda: log.append("child")).fork(start_immediately=True)
    log.append("parent")
    yield from fx.sync(lambda: log.append("scheduled child")).fork()
    log.append("parent again")
    yield from fx.yield_now()
    assert log == ["child", "parent", "parent again", "scheduled child"]


@testing.effect
def test_children_started_immediately_run_in_order_before_their_parent():
    log: list[str] = []

    def child(name: str) -> fx.Effect[Any]:
        grandchild = fx.sync(lambda: log.append(f"{name}.1"))
        return grandchild.fork(start_immediately=True).and_then(fx.sync(lambda: log.append(name)))

    yield from child("a").fork(start_immediately=True)
    yield from child("b").fork(start_immediately=True)
    log.append("parent")
    assert log == ["a.1", "a", "b.1", "b", "parent"]


@testing.effect
def test_a_deep_chain_of_children_started_immediately_does_not_overflow_the_stack():
    def nest(depth: int) -> fx.Effect[int]:
        if depth == 0:
            return fx.succeed(0)
        return (
            fx.suspend(lambda: nest(depth - 1))
            .fork(start_immediately=True)
            .flat_map(lambda f: f.join().map(lambda n: n + 1))
        )

    assert (yield from nest(5000)) == 5000


@pytest.mark.parametrize(
    ("uninterruptible", "parent_uninterruptible", "expected"),
    [
        (False, True, True),
        (True, False, False),
        ("inherit", False, True),
        ("inherit", True, False),
    ],
)
@testing.effect
def test_uninterruptible_sets_how_the_child_starts(
    uninterruptible: bool | Literal["inherit"], parent_uninterruptible: bool, expected: bool
):
    """``expected``: whether interrupting the child stops it before it ends."""
    latch = fx.Deferred[None]()
    fork = latch.wait().fork(uninterruptible=uninterruptible)
    fiber = yield from (fork.uninterruptible() if parent_uninterruptible else fork)
    yield from fx.yield_now()
    fiber.interrupt_as_unsafe(None)
    yield from latch.succeed(None)
    assert _interrupted((yield from fiber.await_exit())) == expected


@testing.effect(asyncio=True)
def test_start_immediately_on_asyncio():
    log: list[str] = []
    child = yield from fx.sync(lambda: log.append("child")).fork(start_immediately=True)
    log.append("parent")
    yield from child.join()
    assert log == ["child", "parent"]


@testing.effect
def test_interrupt_as_attributes_the_interrupt():
    fiber = yield from fx.never.fork(start_immediately=True)
    yield from fiber.interrupt_as(7)
    ex = fiber.poll_unsafe()
    assert isinstance(ex, fx.Failure) and ex.cause.interruptors == frozenset({7})
