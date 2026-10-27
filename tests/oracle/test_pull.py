"""Ports of Effect's ``Pull.test.ts``.

Each test's docstring is the Effect test title. ``Cause.die("boom")`` holds
an exception here, since a defect is a ``BaseException`` in pyfect.
"""

import pyfect as fx
from pyfect import cause, pull

BOOM = RuntimeError("boom")


def test_filter_done_succeeds_when_the_done_signal_is_the_only_failure():
    """succeeds when the done signal is the only failure"""
    result = pull.filter_done(cause.fail(fx.Done("leftover")))
    assert result == fx.Ok(fx.Done("leftover"))


def test_filter_done_strips_the_done_signal_when_merged_with_other_failures():
    """strips the done signal when merged with other failures"""
    merged = cause.fail(fx.Done("leftover")) + cause.die(BOOM)
    assert pull.filter_done(merged) == fx.Err(cause.die(BOOM))


def test_filter_done_fails_with_the_original_cause_when_no_done_signal_is_present():
    """fails with the original cause when no done signal is present"""
    failed = cause.fail("error")
    assert pull.filter_done(failed) == fx.Err(failed)


def test_filter_done_succeeds_when_the_done_signal_is_merged_only_with_interruptions():
    """succeeds when the done signal is merged only with interruptions"""
    merged = cause.interrupt(1) + cause.fail(fx.Done("leftover"))
    assert pull.filter_done(merged) == fx.Ok(fx.Done("leftover"))


def test_done_exit_from_cause_treats_a_pure_done_cause_as_success():
    """treats a pure done cause as success"""
    ex = pull.done_exit_from_cause(cause.fail(fx.Done("leftover")))
    assert ex == fx.Success("leftover")


def test_done_exit_from_cause_fails_with_the_stripped_cause_when_merged_with_a_failure():
    """fails with the stripped cause when the done signal was merged with a failure"""
    merged = cause.fail(fx.Done("leftover")) + cause.die(BOOM)
    assert pull.done_exit_from_cause(merged) == fx.Failure(cause.die(BOOM))
