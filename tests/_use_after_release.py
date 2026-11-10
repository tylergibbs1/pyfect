"""The check every API whose result can outlive its layer goes through.

``value = yield from make().pipe(provide(layer))`` releases ``layer`` once
``make`` returns. Using ``value`` afterwards must fail at once with the
API's typed ``error``, naming what is closed: not wait forever, and not die
with a ``RuntimeError`` from a stopped thread pool or event loop.
"""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect.duration import Duration
from pyfect.exit import Failure
from pyfect.result import Ok

CLOSED = "is closed (used after the scope that owns it closed)"


def assert_fails_after_release[A](
    layer: fx.Layer[Any, Any, Any],
    make: Callable[[], fx.Effect[A, Any, Any]],
    use: Callable[[A], fx.Effect[Any, Any, Any]],
    error: type[BaseException],
    *,
    timeout: float = 5,
) -> BaseException:
    """Make the value with ``layer`` provided to ``make()`` alone, use it,
    and return the typed error the use failed with."""

    @fx.fn
    def program():
        value = yield from make().pipe(fx.provide(layer))
        return (yield from use(value).timeout(Duration(timeout)).exit())

    exit_ = fx.run_blocking(fx.scoped(program()))
    assert isinstance(exit_, Failure), f"used after release, it succeeded: {exit_}"
    found = exit_.cause.find_error()
    assert isinstance(found, Ok), f"not a typed failure: {exit_.cause}"
    assert isinstance(found.value, error), f"expected {error.__name__}, got {found.value!r}"
    assert CLOSED in _text(found.value), f"the error does not say what is closed: {found.value!r}"
    return found.value


def _text(error: BaseException) -> str:
    """The error's message and those of its reasons and causes."""
    parts: list[str] = []
    seen: list[object] = []
    current: object = error
    while current is not None and current not in seen:
        seen.append(current)
        parts.append(str(current))
        parts.append(repr(current))
        current = getattr(current, "reason", None) or getattr(current, "cause", None)
    return "\n".join(parts)
