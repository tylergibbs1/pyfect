"""Every entry in an inventory of rule exceptions says why it is there."""

from __future__ import annotations

import pytest
from _inventory import Entry, InventoryError, parse


def test_an_entry_with_its_reason_parses() -> None:
    text = "# a comment\n\na.py::t 10 seconds  # a real PostgreSQL lock_timeout of 2 s\n"
    assert parse(text) == {"a.py::t": Entry("10 seconds", "a real PostgreSQL lock_timeout of 2 s")}


def test_an_entry_without_a_reason_is_refused() -> None:
    with pytest.raises(InventoryError, match=r"line 1: a\.py::t has no reason"):
        parse("a.py::t 10 seconds\n")


@pytest.mark.parametrize("reason", ["slow", "flaky test", "  "])
def test_a_reason_that_names_nothing_is_refused(reason: str) -> None:
    with pytest.raises(InventoryError, match=r"line 1: a\.py::t"):
        parse(f"a.py::t 10 seconds  # {reason}\n")


def test_every_bad_line_is_named() -> None:
    with pytest.raises(InventoryError, match=r"line 1: a\.py::t(.|\n)*line 2: b\.py::u"):
        parse("a.py::t 10 seconds\nb.py::u 2  # slow\n")


def test_an_entry_listed_twice_is_refused() -> None:
    text = "a.py::t 10 seconds  # a real lock timeout\na.py::t 20 seconds  # a real lock timeout\n"
    with pytest.raises(InventoryError, match=r"line 2: a\.py::t is listed twice"):
        parse(text)


@pytest.mark.parametrize(
    "reason",
    [
        "no real-time dependency: runs on the TestClock",
        "No real-time dependency, pure CPU work",
        "none: everything runs in memory",
        "not needed: could use the TestClock",
    ],
)
def test_a_reason_that_says_there_is_none_is_refused(reason: str) -> None:
    with pytest.raises(InventoryError, match=r"line 1: a\.py::t"):
        parse(f"a.py::t 10 seconds  # {reason}\n")
