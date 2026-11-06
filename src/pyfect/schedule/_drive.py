"""Running effects on a schedule: the work behind ``Effect.retry``,
``repeat``, ``schedule`` and their variants, whose method signatures carry
the types.

Each run of the effect sees the metadata of the step that started it as
``CurrentMetadata``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeIs

from pyfect._core import Effect, _FailCause, _Gen, _Locally, _Succeed
from pyfect._effect_args import require_effect
from pyfect.cause import Cause, Fail
from pyfect.effect import fail
from pyfect.exit import Failure
from pyfect.schedule._constructors import forever
from pyfect.schedule._model import (
    CurrentMetadata,
    Metadata,
    Schedule,
    SetInputType,
    Stop,
    to_step_with_metadata,
)


def _with_metadata[A, E, R](eff: Effect[A, E, R], meta: Metadata[Any, Any]) -> Effect[A, E, R]:
    return _Locally(eff, lambda ctx: ctx.add(CurrentMetadata, meta))


def retry_or_else(
    eff: Effect[Any, Any, Any],
    policy: Schedule[Any, Any, Any, Any],
    or_else: Callable[[Any, Any], Effect[Any, Any, Any]],
) -> Effect[Any, Any, Any]:
    """Retry ``eff`` after each typed failure while ``policy`` recurs, then
    hand the last error and the policy's final output to ``or_else``.
    Defects and interruptions are not retried."""
    require_effect(eff, "eff")

    def body() -> Any:
        step = yield from to_step_with_metadata(policy)
        meta: Metadata[Any, Any] = CurrentMetadata.default()
        while True:
            result = yield from _with_metadata(eff, meta).exit()
            if not isinstance(result, Failure):
                return result.value
            found = result.cause.find_recoverable_error()
            if not isinstance(found, Fail):
                return (yield from _FailCause(found))
            decision = yield from step(found.error)
            if isinstance(decision, Stop):
                return (yield from or_else(found.error, decision.output))
            meta = decision

    return _Gen(body)


def retry(
    eff: Effect[Any, Any, Any], policy: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Retry ``eff`` after each typed failure while ``policy`` recurs; then
    fail with the last error."""
    return retry_or_else(eff, policy, lambda error, _: fail(error))


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

    def body() -> Any:
        step = yield from to_step_with_metadata(schedule)
        last: Metadata[Any, Any] = CurrentMetadata.default()

        def loop() -> Any:
            nonlocal last
            while True:
                value = yield from _with_metadata(eff, last)
                decision = yield from step(value)
                if isinstance(decision, Stop):
                    return decision.output
                last = decision

        def recover(cause: Cause[Any]) -> Effect[Any, Any, Any]:
            found = cause.find_recoverable_error()
            if not isinstance(found, Fail):
                return _FailCause(found)
            return or_else(found.error, None if last.attempt == 0 else last)

        return (yield from _Gen(loop).catch_cause(recover))

    return _Gen(body)


def repeat(
    eff: Effect[Any, Any, Any], schedule: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Run ``eff``, then again after each success while ``schedule`` recurs.
    Succeeds with the schedule's final output."""
    return repeat_or_else(eff, schedule, lambda error, _: fail(error))


def schedule_from(
    eff: Effect[Any, Any, Any], initial: object, schedule: Schedule[Any, Any, Any, Any]
) -> Effect[Any, Any, Any]:
    """Step ``schedule`` with ``initial``, then run ``eff`` after each delay,
    stepping with its result. Succeeds with the schedule's final output."""
    require_effect(eff, "eff")

    def body() -> Any:
        step = yield from to_step_with_metadata(schedule)
        value = initial
        while True:
            decision = yield from step(value)
            if isinstance(decision, Stop):
                return decision.output
            value = yield from _with_metadata(eff, decision)

    return _Gen(body)


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
        policy = policy.while_effect(lambda m: _check(done, m.input).map(lambda b: not b))
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
