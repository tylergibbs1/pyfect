"""Ports of the ``toCodecArrayFromSingle`` section of Effect's ``test/schema/toCodec.test.ts``."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from pyfect import schema as S
from pyfect.schema import ast
from pyfect.testing import SchemaAsserts


class _A(TypedDict):
    a: tuple[float, ...]


class _OptA(TypedDict):
    a: NotRequired[Any]


def _single(schema: Any) -> Any:
    return S.to_codec_array_from_single(S.to_codec_string_tree(schema))


def test_preserves_union_fallback_when_a_singleton_fails_array_element_checks() -> None:
    """toCodecArrayFromSingle / preserves union fallback when a singleton fails array element
    checks"""
    schema = _single(S.Union(S.Array(S.String.check(S.is_min_length(2))), S.String))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a", "a")
    decoding.succeed("ab", ("ab",))


def test_accepts_string_and_array_inputs_for_a_top_level_array() -> None:
    """toCodecArrayFromSingle / accepts string and array inputs for a top-level array"""
    serializer = _single(S.Array(S.Finite))
    assert isinstance(serializer.ast, ast.Arrays)
    asserts = SchemaAsserts(serializer)
    encoding = asserts.encoding()
    encoding.succeed((1.0, 2.0), ("1", "2"))
    encoding.fail(1, "Expected array")
    decoding = asserts.decoding()
    decoding.succeed("1", (1.0,))
    decoding.fail("1,2", "Expected a string representing a finite number\n  at [0]")
    decoding.succeed(["1", "2"], (1.0, 2.0))


def test_accepts_string_and_array_inputs_for_required_array_fields() -> None:
    """toCodecArrayFromSingle / accepts string and array inputs for required array fields"""
    decoding = SchemaAsserts(_single(S.Struct(_A))).decoding()
    decoding.succeed({"a": "1"}, {"a": (1.0,)})
    decoding.succeed({"a": ["1", "2"]}, {"a": (1.0, 2.0)})


def test_accepts_string_and_array_inputs_for_nested_optional_array_fields() -> None:
    """toCodecArrayFromSingle / accepts string and array inputs for nested optional array fields"""
    schema = _single(S.Struct(_OptA, a=S.NonEmptyArray(S.String)))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({})
    decoding.succeed({"a": ["a"]}, {"a": ("a",)})
    decoding.succeed({"a": "a"}, {"a": ("a",)})


def test_accepts_string_and_array_inputs_for_tuples_with_optional_elements() -> None:
    """toCodecArrayFromSingle / accepts string and array inputs for tuples with optional elements"""
    decoding = SchemaAsserts(_single(S.Tuple(S.optional_key(S.String)))).decoding()
    decoding.succeed([], ())
    decoding.succeed("a", ("a",))
    decoding.succeed(["a"], ("a",))


def test_applies_recursively_to_nested_arrays() -> None:
    """toCodecArrayFromSingle / applies recursively to nested arrays"""
    decoding = SchemaAsserts(_single(S.Array(S.Array(S.Finite)))).decoding()
    decoding.succeed("1", ((1.0,),))
    decoding.succeed(["1", "2"], ((1.0,), (2.0,)))
    decoding.succeed([["1", "2"]], ((1.0, 2.0),))


def test_preserves_array_from_single_encoding_when_converting_to_string_tree_again() -> None:
    """toCodecArrayFromSingle / preserves array-from-single encoding when converting to StringTree
    again"""
    schema = _single(S.Array(S.Finite))
    assert S.to_codec_string_tree(schema).ast is schema.ast


def test_is_idempotent() -> None:
    """toCodecArrayFromSingle / is idempotent"""
    schema = _single(S.suspend(lambda: S.Array(S.Finite)))
    assert S.to_codec_array_from_single(schema).ast is schema.ast
