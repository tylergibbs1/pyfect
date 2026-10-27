"""Ports of the ``catchReason``, ``catchReasons`` and ``unwrapReason``
sections of Effect's ``Effect.test.ts``.

Each test's docstring is the Effect test title. The parent error's class is
the tag and the reason classes are the reason tags; ``catchReasons``' object
of handlers is ``(reason_class, handler)`` pairs; handlers take
``(reason, error)``. ``Cause.die("finalizer failure")`` holds an exception.
"""

from dataclasses import dataclass

import pyfect as fx
from pyfect import cause, testing


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


def _ai(reason: RateLimitError | QuotaExceededError) -> fx.Effect[str, AiError]:
    return fx.fail(AiError(reason))


def _ai_or_other(error: AiError | OtherError) -> fx.Effect[str, AiError | OtherError]:
    return fx.fail(error)


def _scoped_failure(error: AiError, defect: Exception) -> fx.Effect[str, AiError]:
    @fx.gen
    def body():
        yield from fx.add_finalizer(lambda _: fx.die(defect))
        return (yield from error)

    return fx.scoped(body)


# --- catchReason ----------------------------------------------------------------


@testing.effect
def test_catch_reason_catches_matching_reason_handler_succeeds():
    """catches matching reason - handler succeeds"""
    result = yield from _ai(RateLimitError(60)).pipe(
        fx.catch_reason(AiError, RateLimitError, lambda r, _: fx.succeed(f"retry: {r.retry_after}"))
    )
    assert result == "retry: 60"


@testing.effect
def test_catch_reason_or_else():
    """orElse"""

    def quota(_reason: QuotaExceededError, _error: AiError) -> fx.Effect[str]:
        return fx.succeed("quota")

    result = yield from _ai(QuotaExceededError(100)).pipe(
        fx.catch_reason(
            AiError,
            RateLimitError,
            lambda r, _: fx.succeed(f"retry: {r.retry_after}"),
            or_else=quota,
        )
    )
    assert result == "quota"


@testing.effect
def test_catch_reason_catches_matching_reason_handler_fails():
    """catches matching reason - handler fails"""
    error = OtherError("handled")
    ex = yield from (
        _ai(RateLimitError(60))
        .pipe(fx.catch_reason(AiError, RateLimitError, lambda _r, _e: fx.fail(error)))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


@testing.effect
def test_catch_reason_ignores_non_matching_reason():
    """ignores non-matching reason"""
    reason = QuotaExceededError(100)
    ex = yield from (
        _ai(reason)
        .pipe(fx.catch_reason(AiError, RateLimitError, lambda _r, _e: fx.succeed("no")))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(AiError(reason)))


@testing.effect
def test_catch_reason_preserves_the_cause_for_a_non_matching_reason():
    """preserves the cause for a non-matching reason"""
    error = AiError(QuotaExceededError(100))
    defect = RuntimeError("finalizer failure")
    ex = yield from (
        _scoped_failure(error, defect)
        .pipe(fx.catch_reason(AiError, RateLimitError, lambda _r, _e: fx.succeed("no")))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.die(error) + cause.die(defect))


@testing.effect
def test_catch_reason_ignores_non_matching_parent_tag():
    """ignores non-matching parent tag"""
    error = OtherError("test")
    ex = yield from (
        _ai_or_other(error)
        .pipe(fx.catch_reason(AiError, RateLimitError, lambda _r, _e: fx.succeed("no")))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(error))


# --- catchReasons ---------------------------------------------------------------


@testing.effect
def test_catch_reasons_catches_with_object_handlers():
    """catches with object handlers"""
    result = yield from _ai(RateLimitError(60)).pipe(
        fx.catch_reasons(
            AiError,
            (RateLimitError, lambda r, _: fx.succeed(f"rate: {r.retry_after}")),
            (QuotaExceededError, lambda r, _: fx.succeed(f"quota: {r.limit}")),
        )
    )
    assert result == "rate: 60"


@testing.effect
def test_catch_reasons_or_else():
    """orElse"""

    def fallback(_reason: RateLimitError, _error: AiError) -> fx.Effect[str]:
        return fx.succeed("orElse")

    result = yield from _ai(RateLimitError(60)).pipe(
        fx.catch_reasons(
            AiError,
            (QuotaExceededError, lambda r, _: fx.succeed(f"quota: {r.limit}")),
            or_else=fallback,
        )
    )
    assert result == "orElse"


@testing.effect
def test_catch_reasons_catches_second_reason_type():
    """catches second reason type"""
    result = yield from _ai(QuotaExceededError(100)).pipe(
        fx.catch_reasons(
            AiError,
            (RateLimitError, lambda r, _: fx.succeed(f"rate: {r.retry_after}")),
            (QuotaExceededError, lambda r, _: fx.succeed(f"quota: {r.limit}")),
        )
    )
    assert result == "quota: 100"


@testing.effect
def test_catch_reasons_partial_handlers_unhandled_passes_through():
    """partial handlers - unhandled passes through"""
    reason = QuotaExceededError(100)
    ex = yield from (
        _ai(reason)
        .pipe(fx.catch_reasons(AiError, (RateLimitError, lambda _r, _e: fx.succeed("handled"))))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail(AiError(reason)))


@testing.effect
def test_catch_reasons_preserves_the_cause_for_an_unhandled_reason():
    """preserves the cause for an unhandled reason"""
    error = AiError(QuotaExceededError(100))
    defect = RuntimeError("finalizer failure")
    ex = yield from (
        _scoped_failure(error, defect)
        .pipe(fx.catch_reasons(AiError, (RateLimitError, lambda _r, _e: fx.succeed("handled"))))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.die(error) + cause.die(defect))


# --- unwrapReason ---------------------------------------------------------------


@testing.effect
def test_unwrap_reason_extracts_reason_into_error_channel():
    """extracts reason into error channel"""
    reason = RateLimitError(60)
    ex = yield from _ai(reason).pipe(fx.unwrap_reason(AiError)).exit()
    testing.assert_exit_failure(ex, cause.fail(reason))


@testing.effect
def test_unwrap_reason_extracts_second_reason_type():
    """extracts second reason type"""
    reason = QuotaExceededError(100)
    ex = yield from _ai(reason).pipe(fx.unwrap_reason(AiError)).exit()
    testing.assert_exit_failure(ex, cause.fail(reason))


@testing.effect
def test_unwrap_reason_preserves_other_errors():
    """preserves other errors"""
    error = OtherError("test")
    ex = yield from _ai_or_other(error).pipe(fx.unwrap_reason(AiError)).exit()
    testing.assert_exit_failure(ex, cause.fail(error))
