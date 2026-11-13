"""Running effects on a schedule: the work behind ``Effect.retry``,
``repeat``, ``schedule`` and their variants, whose method signatures carry
the types.

Each run of the effect sees the metadata of the step that started it as
``CurrentMetadata``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any, TypeIs

from pyfect._core import Effect, _FailCause, _Locally, _Succeed, _Suspend
from pyfect._effect_args import require_effect
from pyfect.cause import Cause, Fail
from pyfect.effect import fail
from pyfect.pull import catch_done, match_effect
from pyfect.result import Err, Ok, Result
from pyfect.schedule._constructors import forever
from pyfect.schedule._model import (
    CurrentMetadata,
    Metadata,
    MetadataStep,
    Schedule,
    SetInputType,
    to_step_with_metadata,
)


def _with_metadata[A, E, R](eff: Effect[A, E, R], meta: Metadata[Any, Any]) -> Effect[A, E, R]:
    return _Locally(eff, lambda ctx: ctx.add(CurrentMetadata, meta))


def _recoverable(cause: Cause[Any]) -> Result[Any, Cause[Any]]:
    """Effect's ``findRecoverableError`` as a filter."""
    found = cause.find_recoverable_error()
    return Ok(found.error) if isinstance(found, Fail) else Err(found)


class _Loop:
    """What a ``retry`` or ``repeat`` loop carries from step to step. These
    loops, and ``schedule_from``'s, are module functions over their state, never
    closures that reach themselves: such a closure is a reference cycle that keeps
    the last error or value (an HTTP response and its socket) alive until the
    cycle collector runs."""

    __slots__ = ("eff", "last", "last_error", "or_else", "step")

    def __init__(
        self,
        eff: Effect[Any, Any, Any],
        step: MetadataStep[Any, Any, Any, Any],
        or_else: Callable[[Any, Any], Effect[Any, Any, Any]],
    ) -> None:
        self.eff = eff
        self.step = step
        self.or_else = or_else
        self.last: Metadata[Any, Any] = CurrentMetadata.default()
        self.last_error: Any = None


def _retry_attempt(s: _Loop) -> Effect[Any, Any, Any]:
    attempt = _Suspend(partial(_retry_run, s))
    return attempt.catch_cause_filter(_recoverable, partial(_retried, s))


def _retry_run(s: _Loop) -> Effect[Any, Any, Any]:
    return _with_metadata(s.eff, s.last)


def _retried(s: _Loop, error: Any, _cause: Cause[Any]) -> Effect[Any, Any, Any]:
    s.last_error = error
    return s.step(error).flat_map(partial(_retry_again, s))


def _retry_again(s: _Loop, meta: Metadata[Any, Any]) -> Effect[Any, Any, Any]:
    s.last = meta
    return _retry_attempt(s)


def _retry_exhausted(s: _Loop, out: Any) -> Effect[Any, Any, Any]:
    return s.or_else(s.last_error, out)


def _retry_with_step(
    eff: Effect[Any, Any, Any],
    or_else: Callable[[Any, Any], Effect[Any, Any, Any]],
    step: MetadataStep[Any, Any, Any, Any],
) -> Effect[Any, Any, Any]:
    s = _Loop(eff, step, or_else)
    return catch_done(_retry_attempt(s), partial(_retry_exhausted, s))


def retry_or_else(
    eff: Effect[Any, Any, Any],
    policy: Schedule[Any, Any, Any, Any],
    or_else: Callable[[Any, Any], Effect[Any, Any, Any]],
) -> Effect[Any, Any, Any]:
    """Retry ``eff`` after each typed failure while ``policy`` recurs, then
    hand the last error and the policy's final output to ``or_else``.
    Defects and interruptions are not retried."""
    require_effect(eff, "eff")
    # Effect's ``retryOrElse``, op for op.
    return to_step_with_metadata(policy).flat_map(partial(_retry_with_step, eff, or_else))


