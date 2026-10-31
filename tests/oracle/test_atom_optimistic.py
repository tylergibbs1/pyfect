"""Ports of the ``optimistic`` tests of Effect's
``test/reactivity/Atom.test.ts``. Conventions as in ``test_atom.py``."""

from typing import Any, Never

import pyfect as fx
from pyfect import layer
from pyfect.latch import Latch
from pyfect.reactivity import async_result, atom
from pyfect.reactivity.async_result import AsyncResult

from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def _wait_for(latch: Latch) -> Any:
    def run(_arg: int, _get: atom.FnContext) -> fx.Effect[None]:
        return latch.wait()

    return run


def _take_update(_current: object, update: int) -> int:
    return update


def _success_of(_current: object, update: int) -> AsyncResult[int]:
    return async_result.success(update)


def test_non_result(timers: FakeTimers) -> None:
    """optimistic / non-Result"""
    latch = Latch()
    r = timers.registry()
    i = [0]
    source = atom.make(lambda _get: i[0])
    optimistic = source.optimistic()
    update = atom.optimistic_fn(
        optimistic, reducer=_take_update, fn=atom.fn(_wait_for(latch))
    ).keep_alive()
    assert r.get(source) == 0
    assert r.get(optimistic) == 0
    r.set(update, 1)
    i[0] = 2
    assert r.get(source) == 0
    assert r.get(optimistic) == 1
    latch.open_unsafe()
    timers.flush()
    assert r.get(source) == 2
    assert r.get(optimistic) == 2


def test_result(timers: FakeTimers) -> None:
    """optimistic / Result"""
    runtime = atom.runtime(layer.empty)
    latch = Latch()
    r = timers.registry()
    i = [0]
    source = atom.make(fx.sync(lambda: i[0]))
    optimistic = source.optimistic()
    update = atom.optimistic_fn(optimistic, reducer=_success_of, fn=runtime.fn(_wait_for(latch)))
    r.mount(optimistic)
    r.mount(update)
    assert r.get(source) == async_result.success(0)
    assert r.get(optimistic) == async_result.success(0)
    r.set(update, 1)
    i[0] = 2
    assert r.get(source) == async_result.success(0)
    assert r.get(optimistic) == async_result.success(1, waiting=True)
    latch.open_unsafe()
    timers.flush()
    assert r.get(source) == async_result.success(2)
    assert r.get(optimistic) == async_result.success(2)


def test_failures(timers: FakeTimers) -> None:
    """optimistic / failures"""
    latch = Latch()
    r = timers.registry()
    rebuilds = [0]

    def read(_get: atom.AtomContext) -> int:
        rebuilds[0] += 1
        return 0

    source = atom.make(read)
    optimistic = source.optimistic()

    def run(_arg: int, _get: atom.FnContext) -> fx.Effect[Never, str]:
        return latch.wait().and_then(fx.fail("error"))

    update = atom.optimistic_fn(optimistic, reducer=_take_update, fn=atom.fn(run))
    r.mount(update)
    r.mount(optimistic)
    assert r.get(source) == 0
    assert r.get(optimistic) == 0
    r.set(update, 1)
    assert r.get(source) == 0
    assert r.get(optimistic) == 1
    latch.open_unsafe()
    timers.flush()
    assert r.get(source) == 0
    assert r.get(optimistic) == 0
    assert rebuilds[0] == 1


def test_sync_fn(timers: FakeTimers) -> None:
    """optimistic / sync fn"""
    r = timers.registry()
    i = [0]
    source = atom.make(lambda _get: i[0])
    optimistic = source.optimistic().keep_alive()

    def run(_arg: int, _get: atom.FnContext) -> fx.Effect[None]:
        i[0] = 2
        return fx.void

    update = atom.optimistic_fn(optimistic, reducer=_take_update, fn=atom.fn(run))
    assert r.get(source) == 0
    assert r.get(optimistic) == 0
    r.set(update, 1)
    assert r.get(source) == 2
    assert r.get(optimistic) == 2


def test_intermediate_updates(timers: FakeTimers) -> None:
    """optimistic / intermediate updates"""
    latch = Latch()
    r = timers.registry()
    i = [0]
    source = atom.make(fx.sync(lambda: i[0]))
    optimistic = source.optimistic()

    def make_fn(
        report: Any,
    ) -> atom.AtomResultFn[int, None, Never]:
        def run(_arg: int, _get: atom.FnContext) -> fx.Effect[None]:
            report(async_result.success(123))
            return latch.wait()

        return atom.fn(run)

    update = atom.optimistic_fn(optimistic, reducer=_success_of, fn=make_fn).keep_alive()
    assert r.get(source) == async_result.success(0)
    assert r.get(optimistic) == async_result.success(0)
    r.set(update, 1)
    i[0] = 2
    assert r.get(source) == async_result.success(0)
    assert r.get(optimistic) == async_result.success(123, waiting=True)
    latch.open_unsafe()
    timers.flush()
    assert r.get(source) == async_result.success(2)
    assert r.get(optimistic) == async_result.success(2)
