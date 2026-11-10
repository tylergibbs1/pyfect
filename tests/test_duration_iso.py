"""ISO 8601 duration text as whole nanoseconds (``pyfect._duration_iso``), the parser and
printer behind ``S.DurationFromIsoString``: every value here was printed by Effect 4.1.2's
``Duration.fromIso`` / ``formatIso`` under Node."""

import pytest

from pyfect._duration_iso import format_iso_nanos, parse_iso_nanos


@pytest.mark.parametrize(
    ("text", "nanos"),
    [
        ("P1W2D", 777_600_000_000_000),
        ("PT1H30M", 5_400_000_000_000),
        ("-PT1.5S", -1_500_000_000),
        ("PT0.000000001S", 1),
        ("+P1D", 86_400_000_000_000),
        ("PT1,5M", 90_000_000_000),
        ("PT0S", 0),
        ("-PT0S", 0),
        ("P1Y", None),
        ("P1M", None),
        ("1 second", None),
        ("P", None),
        ("PT", None),
        ("PT1.5H30M", None),
        ("P1.5D", None),
        ("PT1H\n", None),
        ("p1d", None),
    ],
)
def test_parse(text: str, nanos: int | None) -> None:
    assert parse_iso_nanos(text) == nanos


@pytest.mark.parametrize(
    ("nanos", "text"),
    [
        (0, "PT0S"),
        (604_800_000_000_000, "P7D"),
        (-1, "-PT0.000000001S"),
        (93_600_000_000_000, "P1DT2H"),
        (-1_500_000_000, "-PT1.5S"),
        (5_400_000_000_005, "PT1H30M0.000000005S"),
    ],
)
def test_format(nanos: int, text: str) -> None:
    assert format_iso_nanos(nanos) == text