def retry(
    eff: Effect[Any, Any, Any], policy: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Retry ``eff`` after each typed failure while ``policy`` recurs; then
    fail with the last error."""
    return retry_or_else(eff, policy, lambda error, _: fail(error))


def _repeat_loop(s: _Loop, input: Any) -> Effect[Any, Any, Any]:
    return match_effect(
        s.step(input),
        on_success=partial(_repeat_stepped, s),
        on_failure=_FailCause,
        on_done=_Succeed,
    )


def _repeat_stepped(s: _Loop, meta: Metadata[Any, Any]) -> Effect[Any, Any, Any]:
    s.last = meta
    return _with_metadata(s.eff, meta).flat_map(partial(_repeat_loop, s))


def _repeat_recover(s: _Loop, error: Any, _cause: Cause[Any]) -> Effect[Any, Any, Any]:
    return s.or_else(error, None if s.last.attempt == 0 else s.last)


def _repeat_with_step(
    eff: Effect[Any, Any, Any],
    or_else: Callable[[Any, Any], Effect[Any, Any, Any]],
    step: MetadataStep[Any, Any, Any, Any],
) -> Effect[Any, Any, Any]:
    s = _Loop(eff, step, or_else)
    first = _with_metadata(eff, s.last).flat_map(partial(_repeat_loop, s))
    return first.catch_cause_filter(_recoverable, partial(_repeat_recover, s))


def repeat_or_else(
    eff: Effect[Any, Any, Any],
    schedule: Schedule[Any, Any, Any, Any],
    or_else: Callable[[Any, Metadata[Any, Any] | None], Effect[Any, Any, Any]],
) -> Effect[Any, Any, Any]:
    """Run ``eff``, then again after each success while ``schedule`` recurs,
    succeeding with the schedule's final output. A typed failure of ``eff``
    or of the schedule goes to ``or_else`` with the metadata of the last
    step (``None`` before the first)."""
    require_effect(eff, "eff")
    # Effect's ``repeatOrElse``, op for op.
    return to_step_with_metadata(schedule).flat_map(partial(_repeat_with_step, eff, or_else))


def repeat(
    eff: Effect[Any, Any, Any], schedule: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Run ``eff``, then again after each success while ``schedule`` recurs.
    Succeeds with the schedule's final output."""
    return repeat_or_else(eff, schedule, lambda error, _: fail(error))


def _schedule_loop(
    eff: Effect[Any, Any, Any], step: MetadataStep[Any, Any, Any, Any], input: Any
) -> Effect[Any, Any, Any]:
    return match_effect(
        step(input),
        on_success=partial(_schedule_stepped, eff, step),
        on_failure=_FailCause,
        on_done=_Succeed,
    )


def _schedule_stepped(
    eff: Effect[Any, Any, Any], step: MetadataStep[Any, Any, Any, Any], meta: Metadata[Any, Any]
) -> Effect[Any, Any, Any]:
    return _with_metadata(eff, meta).flat_map(partial(_schedule_loop, eff, step))


def _schedule_with_step(
    eff: Effect[Any, Any, Any], initial: object, step: MetadataStep[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    return _schedule_loop(eff, step, initial)


def schedule_from(
    eff: Effect[Any, Any, Any], initial: object, schedule: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Step ``schedule`` with ``initial``, then run ``eff`` after each delay,
    stepping with its result. Succeeds with the schedule's final output."""
    require_effect(eff, "eff")
    # Effect's ``scheduleFrom``, op for op.
    return to_step_with_metadata(schedule).flat_map(partial(_schedule_with_step, eff, initial))


def scheduled(
    eff: Effect[Any, Any, Any], schedule: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Effect's ``Effect.schedule``: ``schedule_from`` starting with
    ``None``, so ``eff`` first runs after the schedule's first delay."""
    return schedule_from(eff, None, schedule)


type _Predicate = Callable[[Any], bool | Effect[bool, Any, Any]]


def _check(predicate: _Predicate, value: object) -> Effect[bool, Any, Any]:
    result = predicate(value)
    return result if isinstance(result, Effect) else _Succeed(result)


def _check_not(predicate: _Predicate, value: object) -> Effect[bool, Any, Any]:
    result = predicate(value)
    return result.map(lambda b: not b) if isinstance(result, Effect) else _Succeed(not result)


def from_options(
    schedule: Schedule[Any, Any, Any, Any] | None,
    times: int | None,
    while_: _Predicate | None,
    until: _Predicate | None,
) -> Schedule[Any, Any, Any, Any]:
    """Effect's ``buildFromOptions``: the schedule behind the option forms
    of ``repeat`` and ``retry``. It outputs its inputs."""
    policy = forever.passthrough() if schedule is None else schedule.passthrough()
    if while_ is not None:
        keep = while_
        policy = policy.while_effect(lambda m: _check(keep, m.input))
    if until is not None:
        done = until
        policy = policy.while_effect(lambda m: _check_not(done, m.input))
    if times is not None:
        limit = times
        policy = policy.while_(lambda m: m.attempt <= limit)
    return policy


def resolve_policy(
    policy: Schedule[Any, Any, Any, Any] | Callable[[Any], Any] | None,
    schedule: Schedule[Any, Any, Any, Any] | None,
    times: int | None,
    while_: _Predicate | None,
    until: _Predicate | None,
) -> Schedule[Any, Any, Any, Any]:
    """The schedule behind ``retry`` / ``repeat``: a schedule as given, a
    builder applied to ``SetInputType``, or the keyword options."""
    if policy is None:
        return from_options(schedule, times, while_, until)
    if schedule is not None or times is not None or while_ is not None or until is not None:
        raise TypeError("pass either a schedule or the schedule/times/while_/until keywords")
    if _is_schedule(policy):
        return policy
    built: object = policy(SetInputType())
    if not _is_schedule(built):
        raise TypeError(f"a schedule builder must return a Schedule, got {built!r}")
    return built


def _is_schedule(value: object) -> TypeIs[Schedule[Any, Any, Any, Any]]:
    return isinstance(value, Schedule)
