"""``pipe_to_or_fail``: piping into a channel that must not see upstream
failures.

Upstream's failure reaches the downstream channel as a defect,
``Die(Done(cause))``, which no typed handler catches; once the downstream
pull fails, the defect is unwrapped back into the original cause.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, cast

from pyfect._core import Effect, _FailCause
from pyfect.cause import Cause, Die, Reason, from_reasons
from pyfect.cause import die as die_cause
from pyfect.channel._base import AnyChannel, AnyPull, is_done
from pyfect.channel._channel import Channel, from_transform
from pyfect.errors import Done
from pyfect.pull import is_done_cause
from pyfect.scope import CloseableScope


def _hidden(reason: Reason[Any]) -> Cause[Any] | None:
    """The upstream cause ``reason`` hides, if it is a hidden one."""
    if isinstance(reason, Die) and is_done(reason.defect):
        value: object = reason.defect.value
        if not isinstance(value, Cause):
            return None
        return cast("Cause[Any]", value)  # pragma: no mutate, cast is static
    return None


def has_upstream_failure(cause: Cause[Any]) -> bool:
    return any(_hidden(reason) is not None for reason in cause.reasons)


def upstream_failure_to_defect(pull: AnyPull) -> AnyPull:
    def hide(cause: Cause[Any]) -> AnyPull:
        return _FailCause(cause if is_done_cause(cause) else die_cause(Done(cause)))

    return pull.catch_cause(hide)


def unwrap_upstream_failure(cause: Cause[Any]) -> Cause[Any]:
    if not has_upstream_failure(cause):
        return cause
    reasons: list[Reason[Any]] = []
    for reason in cause.reasons:
        hidden = _hidden(reason)
        reasons.extend((reason,) if hidden is None else hidden.reasons)
    return from_reasons(reasons)


def restore_upstream_failure(pull: AnyPull) -> AnyPull:
    return pull.catch_cause(lambda cause: _FailCause(unwrap_upstream_failure(cause)))


def pipe_to_or_fail(
    self: AnyChannel, that: AnyChannel
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return self._transform(upstream, scope).flat_map(
            lambda pull: that._transform(upstream_failure_to_defect(pull), scope).map(
                restore_upstream_failure
            )
        )

    return from_transform(transform)
