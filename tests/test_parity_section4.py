"""Every row of docs/PARITY.md section 4 says what class of difference it is.

- ``a``: spelling or language mapping, the same behaviour.
- ``b: <reason>``: Python or pyright can't express it, and the row says why.
- ``c done``: behaved differently, now does what Effect does.
- ``c kept: <why>``: behaves differently, and the user decided to keep it (§5).
- ``c open: <why>``: behaves differently and Python could match it; not done.

A row that loses its class, a ``b`` without a reason or an unexplained ``c``
fails here, so the table can't drift from what it claims.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

_PARITY = Path(__file__).parent.parent / "docs" / "PARITY.md"
_CELL = re.compile(r"(?<!\\)\|")


def _rows() -> list[list[str]]:
    text = _PARITY.read_text()
    start = text.index("## 4. Pythonic decisions")
    section = text[start : text.index("\n## 5.", start)]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in _CELL.split(line)[1:-1]] for line in lines[2:]]


def test_section_four_has_rows() -> None:
    assert len(_rows()) > 400


def test_every_row_has_four_cells() -> None:
    assert [row[0] for row in _rows() if len(row) != 4] == []


def test_every_row_has_a_valid_class() -> None:
    valid = re.compile(r"a|b: .{10,}|c done|c kept: .{10,}|c open: .{5,}")
    assert [row[0] for row in _rows() if not valid.fullmatch(row[-1])] == []


def _class_counts() -> Counter[str]:
    return Counter(row[-1].split(":")[0] for row in _rows())


def test_the_recorded_class_counts_are_the_tables() -> None:
    """Hand-carried counts drifted once (76 open rows, when 74 were)."""
    found = re.search(
        r"Counts after the merge: a (\d+), b (\d+), c done (\d+), c kept (\d+), c open (\d+)",
        _PARITY.read_text(),
    )
    assert found is not None
    counts = _class_counts()
    assert tuple(map(int, found.groups())) == (
        counts["a"],
        counts["b"],
        counts["c done"],
        counts["c kept"],
        counts["c open"],
    )


@pytest.mark.parametrize(
    "reason",
    ["c kept: security hardening, decided by the user", "c kept: Effect bug, decided by the user"],
)
def test_section_five_states_how_many_rows_each_decision_covers(reason: str) -> None:
    text = _PARITY.read_text()
    section = text[text.index("\n## 5.") : text.index("\n## 6.")]
    count = sum(row[-1].startswith(reason) for row in _rows())
    assert f"({count} §4 rows, `{reason}`)" in section


def test_a_class_b_row_names_its_own_reason() -> None:
    """A generic reason says nothing about what Python lacks."""
    generic = {"pythonic", "not ported", "python", "language limit", "cannot express"}
    assert [
        row[0] for row in _rows() if row[-1].startswith("b: ") and row[-1][3:].lower() in generic
    ] == []
