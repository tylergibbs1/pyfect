"""Ports of the ``toCodecGoJson`` section of Effect's ``test/schema/toCodec.test.ts``."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.schema import ast
from pyfect.testing import SchemaAsserts


class _Host(TypedDict):
    NetworkMode: str


class _Container(TypedDict):
    Id: str
    Names: tuple[str, ...]
    Labels: dict[str, str]
    HostConfig: NotRequired[_Host]
    Ports: tuple[tuple[str, ...], ...]
    Mounts: NotRequired[tuple[str, ...]]


_CONTAINER = S.Struct(_Container)
# json.Marshal(Container{Id: "abc", Ports: [][]string{nil}}) with Go 1.26
_GO_OUTPUT = {
    "Id": "abc",
    "Names": None,
    "Labels": None,
    "HostConfig": None,
    "Ports": [None],
    "Mounts": None,
}
_DECODED: dict[str, Any] = {"Id": "abc", "Names": (), "Labels": {}, "Ports": ((),)}


def test_decodes_null_as_a_missing_key_or_an_empty_collection() -> None:
    """toCodecGoJson / decodes null as a missing key or an empty collection"""
    SchemaAsserts(S.to_codec_go_json(_CONTAINER)).decoding().succeed(_GO_OUTPUT, _DECODED)
    SchemaAsserts(S.to_codec_go_json(S.Array(S.String))).decoding().succeed(None, ())
    SchemaAsserts(S.to_codec_go_json(S.Record(S.String, S.String))).decoding().succeed(None, {})
    lazy = S.to_codec_go_json(S.suspend(lambda: S.Array(S.String)))
    SchemaAsserts(lazy).decoding().succeed(None, ())


class _Mount(S.Class):
    Options: tuple[str, ...]


class _TreeNode(TypedDict):
    Children: Any


_NODE: Any = S.Struct(_TreeNode, Children=S.Array(S.suspend(lambda: _NODE)))


class _Either(TypedDict):
    a: tuple[str, ...]


class _Through(TypedDict):
    mount: _Mount
    node: Any
    either: Any


def test_applies_through_classes_unions_and_recursive_schemas() -> None:
    """toCodecGoJson / applies through classes, unions, and recursive schemas"""
    schema = S.to_codec_go_json(
        S.Struct(_Through, node=_NODE, either=S.Union(S.Struct(_Either), S.String))
    )
    SchemaAsserts(schema).decoding().succeed(
        {
            "mount": {"Options": None},
            "node": {"Children": [{"Children": None}]},
            "either": {"a": None},
        },
        {
            "mount": _Mount(Options=()),
            "node": {"Children": ({"Children": ()},)},
            "either": {"a": ()},
        },
    )


class _FA(TypedDict):
    a: Any


class _FB(TypedDict):
    b: str


def test_decodes_unions_like_to_codec_json() -> None:
    """toCodecGoJson / decodes unions like toCodecJson"""
    schema = S.to_codec_go_json(S.Union(S.Struct(_FA, a=S.FiniteFromString), S.Struct(_FB)))
    SchemaAsserts(schema).decoding().succeed({"a": "a", "b": "b"}, {"b": "b"})


class _Fe(TypedDict):
    f: str


class _Keeps(TypedDict):
    a: NotRequired[str | None]
    b: tuple[str, ...] | None
    c: NotRequired[Any]
    d: str
    e: _Fe
    g: Any


def test_keeps_null_where_the_schema_accepts_it_and_rejects_it_where_go_would_not_write_it() -> (
    None
):
    """toCodecGoJson / keeps null where the schema accepts it and rejects it where Go would not
    write it"""
    schema = S.to_codec_go_json(
        S.Struct(
            _Keeps,
            a=S.NullOr(S.String),
            b=S.NullOr(S.Array(S.String)),
            c=S.Unknown,
            g=S.NonEmptyArray(S.String),
        )
    )
    decoding = SchemaAsserts(schema).decoding(errors="all")
    decoding.succeed(
        {"a": None, "b": None, "c": None, "d": "d", "e": {"f": "f"}, "g": ["g"]},
        {"a": None, "b": None, "c": None, "d": "d", "e": {"f": "f"}, "g": ("g",)},
    )
    decoding.fail(
        {"b": None, "d": None, "e": None, "g": None},
        'Expected string\n  at ["d"]\nExpected object\n  at ["e"]\nExpected array\n  at ["g"]',
    )


class _Defaults(TypedDict):
    a: str
    b: Any


def test_applies_decoding_defaults_to_null_optional_keys() -> None:
    """toCodecGoJson / applies decoding defaults to null optional keys"""
    schema = S.to_codec_go_json(
        S.Struct(
            _Defaults,
            a=S.String.pipe(S.with_decoding_default_key(fx.succeed("a"))),
            b=S.OptionFromOptionalKey(S.String),
        )
    )
    SchemaAsserts(schema).decoding().succeed({"a": None, "b": None}, {"a": "a", "b": None})


def test_never_encodes_null() -> None:
    """toCodecGoJson / never encodes null"""
    SchemaAsserts(S.to_codec_go_json(_CONTAINER)).encoding().succeed(
        _DECODED, {"Id": "abc", "Names": (), "Labels": {}, "Ports": ((),)}
    )


def test_is_idempotent_and_keeps_its_rules_through_to_codec_json() -> None:
    """toCodecGoJson / is idempotent and keeps its rules through toCodecJson"""
    schema = S.to_codec_go_json(_CONTAINER)
    assert S.to_codec_go_json(schema).ast is schema.ast
    SchemaAsserts(S.to_codec_json(schema)).decoding().succeed(_GO_OUTPUT, _DECODED)


class _NullableKey(TypedDict):
    a: NotRequired[str | None]


def test_adds_no_member_for_a_key_that_already_takes_null() -> None:
    """Effect's ``acceptsNull``, which keeps the union (and its JSON Schema) tidy."""
    schema = S.to_codec_go_json(S.Struct(_NullableKey, a=S.NullOr(S.String)))
    assert isinstance(schema.ast, ast.Objects)
    node = schema.ast.properties[0].type
    assert isinstance(node, ast.Union)
    assert not any(isinstance(member.encoding, tuple) for member in node.types)
