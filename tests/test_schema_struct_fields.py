"""``S.Struct(TypedDict, key=schema)``: the schema given for a key must decode
to values of the key's annotation (QA types 1). Pyright cannot check a keyword
argument against a TypedDict key (``research/typing/schema_6_struct_overrides.py``),
so ``Struct`` checks it when the struct is made, and rejects only a schema it
can tell is wrong."""

from collections.abc import Sequence
from typing import Literal, NotRequired, TypedDict

import pytest

from pyfect import schema as S


class Line(TypedDict):
    sku: str
    quantity: int


@pytest.mark.parametrize(
    ("schema", "decodes_to"),
    [(S.String, "string"), (S.NumberFromString, "number"), (S.Finite, "number")],
)
def test_a_schema_decoding_to_another_type_is_rejected(
    schema: S.Codec[object, object, object, object], decodes_to: str
):
    with pytest.raises(
        TypeError, match=rf"^Line\['quantity'\] is int, but its schema decodes to {decodes_to}$"
    ):
        S.Struct(Line, quantity=schema)


class Mode(TypedDict):
    mode: Literal["read", "write"]


def test_a_wider_literal_union_is_rejected_and_a_narrower_one_kept():
    with pytest.raises(TypeError, match=r"Mode\['mode'\]"):
        S.Struct(Mode, mode=S.Literals("read", "write", "append"))
    with pytest.raises(TypeError, match=r"Mode\['mode'\]"):
        S.Struct(Mode, mode=S.String)
    narrow = S.Struct(Mode, mode=S.Literal("read"))
    assert S.decode_unknown_sync(narrow)({"mode": "read"}) == {"mode": "read"}


class Price(TypedDict):
    amount: float
    count: int
    note: str | None
    tags: Sequence[str]
    when: NotRequired[object]
    flag: int


def test_transformations_and_refinements_of_the_annotated_type_are_kept():
    schema = S.Struct(
        Price,
        amount=S.NumberFromString,  # float
        count=S.Int.check(S.is_greater_than(0)),  # int, refined
        note=S.NullOr(S.String.check(S.is_min_length(1))),
        tags=S.List(S.String),  # a list is a Sequence
        flag=S.Boolean,  # a bool is an int
    )
    decoded = S.decode_unknown_sync(schema)(
        {"amount": "1.5", "count": 2, "note": None, "tags": ["a"], "flag": True}
    )
    assert decoded == {"amount": 1.5, "count": 2, "note": None, "tags": ["a"], "flag": True}


class Listed(TypedDict):
    items: list[int]


def test_a_tuple_for_a_list_is_rejected():
    with pytest.raises(TypeError, match=r"Listed\['items'\] is list\[int\]"):
        S.Struct(Listed, items=S.Array(S.Int))
    assert S.decode_unknown_sync(S.Struct(Listed, items=S.List(S.Int)))({"items": [1]}) == {
        "items": [1]
    }


class Tagged(TypedDict):
    _tag: Literal["Square"]
    side: float


def test_tagged_structs_are_checked_too():
    with pytest.raises(TypeError, match=r"Tagged\['side'\] is float"):
        S.TaggedStruct(Tagged, side=S.String)
