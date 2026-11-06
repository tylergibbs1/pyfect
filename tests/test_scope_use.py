"""``Scope.make``, ``Scope.provide`` and ``Scope.use`` (``pyfect.scope``):
Effect's ``Scope.test.ts`` has no titles for them, so these pin what
Effect 4.0.6 does under Node: ``provide`` hands a scope on and leaves it
open, ``use`` closes it with the effect's exit, also when it fails or is
interrupted."""

from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.scope import CloseableScope


def _release(log: list[fx.Exit[Any, Any]]) -> fx.Effect[str, Never, fx.Scope]:
    return fx.acquire_release(fx.succeed("r"), lambda _a, ex: fx.sync(lambda: log.append(ex)))


@testing.effect
def test_make_gives_an_open_scope_with_the_strategy():
    scope = yield from fx.scope.make()
    parallel = yield from fx.scope.make("parallel")
    assert isinstance(scope, CloseableScope)
    assert scope.is_empty and not scope.is_closed
    assert parallel.strategy == "parallel" and scope.strategy == "sequential"


@testing.effect
def test_provide_leaves_the_scope_open():
    log: list[fx.Exit[Any, Any]] = []
    scope = yield from fx.scope.make()
    value = yield from _release(log).pipe(fx.scope.provide(scope))
    assert value == "r"
    assert log == [] and scope.finalizer_count == 1
    yield from scope.close(fx.exit.void)
    assert log == [fx.exit.void]


@testing.effect
def test_use_closes_the_scope_with_the_effects_exit():
    log: list[fx.Exit[Any, Any]] = []
    scope = yield from fx.scope.make()
    value = yield from _release(log).as_(7).pipe(fx.scope.use(scope))
    assert value == 7
    assert scope.is_closed
    assert log == [fx.exit.succeed(7)]


@testing.effect
def test_use_closes_the_scope_when_the_effect_fails():
    log: list[fx.Exit[Any, Any]] = []
    scope = yield from fx.scope.make()
    failing = _release(log).flat_map(lambda _: fx.fail("boom"))
    ex = yield from failing.pipe(fx.scope.use(scope)).exit()
    assert ex == fx.exit.fail("boom")
    assert scope.is_closed and log == [ex]


@testing.effect
def test_use_closes_the_scope_when_the_fiber_is_interrupted():
    log: list[fx.Exit[Any, Any]] = []
    scope = yield from fx.scope.make()
    fiber = yield from (_release(log).flat_map(lambda _: fx.never).pipe(fx.scope.use(scope)).fork())
    yield from fx.yield_now()
    yield from fiber.interrupt()
    assert scope.is_closed
    assert len(log) == 1 and isinstance(log[0], fx.Failure) and log[0].cause.has_interrupts_only


@testing.effect
def test_use_of_a_closed_scope_runs_new_finalizers_at_once():
    log: list[fx.Exit[Any, Any]] = []
    scope = yield from fx.scope.make()
    yield from scope.close(fx.exit.void)
    yield from _release(log).pipe(fx.scope.use(scope))
    assert log == [fx.exit.void]


def test_fork_unsafe_gives_a_child_closed_with_its_parent():
    parent = CloseableScope()
    child = parent.fork_unsafe("parallel")
    assert child.strategy == "parallel" and not child.is_closed
    fx.run_blocking(parent.close(fx.exit.void))
    assert child.is_closed
