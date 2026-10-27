"""Ports of the ``catchReason`` and ``catchReasons`` sections of Effect's
``Stream.test.ts`` (``error handling``).

Each test's docstring is the Effect test title. As in
``test_effect_reasons.py``, the parent error's class is the tag, the reason
classes are the reason tags, ``catchReasons``' handlers are
``(reason_class, handler)`` pairs, and handlers take ``(reason, error)``.
"""

from dataclasses import dataclass
from typing import Never

import pyfect as fx
from pyfect import cause, stream, testing
from pyfect.stream import Stream


@dataclass
class RateLimitError(fx.TaggedError):
    retry_after: int


@dataclass
class QuotaExceededError(fx.TaggedError):
    limit: int


@dataclass
class AiError(fx.TaggedError):
    reason: RateLimitError | QuotaExceededError


@dataclass
class OtherError(fx.TaggedError):
    message: str


def _ai(reason: RateLimitError | QuotaExceededError) -> Stream[Never, AiError]:
    return stream.fail(AiError(reason))


def _other(error: OtherError) -> Stream[Never, AiError | OtherError]:
    return stream.fail(error)


# --- catchReason ----------------------------------------------------------------


@testing.effect
def test_catch_reason_catches_matching_reason_handler_succeeds():
    """catches matching reason - handler succeeds"""
    result = yield from (
        _ai(RateLimitError(60))
        .pipe(
            stream.catch_reason(
                AiError, RateLimitError, lambda r, _: stream.succeed(f"retry: {r.retry_after}")
            )
        )
        .run_collect()
    )
    assert result == ["retry: 60"]


@testing.effect
def test_catch_reason_catches_matching_reason_handler_fails():
    """catches matching reason - handler fails"""
    error = OtherError("handled")
    ex = yield from (
        _ai(RateLimitError(60))
        .pipe(stream.catch_reason(AiError, RateLimitError, lambda _r, _e: stream.fail(error)))
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reason_ignores_non_matching_reason():
    """ignores non-matching reason"""
    error = AiError(QuotaExceededError(100))
    ex = yield from (
        stream.fail(error)
        .pipe(stream.catch_reason(AiError, RateLimitError, lambda _r, _e: stream.succeed("no")))
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reason_handles_non_matching_reason_with_or_else():
    """handles non-matching reason with orElse"""

    def quota(reason: QuotaExceededError, _: AiError) -> Stream[str]:
        return stream.succeed(f"quota: {reason.limit}")

    result = yield from (
        _ai(QuotaExceededError(100))
        .pipe(
            stream.catch_reason(
                AiError,
                RateLimitError,
                lambda r, _: stream.succeed(f"retry: {r.retry_after}"),
                or_else=quota,
            )
        )
        .run_collect()
    )
    assert result == ["quota: 100"]


@testing.effect
def test_catch_reason_ignores_non_matching_parent_tag():
    """ignores non-matching parent tag"""
    error = OtherError("test")
    ex = yield from (
        _other(error)
        .pipe(stream.catch_reason(AiError, RateLimitError, lambda _r, _e: stream.succeed("no")))
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reason_or_else_ignores_non_matching_parent_tag():
    """orElse ignores non-matching parent tag"""
    error = OtherError("test")

    def fallback(_reason: QuotaExceededError, _error: AiError) -> Stream[str]:
        return stream.succeed("fallback")

    ex = yield from (
        _other(error)
        .pipe(
            stream.catch_reason(
                AiError, RateLimitError, lambda _r, _e: stream.succeed("no"), or_else=fallback
            )
        )
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


# --- catchReasons ---------------------------------------------------------------


@testing.effect
def test_catch_reasons_catches_matching_reason():
    """catches matching reason"""
    result = yield from (
        _ai(RateLimitError(60))
        .pipe(
            stream.catch_reasons(
                AiError, (RateLimitError, lambda r, _: stream.succeed(f"retry: {r.retry_after}"))
            )
        )
        .run_collect()
    )
    assert result == ["retry: 60"]


@testing.effect
def test_catch_reasons_ignores_non_matching_reason():
    """ignores non-matching reason"""
    error = AiError(QuotaExceededError(100))
    ex = yield from (
        stream.fail(error)
        .pipe(stream.catch_reasons(AiError, (RateLimitError, lambda _r, _e: stream.succeed("no"))))
        .run_collect()
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reasons_handles_non_matching_reason_with_or_else():
    """handles non-matching reason with orElse"""

    def fallback(reason: RateLimitError, _: AiError) -> Stream[str]:
        return stream.succeed(f"fallback: {type(reason).__name__}")

    result = yield from (
        _ai(RateLimitError(60))
        .pipe(
            stream.catch_reasons(
                AiError,
                (QuotaExceededError, lambda r, _: stream.succeed(f"quota: {r.limit}")),
                or_else=fallback,
            )
        )
        .run_collect()
    )
    assert result == ["fallback: RateLimitError"]
