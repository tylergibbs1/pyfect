"""Numbers in text from outside are parsed by ``pyfect._digits``.

``str.isdigit`` accepts ``"²"``, which ``int`` then rejects with a crash,
and ``int`` alone accepts signs, spaces, underscores and non-ASCII digits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pyfect._digits import parse_digits

SRC = Path(__file__).resolve().parent.parent / "src" / "pyfect"
_BANNED = frozenset({"isdigit", "isdecimal", "isnumeric"})


def test_isdigit_is_called_only_by_parse_digits():
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "_digits.py":
            continue
        tree = ast.parse(path.read_text(), str(path))
        offenders.extend(
            f"{path.relative_to(SRC)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in _BANNED
        )
    assert offenders == [], "use pyfect._digits.parse_digits"


@pytest.mark.parametrize("value", ["", chr(0xB2), chr(0x661), "-1", "+1", " 1", "1 ", "1_0", "0x1"])
def test_parse_digits_refuses_anything_but_ascii_digits(value: str):
    assert parse_digits(value) is None


def test_parse_digits_reads_ascii_digits():
    assert parse_digits("0") == 0
    assert parse_digits("0012") == 12
