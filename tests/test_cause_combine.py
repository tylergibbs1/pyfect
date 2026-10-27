"""``Cause.__add__`` (Effect's ``combine``): no reason is ever lost."""

from itertools import product

from pyfect import cause
from pyfect.cause import Cause, Fail, Interrupt, Reason

_REASONS: tuple[Reason[int], ...] = (Fail(1), Fail(2), Interrupt(1))


def _all_causes(max_len: int) -> list[Cause[int]]:
    """Every cause of up to ``max_len`` reasons, repeats included, as
    ``from_reasons`` allows."""
    return [
        cause.from_reasons(rs) for n in range(max_len + 1) for rs in product(_REASONS, repeat=n)
    ]


def test_combining_keeps_every_reason_of_both_causes_once_in_order() -> None:
    for left, right in product(_all_causes(3), repeat=2):
        expected = tuple(dict.fromkeys((*left.reasons, *right.reasons)))
        combined = left + right
        if left.reasons and right.reasons:
            assert combined.reasons == expected, (left, right)
        else:
            assert combined is (right if not left.reasons else left)


def test_a_cause_with_repeats_does_not_swallow_a_new_reason() -> None:
    repeated = cause.from_reasons([Fail(1), Fail(1)])
    assert (repeated + cause.fail(2)).reasons == (Fail(1), Fail(2))
