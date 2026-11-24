"""A field's default must be a value of its schema's type, and a class whose default isn't fails
where it is defined, naming the field and saying what it needs.

pyright accepts ``n: int | None = S.field(S.Int, default=None)``: a ``Codec`` is covariant (as
Effect's is), so ``S.Int`` reads as a ``Codec[int | None]``. Effect's compiler rejects such a
constructor default, so the class definition does here. A ``None`` default gets the fix
``S.NullOr(S.Int)``, or ``S.Union(S.Int, S.Undefined)`` to leave the key out while it is None.
The default's checks run at construction, as Effect's do, and a schema naming a class not
defined yet is checked on first use.
"""

from __future__ import annotations

import pytest

from pyfect import schema as S

_HINT = (
    "Expected number, and the default None is not one: write S.NullOr(schema) for a field that "
    "may be None, or S.Union(schema, S.Undefined) to leave the key out while it is None"
)


class Absent(S.Class):
    n: int | None = S.field(S.Union(S.Int, S.Undefined), default=None)


class Nullable(S.Class):
    n: int | None = S.field(S.NullOr(S.Int), default=None)


def test_a_none_default_the_schema_refuses_fails_at_definition() -> None:
    with pytest.raises(TypeError) as raised:

        class Misdefined(S.Class):  # pyright: ignore[reportUnusedClass]
            n: int | None = S.field(S.Int, default=None)

    assert str(raised.value) == f"Misdefined.n: {_HINT}"


def test_any_default_of_another_type_fails_at_definition() -> None:
    with pytest.raises(TypeError) as raised:

        class Wrong(S.Class):  # pyright: ignore[reportUnusedClass]
            n: int | str = S.field(S.Int, default="a")

    assert str(raised.value) == (
        "Wrong.n: Expected number, and the default 'a' is not one: give the field a default of "
        "its schema's type, or a schema that takes it"
    )


def test_a_default_failing_only_a_check_fails_at_construction() -> None:
    class Positive(S.Class):
        n: int = S.field(S.Int.check(S.is_greater_than(0)), default=0)

    assert Positive(n=1).n == 1
    with pytest.raises(S.SchemaError, match=r"^Expected a value greater than 0\n"):
        Positive()


def test_a_schema_naming_a_later_class_is_checked_on_first_use() -> None:
    class Holder(S.Class):
        n: Later | None = S.field(S.suspend(lambda: Later), default=None)

    class Later(S.Class):
        v: int

    with pytest.raises(S.SchemaError, match=r"^Expected Later\n"):
        Holder()


def test_a_field_whose_schema_takes_none_gets_no_hint() -> None:
    assert S.encode_sync(Absent)(Absent()) == {}
    assert S.encode_sync(Nullable)(Nullable()) == {"n": None}
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(Nullable)({"n": "x"})
    assert "default" not in str(error.value)
