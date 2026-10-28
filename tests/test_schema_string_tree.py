"""``S.to_codec_string_tree``: a schema's values read from and written as a
tree of strings."""

from typing import NotRequired, TypedDict

import pytest

from pyfect import schema as S


class _Payload(TypedDict):
    n: int
    ok: bool
    tags: tuple[float, ...]
    nothing: None
    note: NotRequired[str]


_PAYLOAD = S.to_codec_string_tree(S.Struct(_Payload))


def test_every_leaf_is_written_as_text():
    value: _Payload = {"n": 1, "ok": True, "tags": (1.5, 2.0), "nothing": None}

    assert S.encode_sync(_PAYLOAD)(value) == {
        "n": "1",
        "ok": "true",
        "tags": ("1.5", "2"),
        "nothing": "null",
    }


def test_text_leaves_decode_to_the_schema_type():
    tree = {"n": "1", "ok": "false", "tags": ["1.5"], "nothing": "null", "note": "hi"}

    assert S.decode_unknown_sync(_PAYLOAD)(tree) == {
        "n": 1,
        "ok": False,
        "tags": (1.5,),
        "nothing": None,
        "note": "hi",
    }


def test_numeric_union_members_are_tried_before_string_ones():
    codec = S.to_codec_string_tree(S.Union(S.String, S.Number))

    assert S.decode_unknown_sync(codec)("3") == 3
    assert S.decode_unknown_sync(codec)("three") == "three"


def test_non_finite_numbers_and_literals_are_written_as_text():
    assert S.encode_sync(S.to_codec_string_tree(S.Number))(float("inf")) == "Infinity"
    assert S.encode_sync(S.to_codec_string_tree(S.Literal(5)))(5) == "5"


def test_invalid_text_fails_with_the_leaf_message():
    with pytest.raises(S.SchemaError, match="Expected a string representing a finite number"):
        S.decode_unknown_sync(S.to_codec_string_tree(S.Int))("x")


def test_unknown_values_are_kept_as_any_string_tree():
    codec = S.to_codec_string_tree(S.Unknown)

    assert S.decode_unknown_sync(codec)({"a": ["b"]}) == {"a": ["b"]}
    with pytest.raises(S.SchemaError, match="StringTree"):
        S.decode_unknown_sync(codec)({"a": 1})
