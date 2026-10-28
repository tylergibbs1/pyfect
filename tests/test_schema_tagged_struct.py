"""``S.TaggedStruct`` checks its TypedDict at the boundary: a case of a
tagged union always holds one literal under ``"_tag"``."""

from typing import Literal, NotRequired, ReadOnly, TypedDict

import pytest

from pyfect import schema as S


class Untagged(TypedDict):
    a: str


class TwoTags(TypedDict):
    _tag: Literal["A", "B"]


class StringTag(TypedDict):
    _tag: str


class OptionalTag(TypedDict):
    _tag: NotRequired[Literal["A"]]


class ReadOnlyTag(TypedDict):
    _tag: ReadOnly[Literal["A"]]


@pytest.mark.parametrize("typed_dict", [Untagged, TwoTags, StringTag, OptionalTag])
def test_a_typed_dict_without_one_required_literal_tag_is_rejected(typed_dict: type):
    with pytest.raises(TypeError, match=r'needs a required "_tag" key of one literal$'):
        S.TaggedStruct(typed_dict)


def test_a_read_only_literal_tag_is_a_tag():
    schema = S.TaggedStruct(ReadOnlyTag)
    assert schema.tag == "A"
    assert S.TaggedUnion(schema).discriminants == ("A",)
