"""A tracer's ``context`` hook runs every step and every continuation of a
fiber whose context holds the tracer (Effect's ``tracerContext``), handing
it the fiber, and what it runs gets the same values and causes as without a
hook."""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.tracer import NativeSpan, Tracer


class _Hook:
    def __init__(self) -> None:
        self.inside = False
        self.fibers: set[int] = set()

    def __call__[T](self, run: Callable[[], T], fiber: fx.Fiber[Any, Any]) -> T:
        self.fibers.add(fiber.id)
        self.inside = True
        try:
            return run()
        finally:
            self.inside = False


def test_the_hook_runs_steps_and_continuations_with_their_values_and_causes():
    hook = _Hook()
    seen: list[tuple[str, object, bool]] = []

    def record(label: str, value: object) -> object:
        seen.append((label, value, hook.inside))
        return value

    @fx.gen
    def program():
        fiber = fx.Fiber.get_current()
        assert fiber is not None
        a = yield from fx.sync(lambda: record("step", 1)).map(lambda n: record("map", n))
        b = yield from fx.succeed(2).uninterruptible()
        c = (
            yield from fx.fail("boom")
            .uninterruptible()
            .catch_all(lambda e: fx.sync(lambda: record("caught", e)))
        )
        return fiber.id, (a, b, c)

    fiber_id, values = fx.run_blocking(program.with_tracer(Tracer(NativeSpan, hook)))
    assert values == (1, 2, "boom")
    assert seen == [("step", 1, True), ("map", 1, True), ("caught", "boom", True)]
    assert hook.fibers == {fiber_id}
