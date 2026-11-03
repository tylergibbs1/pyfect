"""A fired ``resume`` does not keep its fiber alive. The outside a fiber
waits on (a future's done callbacks, a listener list) may keep ``resume``
after calling it; if that kept the fiber, its result would live until the
cycle collector runs, or forever (DOGFOOD beacon #14: an HTTP response
inside ``.timeout`` kept its connection open this way)."""

import gc
import threading
import weakref
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import pytest

import pyfect as fx


class _Value:
    pass


@contextmanager
def _without_cycle_collection() -> Generator[None]:
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _result_after(resume_from: Callable[[Callable[[], None]], None]) -> weakref.ref[_Value]:
    """Run a forked fiber whose wait's ``resume`` (and canceler) the outside
    keeps; ``resume_from(fire)`` decides where ``resume`` is called. Returns
    a weak reference to the fiber's result."""
    kept: list[Any] = []
    results: list[weakref.ref[_Value]] = []

    def register(resume: Callable[[fx.Effect[None]], None]) -> fx.Effect[None]:
        canceler = fx.sync(kept.clear)
        kept.extend([resume, canceler])
        return canceler

    def make() -> _Value:
        value = _Value()
        results.append(weakref.ref(value))
        return value

    @fx.gen
    def program():
        fiber = yield from fx.callback(register).map(lambda _: make()).fork()
        yield from fx.yield_now()
        resume_from(lambda: kept[0](fx.void))
        yield from fiber.await_exit()

    fx.run_sync(program)
    assert kept, "the outside still holds resume"
    return results[0]


@pytest.mark.parametrize("where", ["same thread", "other thread"])
def test_a_kept_resume_does_not_keep_the_fiber_result(where: str) -> None:
    def resume_from(fire: Callable[[], None]) -> None:
        if where == "same thread":
            fire()
            return
        thread = threading.Thread(target=fire)
        thread.start()
        thread.join()

    with _without_cycle_collection():
        result = _result_after(resume_from)
        assert result() is None
