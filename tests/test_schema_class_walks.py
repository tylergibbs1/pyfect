"""Every schema walk that reaches into fields reaches into each kind of schema class too.

Effect's classes are declarations linked to their struct, so its walks meet the fields through
the link; pyfect's are ``ast.Class`` nodes, and a walk that matches only on ``Objects`` skips
them. Each walk here runs against every class kind, alone and in a union.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyfect import schema as S


class Plain(S.Class):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class PlainError(S.Error):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class Tagged(S.TaggedClass):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


class TaggedErr(S.TaggedError):
    tags: tuple[str, ...] = S.field(S.Array(S.String))


CLASS_KINDS: list[Any] = [Plain, PlainError, Tagged, TaggedErr]


def _encoded(cls: Any, tags: object) -> dict[str, object]:
    tag = getattr(cls, "_tag", None)
    return {"tags": tags} if tag is None else {"_tag": tag, "tags": tags}


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_decodes_a_single_value_in_every_class_kind(cls: Any) -> None:
    decode = S.decode_unknown_sync(S.to_codec_array_from_single(cls))
    assert decode(_encoded(cls, "a")) == cls(tags=("a",))
    assert decode(_encoded(cls, ["a", "b"])) == cls(tags=("a", "b"))


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_reaches_classes_in_unions_and_string_trees(cls: Any) -> None:
    schema = S.to_codec_array_from_single(S.to_codec_string_tree(S.Union(cls, S.Int)))
    assert S.decode_unknown_sync(schema)(_encoded(cls, "a")) == cls(tags=("a",))
    assert S.decode_unknown_sync(schema)("1") == 1


@pytest.mark.parametrize("cls", CLASS_KINDS, ids=lambda cls: cls.__name__)
def test_to_codec_array_from_single_keeps_encoding_and_is_idempotent(cls: Any) -> None:
    schema = S.to_codec_array_from_single(cls)
    assert S.encode_sync(schema)(cls(tags=("a",))) == _encoded(cls, ("a",))
    assert S.to_codec_array_from_single(schema).ast is schema.ast
