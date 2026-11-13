"""How a parameter is written into a text-protocol statement, in each quoting mode.

Under ``NO_BACKSLASH_ESCAPES`` a backslash is plain text, so a literal written with
backslash escapes ends early and the rest of the value runs as SQL. Every value that holds
text must be written for the session's mode; the real-server round trips are in
``tests/oracle/test_sql_hostile_round_trip.py``.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("asyncmy")

from pyfect.sql.mysql._literal import text_literal

_NBE = text_literal(no_backslash_escapes=True)
_DEFAULT = text_literal(no_backslash_escapes=False)


@pytest.mark.parametrize(
    ("value", "nbe", "default"),
    [
        ("it's \\", "'it''s \\'", "'it\\'s \\\\'"),
        (b"' AS b --\\", "X'272041532062202d2d5c'", "X'272041532062202d2d5c'"),
        (bytearray(b"\x00"), "X'00'", "X'00'"),
        (b"", "X''", "X''"),
        (("a'", ("\\",)), "('a''',('\\'))", "('a\\'',('\\\\'))"),
        (["a'", ["b\\"]], "'a''', ('b\\')", "'a\\'', ('b\\\\')"),
        ({"k": "'\\"}, "'{\"k\":\"''\\\\\"}'", '\'{\\"k\\":\\"\\\'\\\\\\\\\\"}\''),
        (uuid.UUID(int=1), f"'{uuid.UUID(int=1)}'", f"'{uuid.UUID(int=1)}'"),
        (None, "NULL", "NULL"),
        (True, "1", "1"),
        (Decimal("-1.50"), "-1.50", "-1.50"),
    ],
)
def test_each_value_is_written_for_the_sessions_mode(value: object, nbe: str, default: str):
    assert _NBE(value, False) == nbe
    assert _DEFAULT(value, False) == default


def test_any_other_value_is_its_text_in_the_sessions_mode():
    class Named:
        def __str__(self) -> str:
            return "x\\' OR 1=1 -- "

    assert _NBE(Named(), False) == "'x\\'' OR 1=1 -- '"
    assert _DEFAULT(Named(), False) == "'x\\\\\\' OR 1=1 -- '"


def test_a_set_assignment_list_writes_its_values_in_the_sessions_mode():
    assert _NBE({"a`b": "\\'"}, True) == "`a``b` = '\\'''"
