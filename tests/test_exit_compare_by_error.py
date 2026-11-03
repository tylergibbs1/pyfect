"""Comparing a failed ``Exit`` whose cause carries span annotations.

As in Effect (checked under Node: ``Equal.equals`` of a failure inside
``withSpan`` and ``Exit.fail`` of the same error is ``false``), annotations
take part in equality, so ``exit_ == exit.fail(error)`` fails for a failure
raised inside a span. ``testing.assert_exit_fail`` compares by error, and a
failed ``==`` says when the sides differ only in annotations."""

from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import exit, testing


@dataclass
class Rejected(fx.TaggedError):
    by: str


def _in_span(effect: fx.Effect[object, Rejected]) -> fx.Exit[object, Rejected]:
    return fx.run_sync_exit(effect.with_span("hold-budget"))


def test_a_failure_inside_a_span_is_not_equal_to_the_bare_failure_as_in_effect():
    assert _in_span(fx.fail(Rejected("grace"))) != exit.fail(Rejected("grace"))


def test_assert_exit_fail_compares_by_error_ignoring_annotations():
    testing.assert_exit_fail(_in_span(fx.fail(Rejected("grace"))), Rejected("grace"))


def test_assert_exit_fail_reports_another_error_with_the_pretty_cause():
    with pytest.raises(AssertionError, match=r"(?s)expected Failure.*Rejected.*'bob'.*got.*grace"):
        testing.assert_exit_fail(_in_span(fx.fail(Rejected("grace"))), Rejected("bob"))


def test_assert_exit_fail_refuses_a_success_or_a_defect_beside_the_error():
    with pytest.raises(AssertionError, match=r"got Success\(value=1\)"):
        testing.assert_exit_fail(fx.run_sync_exit(fx.succeed(1)), Rejected("grace"))
    both = fx.run_sync_exit(
        fx.fail(Rejected("grace")).ensuring(fx.die(ValueError("cleanup broke")))
    )
    with pytest.raises(AssertionError, match="cleanup broke"):
        testing.assert_exit_fail(both, Rejected("grace"))


def test_a_failed_comparison_says_the_sides_differ_only_in_annotations(
    pytester: pytest.Pytester,
):
    pytester.makepyfile(
        """
        import pyfect as fx
        from pyfect import exit

        def test_compare():
            ex = fx.run_sync_exit(fx.fail("no").with_span("hold-budget"))
            assert ex == exit.fail("no")
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            "*equal but for their annotations*",
            "*left Fail(error='no') annotations: StackTrace*hold-budget*",
            "*right Fail(error='no') annotations: none*",
            "*testing.assert_exit_fail*",
        ]
    )
