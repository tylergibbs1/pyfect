"""Every row of docs/PARITY.md section 4 says what class of difference it is.

- ``a``: spelling or language mapping, the same behaviour.
- ``b: <reason>``: Python or pyright can't express it, and the row says why.
- ``c done``: behaved differently, now does what Effect does.
- ``c open: <why>``: behaves differently and Python could match it; not done.

A row that loses its class, a ``b`` without a reason or an unexplained ``c``
fails here, so the table can't drift from what it claims.
"""

from __future__ import annotations

import re
from pathlib import Path

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
    valid = re.compile(r"a|b: .{10,}|c done|c open: .{5,}")
    assert [row[0] for row in _rows() if not valid.fullmatch(row[-1])] == []


def test_a_class_b_row_names_its_own_reason() -> None:
    """A generic reason says nothing about what Python lacks."""
    generic = {"pythonic", "not ported", "python", "language limit", "cannot express"}
    assert [
        row[0] for row in _rows() if row[-1].startswith("b: ") and row[-1][3:].lower() in generic
    ] == []
