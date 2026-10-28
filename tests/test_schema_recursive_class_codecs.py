"""A schema class that refers to itself (no ``S.suspend``: the class shape
is lazy) goes through every derivation that rebuilds a schema: the JSON and
string-tree codecs, ``config.schema`` and the pydantic hook."""

from __future__ import annotations

import pytest

import pyfect as fx
from pyfect import config
from pyfect import config_provider as cp
from pyfect import schema as S


class User(S.Class):
    name: str
    age: int = S.field(S.Int, default=0)
    friend: User | None = None


_NESTED = User(name="a", age=1, friend=User(name="b", age=2))


def test_the_json_codec_of_a_self_referring_class_decodes_and_encodes_nested_values():
    codec = S.to_codec_json(User)
    encoded = {"name": "a", "age": 1, "friend": {"name": "b", "age": 2, "friend": None}}

    assert S.decode_unknown_sync(codec)(encoded) == _NESTED
    assert S.encode_sync(codec)(_NESTED) == encoded


def test_the_json_codec_of_a_self_referring_class_type_side_reads_nested_values():
    codec = S.to_codec_json(S.to_type(User))

    decoded = S.decode_unknown_sync(codec)(
        {"name": "a", "age": 1, "friend": {"name": "b", "age": 2, "friend": None}}
    )
    assert decoded == _NESTED


def test_the_string_tree_codec_of_a_self_referring_class_reads_text_leaves():
    codec = S.to_codec_string_tree(User)

    decoded = S.decode_unknown_sync(codec)(
        {"name": "a", "age": "1", "friend": {"name": "b", "age": "2", "friend": "null"}}
    )
    assert decoded == _NESTED


def test_config_schema_reads_a_self_referring_class():
    provider = cp.from_unknown({"name": "a", "age": 1, "friend": {"name": "b", "age": 2}})

    assert fx.run_sync(config.schema(User).parse(provider).or_die()) == _NESTED


class Node(S.Class):
    payload: object = S.field(S.Unknown)
    next: Node | None = None


def test_config_schema_rejects_an_opaque_field_of_a_self_referring_class_when_made():
    with pytest.raises(ValueError, match="does not support opaque StringTree encodings"):
        config.schema(Node)


class Opaque:
    pass


class Holder(S.Class):
    thing: Opaque = S.field(S.instance_of(Opaque))


def test_a_class_field_without_a_codec_fails_when_the_codec_is_derived():
    with pytest.raises(ValueError, match="Missing structural codec for StringTree: Opaque"):
        S.to_codec_string_tree(Holder)
