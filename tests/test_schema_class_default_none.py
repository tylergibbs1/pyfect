"""A field whose default is ``None`` but whose schema refuses ``None`` says how to fix it.

``n: int | None = S.field(S.Int, default=None)`` decodes a missing key to ``None`` and then
cannot construct or encode that ``None``. The error says what the field needs:
``S.NullOr(S.Int)``, or ``S.Union(S.Int, S.Undefined)`` to leave the key out while it is None.
"""

from __future__ import annotations

import pytest

from pyfect import schema as S

_HINT = (
    "Expected number, and the default None is not one: write S.NullOr(schema) for a field that "
    "may be None, or S.Union(schema, S.Undefined) to leave the key out while it is None\n"
    '  at ["n"]'
)


class Misdefined(S.Class):
    n: int | None = S.field(S.Int, default=None)


class Absent(S.Class):
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class Nullable(S.Class):
    n: int | None = S.field(S.NullOr(S.Int), default=None)


def test_constructing_or_encoding_the_default_none_says_what_the_field_needs() -> None:
    with pytest.raises(S.SchemaError) as constructing:
        Misdefined()
    assert str(constructing.value) == _HINT
    decoded = S.decode_unknown_sync(Misdefined)({})
    with pytest.raises(S.SchemaError) as encoding:
        S.encode_sync(Misdefined)(decoded)
    assert str(encoding.value) == _HINT


def test_the_hint_keeps_check_failures_and_good_values_as_they_were() -> None:
    class Positive(S.Class):
        n: int | None = S.field(S.Int.check(S.is_greater_than(0)), default=None)

    with pytest.raises(S.SchemaError, match=r"^Expected a value greater than 0\n"):
        Positive(n=-1)
    assert S.encode_sync(Misdefined)(Misdefined(n=1)) == {"n": 1}


def test_a_field_whose_schema_takes_none_gets_no_hint() -> None:
    assert S.encode_sync(Absent)(Absent()) == {}
    assert S.encode_sync(Nullable)(Nullable()) == {"n": None}
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(Nullable)({"n": "x"})
    assert "default" not in str(error.value)
