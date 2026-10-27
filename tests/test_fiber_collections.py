"""FiberSet, FiberMap and FiberHandle edge cases beyond Effect's own tests.

Each expected value was checked by running Effect v4's source under Node.
"""

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing


def _run_set_member(scope: fx.CloseableScope, eff: fx.Effect[Any], propagate: bool):
    fiber_set = yield from fx.FiberSet.make().pipe(fx.provide_service(fx.Scope, scope))
    yield from fiber_set.run(eff, propagate_interruption=propagate)
    return fiber_set.deferred


def _run_map_member(scope: fx.CloseableScope, eff: fx.Effect[Any], propagate: bool):
    fiber_map = yield from fx.FiberMap[str].make().pipe(fx.provide_service(fx.Scope, scope))
    yield from fiber_map.run("k", eff, propagate_interruption=propagate)
    return fiber_map.deferred


def _run_handle_member(scope: fx.CloseableScope, eff: fx.Effect[Any], propagate: bool):
    handle = yield from fx.FiberHandle.make().pipe(fx.provide_service(fx.Scope, scope))
    yield from handle.run(eff, propagate_interruption=propagate)
    return handle.deferred


_MEMBERS = {"set": _run_set_member, "map": _run_map_member, "handle": _run_handle_member}


@testing.effect
def test_set_clear_interrupts_a_fiber_a_finalizer_adds_meanwhile():
    fiber_set = yield from fx.FiberSet.make()
    run = yield from fiber_set.runtime()
    added: list[fx.Fiber[Any, Any]] = []
    run(fx.never.ensuring(fx.sync(lambda: added.append(run(fx.never)))))

    yield from fiber_set.clear()

    assert (yield from fiber_set.size()) == 0
    assert added[0].unsafe_poll() is not None


@testing.effect
def test_map_clear_interrupts_a_fiber_a_finalizer_adds_under_a_new_key():
    fiber_map = yield from fx.FiberMap[str].make()
    run = yield from fiber_map.runtime()
    added: list[fx.Fiber[Any, Any]] = []
    run("a", fx.never.ensuring(fx.sync(lambda: added.append(run("b", fx.never)))))

    yield from fiber_map.clear()

    assert (yield from fiber_map.size()) == 0
    assert added[0].unsafe_poll() is not None


@testing.effect
def test_map_clear_keeps_a_fiber_a_finalizer_puts_under_a_cleared_key():
    fiber_map = yield from fx.FiberMap[str].make()
    run = yield from fiber_map.runtime()
    added: list[fx.Fiber[Any, Any]] = []
    run("a", fx.never.ensuring(fx.sync(lambda: added.append(run("a", fx.never)))))

    yield from fiber_map.clear()

    assert fiber_map.unsafe_get("a") is added[0]
    assert added[0].unsafe_poll() is None


@testing.effect
def test_map_clear_visits_a_key_that_left_and_was_set_again_meanwhile():
    fiber_map = yield from fx.FiberMap[str].make()
    run = yield from fiber_map.runtime()
    added: list[fx.Fiber[Any, Any]] = []
    run("a", fx.never)
    run("b", fx.never.ensuring(fx.sync(lambda: added.append(run("a", fx.never)))))

    yield from fiber_map.clear()

    assert added[0].unsafe_poll() is not None
    assert (yield from fiber_map.size()) == 0


@testing.effect
def test_propagate_interruption_ignores_the_collections_own_interrupts():
    fiber_map = yield from fx.FiberMap[str].make()
    yield from fiber_map.run("a", fx.never, propagate_interruption=True)
    yield from fiber_map.run("a", fx.never, propagate_interruption=True)
    yield from fx.yield_now()
    yield from fiber_map.remove("a")
    yield from fiber_map.run("b", fx.never, propagate_interruption=True)
    yield from fiber_map.clear()
    assert not (yield from fiber_map.deferred.is_done())

    fiber_set = yield from fx.FiberSet.make()
    yield from fiber_set.run(fx.never, propagate_interruption=True)
    yield from fiber_set.clear()
    assert not (yield from fiber_set.deferred.is_done())

    handle = yield from fx.FiberHandle.make()
    yield from handle.run(fx.never, propagate_interruption=True)
    yield from handle.run(fx.never, propagate_interruption=True)
    yield from handle.clear()
    assert not (yield from handle.deferred.is_done())


@pytest.mark.parametrize("kind", ["set", "map", "handle"])
@testing.effect
def test_closing_with_propagate_interruption_lets_join_succeed(kind: str):
    scope = fx.CloseableScope()
    deferred = yield from _MEMBERS[kind](scope, fx.never, True)
    yield from fx.yield_now()
    yield from scope.close(fx.Success(None))
    assert isinstance((yield from deferred.wait().exit()), fx.Success)


@pytest.mark.parametrize(("kind", "reported"), [("set", False), ("map", False), ("handle", True)])
@testing.effect
def test_a_finalizer_defect_while_closing_fails_join_only_for_a_handle(kind: str, reported: bool):
    scope = fx.CloseableScope()
    deferred = yield from _MEMBERS[kind](
        scope, fx.never.ensuring(fx.die(ValueError("boom"))), False
    )
    yield from fx.yield_now()
    yield from scope.close(fx.Success(None))
    ex = yield from deferred.wait().exit()
    if reported:
        assert isinstance(ex, fx.Failure)
        assert ex.cause.has_interrupts and ex.cause.has_dies
    else:
        assert isinstance(ex, fx.Success)


@testing.effect
def test_handle_clear_can_be_interrupted_while_waiting():
    handle = yield from fx.FiberHandle.make()
    yield from handle.run(fx.sleep(1).uninterruptible())
    clearing = yield from handle.clear().fork(start_immediately=True)
    yield from testing.adjust(0.01)
    interrupting = yield from clearing.interrupt().fork(start_immediately=True)
    yield from testing.adjust(0.01)

    assert clearing.unsafe_poll() is not None
    assert interrupting.unsafe_poll() is not None
    assert handle.unsafe_get() is not None
    yield from testing.adjust(2)
    assert handle.unsafe_get() is None
