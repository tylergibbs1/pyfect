"""Ports of the "interruption before cleanup registration" block of Effect's
``Effect.test.ts``.

Each test's docstring is the Effect test title. Effect's tests pause the
child with a custom ``Scheduler.shouldYield`` right after its context
changes, then interrupt it. pyfect has no per-step hook, so the ports sweep
``MaxOpsBeforeYield`` budgets until the pause has landed at every step of
the body, and interrupt the paused child each time.

The two ``cached`` / ``cachedInvalidateWithTTL`` cases of the block are in
``test_effect_combinators.py``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, ClassVar

import pytest

import pyfect as fx
import pyfect.scope
from pyfect import testing
from pyfect.context import Context
from pyfect.scope import CloseableScope, Finalizer, Strategy

BUDGETS = range(1, 40)


def _current_context() -> Context[Any]:
    fiber = fx.Fiber.get_current()
    assert fiber is not None
    return fiber._context


def _observing[A](body: fx.Effect[A], observed: list[Context[Any]]) -> fx.Effect[A]:
    return body.on_exit(lambda _: fx.sync(lambda: observed.append(_current_context())))


def _fork_paused[A](body: fx.Effect[A], budget: int):
    return body.pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget)).fork(start_immediately=True)


class _RecordingScope(CloseableScope):
    """Records every scope ``scoped`` creates and whether a finalizer was
    ever registered in it."""

    made: ClassVar[list[_RecordingScope]] = []
    __slots__ = ("registered",)

    def __init__(self, strategy: Strategy = "sequential") -> None:
        super().__init__(strategy)
        self.registered = False
        _RecordingScope.made.append(self)

    def _add(self, key: object, finalizer: Finalizer) -> None:
        self.registered = True
        super()._add(key, finalizer)


@pytest.mark.parametrize("budget", BUDGETS)
def test_scoped_closes_its_scope_when_interrupted_after_installing_it(
    budget: int, monkeypatch: pytest.MonkeyPatch
):
    """scoped closes its scope when interrupted after installing it"""
    monkeypatch.setattr(pyfect.scope, "CloseableScope", _RecordingScope)
    monkeypatch.setattr(_RecordingScope, "made", [])
    finalized: list[bool] = []
    original: list[Context[Any]] = []
    observed: list[Context[Any]] = []

    @fx.gen
    def body():
        original.append(_current_context())
        yield from fx.scoped(fx.add_finalizer(lambda _: fx.sync(lambda: finalized.append(True))))

    @fx.gen
    def program():
        child = yield from _fork_paused(_observing(body, observed), budget)
        child.unsafe_interrupt_as(None)
        yield from child.await_exit()

    testing.run_test(program)
    registered = [scope for scope in _RecordingScope.made if scope.registered]
    assert all(scope.is_closed for scope in registered)
    assert len(finalized) == len(registered)
    if original:
        assert observed == original


class Value(fx.Tag[int], key="InterruptedValue"): ...


@pytest.mark.parametrize("budget", BUDGETS)
@testing.effect
def test_provide_service_restores_the_original_context_if_interrupted_before_its_body(
    budget: int,
):
    """provideService restores the original context if interrupted before its body"""
    original: list[Context[Any]] = []
    observed: list[Context[Any]] = []

    @fx.gen
    def body():
        original.append(_current_context())
        yield from fx.void.pipe(fx.provide_service(Value, 2))

    child = yield from _fork_paused(
        _observing(body, observed).pipe(fx.provide_service(Value, 1)), budget
    )
    child.unsafe_interrupt_as(None)
    yield from child.await_exit()
    if original:
        assert observed == original
