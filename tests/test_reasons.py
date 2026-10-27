"""Reason errors beyond Effect's titles: ``isinstance`` matching, case order,
mixed causes, and ``stream.unwrap_reason`` (which Effect's tests do not
cover)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import cause, channel, stream, testing
from pyfect.cause import Cause


@dataclass
class Throttled(fx.TaggedError):
    retry_after: int


@dataclass
class HardThrottled(Throttled):
    pass


@dataclass
class Quota(fx.TaggedError):
    limit: int


@dataclass
class ApiError(fx.TaggedError):
    reason: Throttled | Quota


ERROR = ApiError(Quota(1))
DEFECT = RuntimeError("boom")


@testing.effect
def test_a_reason_class_catches_its_subclasses():
    failing: fx.Effect[str, ApiError] = fx.fail(ApiError(HardThrottled(5)))
    result = yield from failing.pipe(
        fx.catch_reason(ApiError, Throttled, lambda r, _: fx.succeed(type(r).__name__))
    )
    assert result == "HardThrottled"


@testing.effect
def test_catch_reasons_uses_the_first_matching_case():
    failing: fx.Effect[str, ApiError] = fx.fail(ApiError(HardThrottled(5)))
    result = yield from failing.pipe(
        fx.catch_reasons(
            ApiError,
            (Throttled, lambda _r, _e: fx.succeed("throttled")),
            (HardThrottled, lambda _r, _e: fx.succeed("hard")),
        )
    )
    assert result == "throttled"


@testing.effect
def test_handlers_receive_the_parent_error():
    error = ApiError(Quota(3))
    failing: fx.Effect[ApiError, ApiError] = fx.fail(error)
    result = yield from failing.pipe(fx.catch_reason(ApiError, Quota, lambda _, e: fx.succeed(e)))
    assert result is error


@testing.effect
def test_stream_unwrap_reason_fails_with_the_reason():
    reason = Quota(7)
    ex = yield from (
        stream.make(1)
        .concat(stream.fail(ApiError(reason)))
        .pipe(stream.unwrap_reason(ApiError))
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(reason))


@testing.effect
def test_stream_catch_reason_keeps_items_written_before_the_failure():
    items = yield from (
        stream.make(1, 2)
        .concat(stream.fail(ApiError(Throttled(9))))
        .pipe(stream.catch_reason(ApiError, Throttled, lambda r, _: stream.succeed(r.retry_after)))
        .run_collect()
    )
    assert items == [1, 2, 9]


def _quota_any(_reason: Quota, _error: ApiError) -> fx.Effect[str]:
    return fx.succeed("recovered")


RECOVERIES: dict[str, Callable[[fx.Effect[Any, ApiError]], fx.Effect[Any, Any]]] = {
    "catch_reason": lambda e: e.pipe(
        fx.catch_reason(ApiError, Quota, lambda _r, _e: fx.succeed("recovered"))
    ),
    "catch_reason or_else": lambda e: e.pipe(
        fx.catch_reason(
            ApiError, Throttled, lambda _r, _e: fx.succeed("recovered"), or_else=_quota_any
        )
    ),
    "catch_reasons": lambda e: e.pipe(
        fx.catch_reasons(ApiError, (Quota, lambda _r, _e: fx.succeed("recovered")))
    ),
    "unwrap_reason": lambda e: e.pipe(fx.unwrap_reason(ApiError)).catch_all(
        lambda _: fx.succeed("recovered")
    ),
}


def _failing(*reasons: cause.Reason[ApiError]) -> fx.Effect[Any, ApiError]:
    return fx.fail_cause(cause.from_reasons(reasons))


@pytest.mark.parametrize("name", RECOVERIES)
def test_defects_take_precedence_over_a_reason_error(name: str) -> None:
    """Effect's "typed recovery with mixed causes" for the reason combinators."""
    recover = RECOVERIES[name]
    failed = testing.run_test(recover(_failing(cause.Fail(ERROR), cause.Die(DEFECT))).exit())
    assert isinstance(failed, fx.Failure)
    expected: Cause[Any] = cause.die(ERROR) + cause.die(DEFECT)
    assert failed.cause == expected


@pytest.mark.parametrize("name", RECOVERIES)
def test_interrupts_beside_a_reason_error_do_not_block_recovery(name: str) -> None:
    recover = RECOVERIES[name]
    ex = testing.run_test(recover(_failing(cause.Fail(ERROR), cause.Interrupt(1))).exit())
    assert ex == fx.Success("recovered")


@testing.effect
def test_channel_catch_reasons_without_or_else_keeps_other_reasons():
    error = ApiError(Quota(2))
    ex = yield from (
        channel.fail(error)
        .pipe(channel.catch_reasons(ApiError, (Throttled, lambda _r, _e: channel.succeed(0))))
        .run_drain()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


def test_unwrap_reason_replaces_the_whole_cause() -> None:
    """Effect's ``unwrapReason`` is a ``catchFilter``: the reason's failure
    replaces the cause, dropping an interrupt beside it (checked under
    Node: only ``Fail``)."""
    reason = Quota(4)
    eff = _failing(cause.Fail(ApiError(reason)), cause.Interrupt(1)).pipe(
        fx.unwrap_reason(ApiError)
    )
    testing.assert_exit_failure(testing.run_test(eff.exit()), cause.fail(reason))
