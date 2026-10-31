"""An ``AsyncResult`` that has settled, as an effect."""

from __future__ import annotations

from typing import Any, cast

from pyfect._core import Effect, _Succeed  # pyright: ignore[reportPrivateUsage]
from pyfect.effect import fail_cause
from pyfect.reactivity.async_result import AsyncResult, Failure


def result_effect[A, E](result: AsyncResult[A, E]) -> Effect[A, E]:
    """A failure's cause, else the value (an ``Initial`` is never passed:
    callers wait for a value first)."""
    if isinstance(result, Failure):
        return fail_cause(result.cause)
    return _Succeed(cast("Any", result).value)
