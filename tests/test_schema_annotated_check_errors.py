"""A check in a field's `Annotated` metadata that doesn't fit the field's type (a length check
on an int) fails where the class is defined, naming the field and the check, as Effect's
compiler rejects it: pyright can't see a check inside `Annotated`. The check is tried on a value
of each primitive kind the type holds (string, number, boolean, None, literal, array); a check
that raises `TypeError` or `AttributeError` there doesn't fit.

Where that can't decide (a declaration such as `bytes`, a class), a check that raises on a value
still raises a `TypeError` naming the field and the check, chained from what it raised, instead
of `RuntimeError: Constructor adapter can only throw schema issues`.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

import pytest

from pyfect import schema as S
from pyfect.schema._check_guard import CheckRaisedError

_BIN = (
    "Bin.count: the check is_min_length (a value with a length of at least 1) cannot check "
    "number values: on 0 it raised TypeError: object of type 'int' has no len(). "
    "Give the field a check that fits its type"
)


def test_defining_the_class_names_the_field_and_the_check():
    with pytest.raises(TypeError) as raised:

        class Bin(S.Class):  # pyright: ignore[reportUnusedClass]
            count: Annotated[int, S.is_min_length(1)]

    assert str(raised.value) == _BIN
    assert isinstance(raised.value.__cause__, TypeError)
    assert str(raised.value.__cause__) == "object of type 'int' has no len()"


def test_a_number_check_on_a_string_fails_too():
    with pytest.raises(TypeError, match=r"^Code\.s: the check is_greater_than .* string values"):

        class Code(S.Class):  # pyright: ignore[reportUnusedClass]
            s: Annotated[str, S.is_greater_than(0)]


def test_a_union_fails_when_the_check_does_not_fit_one_member():
    with pytest.raises(TypeError, match=r"^Mixed\.v: the check is_min_length .* number values"):

        class Mixed(S.Class):  # pyright: ignore[reportUnusedClass]
            v: Annotated[int | str, S.is_min_length(1)]


def test_a_default_or_an_optional_field_does_not_excuse_it():
    with pytest.raises(TypeError, match=r"^WithDefault\.count: the check is_min_length "):

        class WithDefault(S.Class):  # pyright: ignore[reportUnusedClass]
            count: Annotated[int, S.is_min_length(1)] = 0

    with pytest.raises(TypeError, match=r"^Maybe\.count: the check is_min_length "):

        class Maybe(S.Class):  # pyright: ignore[reportUnusedClass]
            count: Annotated[int, S.is_min_length(1)] | None = None


def test_a_check_inside_a_container_names_the_field():
    with pytest.raises(TypeError, match=r"^Rows\.xs: the check is_min_length "):

        class Rows(S.Class):  # pyright: ignore[reportUnusedClass]
            xs: list[Annotated[int, S.is_min_length(1)]]


def test_a_check_without_a_name_is_called_a_check():
    with pytest.raises(TypeError, match=r"^Custom\.n: the check cannot check number values"):

        class Custom(S.Class):  # pyright: ignore[reportUnusedClass]
            n: Annotated[int, S.make_filter(lambda s: len(s) > 0)]  # pyright: ignore[reportArgumentType]


def test_a_typed_dict_key_is_named_too():
    class Line(TypedDict):
        quantity: Annotated[int, S.is_min_length(1)]

    with pytest.raises(CheckRaisedError, match=r"^Line\['quantity'\]: the check is_min_length "):
        S.Struct(Line)


def _none_or_non_empty(s: str | None) -> bool:
    return s is None or len(s) > 0


def test_checks_that_fit_define_and_still_check():
    class Fits(S.Class):
        name: Annotated[str, S.is_min_length(1)]
        count: Annotated[int, S.is_greater_than(0)]
        tags: Annotated[tuple[str, ...], S.is_max_length(2)]
        mode: Annotated[Literal["a", "bc"], S.is_min_length(1)]
        note: Annotated[str | None, S.make_filter(_none_or_non_empty)] = None

    assert Fits(name="x", count=1, tags=(), mode="bc").count == 1
    with pytest.raises(S.SchemaError):
        Fits(name="", count=1, tags=(), mode="a")


def test_a_check_on_a_declaration_still_names_the_field_when_it_raises():
    class Blob(S.Class):
        data: Annotated[bytes, S.is_greater_than(0)]

    with pytest.raises(TypeError) as raised:
        Blob(data=b"x")
    assert str(raised.value).startswith(
        "Blob.data: the check is_greater_than (a value greater than 0) raised on b'x': TypeError: "
    )
    assert isinstance(raised.value.__cause__, TypeError)
