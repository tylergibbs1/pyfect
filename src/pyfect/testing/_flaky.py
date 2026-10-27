"""``flaky``: retry a test effect that sometimes fails."""

from __future__ import annotations

from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect.cause import Cause, Die, Fail, _as_exception, from_reasons  # pyright: ignore[reportPrivateUsage]
from pyfect.duration import Duration
from pyfect.effect import fail_cause
from pyfect.schedule import recurs
from pyfect.scope import Scope, scoped


@overload
def flaky[A, E](eff: Effect[A, E, Scope], timeout: Duration = 30.0) -> Effect[A]: ...
@overload
def flaky[A, E, R](
    eff: Effect[A, E, Scope | R], timeout: Duration = 30.0
) -> Effect[A, Never, R]: ...
def flaky(eff: Effect[Any, Any, Any], timeout: Duration = 30.0) -> Effect[Any, Any, Any]:
    """Retry ``eff`` (in a fresh scope each time) after any failure, defects
    included, up to 10 times while less than ``timeout`` has passed. Like
    Effect's ``flakyTest``, the last failure dies: its typed errors become
    defects, kept with their tracebacks."""
    attempts: Effect[Any, Any, Any] = scoped(eff).sandbox().retry(recurs(10).up_to(timeout))
    return attempts.catch_all(lambda cause: fail_cause(_all_defects(cause)))


def _all_defects(cause: Cause[Any]) -> Cause[Never]:
    return from_reasons(
        Die(_as_exception(r.error)) if isinstance(r, Fail) else r for r in cause.reasons
    )
