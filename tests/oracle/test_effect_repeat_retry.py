"""Ports of the ``repeat`` and ``retry`` sections of Effect's ``Effect.test.ts``
that the current ``Schedule`` already supports.

Each test's docstring is the Effect test title. Omitted, with the reason:

- "preserves finalizer defects accompanying schedule completion",
  "repeatOrElse passes source Done failures and iteration metadata to
  orElse", "retry/schedule - CurrentMetadata": need ``Schedule.from_step``,
  ``repeat_or_else`` and schedule metadata, which come with the M3
  ``Schedule`` rewrite.
- "repeat/until", "repeat/while", "repeat/times", "repeat/schedule",
  "retry/until", "retry/while", "retry/schedule" (every title) and "nothing
  on success" (``retry({ times })``): the ``repeat`` / ``retry`` option
  forms are M3's Effect integration, ported with them.
"""

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cause import Die, Fail


@testing.effect
def test_fails_with_a_done_raised_by_the_repeated_effect():
    """fails with a Done raised by the repeated effect"""
    # Effect's ``Cause.done(42)`` carries a value; pyfect's ``Done`` has none
    # until ``Pull`` (M6).
    ex = yield from fx.fail(fx.Done()).repeat(schedule.recurs(3)).exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Fail(fx.Done()),)


@testing.effect
def test_is_interruptible():
    """is interruptible"""
    fiber = yield from fx.void.forever().timeout_option(0.05).fork()
    yield from testing.adjust(0.05)
    assert (yield from fiber.join()) is None


@testing.effect
def test_does_not_retry_typed_failures_accompanied_by_finalizer_defects():
    """does not retry typed failures accompanied by finalizer defects"""
    attempts = 0
    cleanup_failed = RuntimeError("cleanup failed")

    def source() -> fx.Effect[None, str]:
        nonlocal attempts
        attempts += 1
        return fx.fail("error").ensuring(fx.die(cleanup_failed))

    ex = yield from fx.suspend(source).retry(schedule.recurs(1)).exit()
    assert attempts == 1
    assert isinstance(ex, fx.Failure)
    # Effect dies with the raw error "error"; a pyfect defect is an exception,
    # so the unhandled typed error is wrapped in ``UnhandledError``.
    first, second = ex.cause.reasons
    assert isinstance(first, Die)
    assert isinstance(first.defect, fx.UnhandledError)
    assert first.defect.error == "error"
    assert second == Die(cleanup_failed)
