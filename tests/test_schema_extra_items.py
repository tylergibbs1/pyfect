"""``S.Struct`` over a PEP 728 TypedDict: ``extra_items=`` types the keys the
TypedDict does not declare (Effect's ``StructWithRest`` of a string
record). Unlike a TypeScript index signature, it does not cover the
declared keys."""

from typing import ReadOnly

import pytest
from typing_extensions import TypedDict

from pyfect import schema as S


class Scores(TypedDict, extra_items=int):
    name: str


class Frozen(TypedDict, extra_items=ReadOnly[int]):
    name: str


class Closed(TypedDict, closed=True):
    name: str


def test_undeclared_keys_take_the_extra_items_type():
    decode = S.decode_unknown_sync(S.Struct(Scores))
    assert decode({"name": "a", "x": 1, "y": 2}) == {"name": "a", "x": 1, "y": 2}
    with pytest.raises(S.SchemaError, match=r'^Expected number\n  at \["x"\]$'):
        decode({"name": "a", "x": "1"})


def test_declared_keys_keep_their_own_type():
    assert S.decode_unknown_sync(S.Struct(Scores))({"name": "a"}) == {"name": "a"}


def test_read_only_extra_items_take_the_inner_type():
    decode = S.decode_unknown_sync(S.Struct(Frozen))
    assert decode({"name": "a", "x": 1}) == {"name": "a", "x": 1}
    with pytest.raises(S.SchemaError):
        decode({"name": "a", "x": "1"})


def test_a_closed_typed_dict_drops_undeclared_keys():
    decode = S.decode_unknown_sync(S.Struct(Closed))
    assert decode({"name": "a", "x": 1}) == {"name": "a"}
    with pytest.raises(S.SchemaError, match="Expected no excess property"):
        decode({"name": "a", "x": 1}, on_excess_property="error")


def test_the_json_codec_writes_the_extra_keys():
    codec = S.to_codec_json(S.Struct(Scores))
    assert S.encode_sync(codec)({"name": "a", "x": 1}) == {"name": "a", "x": 1}
