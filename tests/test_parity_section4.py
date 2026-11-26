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

import pytest
from _parity_counts import PARITY, WRITE, BadRow, Row, rewrite, section_four


def _rows() -> list[Row]:
    return section_four(PARITY.read_text())


def test_section_four_has_rows() -> None:
    assert len(_rows()) > 400


def test_a_row_split_by_an_unescaped_bar_is_named_with_its_line() -> None:
    """A ``|`` in a backticked cell still ends the cell, so the row has a cell too many."""
    text = (
        "## 4. Pythonic decisions\n\n| Feature | Mapping | Why | Class |\n|---|---|---|---|\n"
        "| `Option` | `fx.Option` | same | a |\n"
        "| `A | B` unions | `A \\| B` | same | a |\n\n## 5. Open\n"
    )
    with pytest.raises(BadRow) as raised:
        section_four(text)
    assert str(raised.value) == (
        "docs/PARITY.md:6: the §4 row '`A' has 5 cells, not 4. A `|` inside a cell, "
        "backticked or not, ends the cell: write it `\\|`."
    )


def test_every_row_has_a_valid_class() -> None:
    valid = re.compile(r"a|b: .{10,}|c done|c kept: .{10,}|c open: .{5,}")
    assert [row.feature for row in _rows() if not valid.fullmatch(row.kind)] == []


def test_the_recorded_counts_are_the_tables() -> None:
    """§4's class counts and §5's row counts per decision. Hand-carried counts drifted once
    (76 open rows, when 74 were)."""
    stale = rewrite(PARITY.read_text(), open_titles=None).stale
    assert not stale, f"docs/PARITY.md: {stale}; run `{WRITE}`"


def test_a_rewrite_puts_back_every_count_it_keeps() -> None:
    text = PARITY.read_text()
    wrong = re.sub(r"(Counts after the merge: [^\n]*?c open )\d+", r"\g<1>999", text)
    wrong = re.sub(
        r"\((\d+) §4 rows, `c kept: Effect bug", r"(999 §4 rows, `c kept: Effect bug", wrong
    )
    wrong = re.sub(r"\d+ titles NOT_PORTED, all open", "999 titles NOT_PORTED, all open", wrong)
    done = rewrite(wrong, open_titles=7)
    assert len(done.stale) == 3, done.stale
    assert done.text == re.sub(
        r"\d+ titles NOT_PORTED, all open", "7 titles NOT_PORTED, all open", text
    )


@pytest.mark.parametrize(
    "reason",
    ["c kept: security hardening, decided by the user", "c kept: Effect bug, decided by the user"],
)
def test_section_five_states_how_many_rows_each_decision_covers(reason: str) -> None:
    text = PARITY.read_text()
    section = text[text.index("\n## 5.") : text.index("\n## 6.")]
    assert re.search(rf"\(\d+ §4 rows, `{re.escape(reason)}`\)", section)


def test_a_class_b_row_names_its_own_reason() -> None:
    """A generic reason says nothing about what Python lacks."""
    generic = {"pythonic", "not ported", "python", "language limit", "cannot express"}
    assert [
        row.feature
        for row in _rows()
        if row.kind.startswith("b: ") and row.kind[3:].lower() in generic
    ] == []
