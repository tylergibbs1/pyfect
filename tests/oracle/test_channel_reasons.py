"""Ports of the reason-error titles of Effect's ``Channel.test.ts``
(``catchReason orElse``, ``catchReason ignores non-matching parent tag``,
``catchReasons orElse`` and the ``unwrapReason`` section).

Each test's docstring is the Effect test title. As in
``test_effect_reasons.py``, the parent error's class is the tag, the reason
classes are the reason tags, ``catchReasons``' handlers are
``(reason_class, handler)`` pairs, and handlers take ``(reason, error)``.
"""

from dataclasses import dataclass
from typing import Never

import pyfect as fx
from pyfect import cause, channel, testing
from pyfect.channel import Channel


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


def _ai(reason: RateLimitError | QuotaExceededError) -> Channel[Never, AiError, Never]:
    return channel.fail(AiError(reason))


def _other(error: OtherError) -> Channel[Never, AiError | OtherError, Never]:
    return channel.fail(error)


@testing.effect
def test_catch_reason_or_else():
    """catchReason orElse"""

    def quota(reason: QuotaExceededError, _: AiError) -> Channel[str]:
        return channel.succeed(f"quota: {reason.limit}")

    recovered = _ai(QuotaExceededError(100)).pipe(
        channel.catch_reason(
            AiError,
            RateLimitError,
            lambda r, _: channel.succeed(f"retry: {r.retry_after}"),
            or_else=quota,
        )
    )
    assert (yield from recovered.run_collect()) == ["quota: 100"]


@testing.effect
def test_catch_reason_ignores_non_matching_parent_tag():
    """catchReason ignores non-matching parent tag"""
    error = OtherError("test")

    def fallback(_reason: QuotaExceededError, _error: AiError) -> Channel[str]:
        return channel.succeed("orElse")

    recovered = _other(error).pipe(
        channel.catch_reason(
            AiError, RateLimitError, lambda _r, _e: channel.succeed("no"), or_else=fallback
        )
    )
    ex = yield from recovered.run_collect().exit()
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reasons_or_else():
    """catchReasons orElse"""

    def fallback(reason: RateLimitError, _: AiError) -> Channel[str]:
        return channel.succeed(f"fallback: {type(reason).__name__}")

    recovered = _ai(RateLimitError(60)).pipe(
        channel.catch_reasons(
            AiError,
            (QuotaExceededError, lambda r, _: channel.succeed(f"quota: {r.limit}")),
            or_else=fallback,
        )
    )
    assert (yield from recovered.run_collect()) == ["fallback: RateLimitError"]


# --- unwrapReason ---------------------------------------------------------------


@testing.effect
def test_unwrap_reason_extracts_reason_into_error_channel():
    """extracts reason into error channel"""
    reason = RateLimitError(60)
    ex = yield from _ai(reason).pipe(channel.unwrap_reason(AiError)).run_drain().exit()
    testing.assert_exit_failure(ex, cause.fail(reason))


@testing.effect
def test_unwrap_reason_extracts_second_reason_type():
    """extracts second reason type"""
    reason = QuotaExceededError(100)
    ex = yield from _ai(reason).pipe(channel.unwrap_reason(AiError)).run_drain().exit()
    testing.assert_exit_failure(ex, cause.fail(reason))


@testing.effect
def test_unwrap_reason_preserves_other_errors():
    """preserves other errors"""
    error = OtherError("test")
    ex = yield from _other(error).pipe(channel.unwrap_reason(AiError)).run_drain().exit()
    testing.assert_exit_failure(ex, cause.fail(error))
