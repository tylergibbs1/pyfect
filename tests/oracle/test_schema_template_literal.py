"""Ports of Effect's ``schema/TemplateLiteral.test.ts`` and the
``TemplateLiteral`` / ``TemplateLiteralParser`` blocks of
``Schema.test.ts``. Each docstring is the Effect test title, prefixed by
its ``describe`` block (``TemplateLiteral.test.ts`` titles by
``TemplateLiteral.test``).

Python mappings: parts are arguments (or one list, as in Effect); a
``bigint`` literal part (``1n``) is an ``int``; the parser decodes to a
``tuple``; a construction error is a ``ValueError``.

Omitted:
- "TemplateLiteral.test / does not expand shared subtemplates during
  construction" counts property reads through a JavaScript ``Proxy``; the
  shared-subtemplate case is pinned below by timing-free construction of a
  deep template instead.
"""

from __future__ import annotations

from typing import Any, NewType, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import Effect
from pyfect import schema as S
from pyfect.brand import Brand
from pyfect.context import Tag
from pyfect.exit import Failure, Success
from pyfect.schema import ParseOptions
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import Issue
from pyfect.testing import SchemaAsserts

Prefix = NewType("Prefix", str)


class Value(TypedDict):
    value: NotRequired[str]


class A(TypedDict):
    a: float


_MISMATCH = "Expected a string matching template literal parts"


def _fails(result: object) -> bool:
    return isinstance(result, Failure)


# ------------------------------------------------------- TemplateLiteral.test


def test_shared_subtemplates_construct_once():
    """TemplateLiteral.test.ts / does not expand shared subtemplates during construction"""
    part: S.ast.AST = S.String.ast
    for _ in range(40):
        part = S.ast.TemplateLiteral((part, part))
    assert isinstance(part, S.ast.TemplateLiteral)


@pytest.mark.parametrize(
    "part",
    [
        S.BooleanFromBit,
        S.FiniteFromString,
        S.String.pipe(S.decode(T.snake_to_camel())),
    ],
)
def test_rejects_codecs_at_construction(part: Any):
    """TemplateLiteral.test.ts / rejects codecs at construction, including transformations between equal types"""  # noqa: E501
    message = "TemplateLiteral parts cannot have an encoding at parts\\[0\\]"
    with pytest.raises(ValueError, match=message):
        S.TemplateLiteral(part)
    with pytest.raises(ValueError, match=message):
        S.ast.TemplateLiteral((part.__codec__().ast,))


def test_rejects_codecs_inside_nested_unions():
    """TemplateLiteral.test.ts / rejects codecs inside nested unions"""
    part = S.Union(S.String, S.Union(S.Number, S.BooleanFromBit))
    with pytest.raises(
        ValueError,
        match=r"cannot have an encoding at parts\[1\]\.types\[1\]\.types\[1\]",
    ):
        S.TemplateLiteral("prefix", part)


def test_rejects_a_transformed_nested_template():
    """TemplateLiteral.test.ts / rejects a transformed nested template"""
    part = S.TemplateLiteral(S.String).pipe(S.decode(T.snake_to_camel()))
    with pytest.raises(ValueError, match=r"cannot have an encoding at parts\[0\]"):
        S.TemplateLiteral(part)


def test_supports_checks_and_explicit_projections():
    """TemplateLiteral.test.ts / supports branded parts, checks, and explicit projections"""
    prefix = S.NonEmptyString.pipe(S.from_brand(Brand[str, Prefix].nominal()))
    schema = S.TemplateLiteral(prefix, ":", S.Int.check(S.is_greater_than(0)))
    assert S.decode_sync(schema)("a:1") == "a:1"
    assert not S.is_(schema)(":1")
    assert not S.is_(schema)("a:0")

    bits = S.TemplateLiteral(S.to_encoded(S.BooleanFromBit))
    assert S.is_(bits)("0")
    assert S.is_(bits)("1")
    assert not S.is_(bits)("true")


def test_parser_transforms_a_template_into_a_tuple():
    """TemplateLiteral.test.ts / TemplateLiteralParser / transforms a template into a tuple and encodes transformed parts"""  # noqa: E501
    schema = S.TemplateLiteralParser("bit:", S.BooleanFromBit)
    encoded = S.to_encoded(schema)
    assert isinstance(encoded.ast, S.ast.TemplateLiteral)
    assert S.is_(encoded)("bit:1")
    assert not S.is_(encoded)("bit:true")
    assert S.decode_sync(schema)("bit:1") == ("bit:", True)
    assert S.encode_sync(schema)(("bit:", False)) == "bit:0"
    assert _fails(S.decode_unknown_exit(schema)("bit:true"))


def _is_one(value: int) -> bool:
    return value == 1


def _is_true(value: bool) -> bool:
    return value


def test_parser_preserves_decoded_checks_and_decode_only_parts():
    """TemplateLiteral.test.ts / TemplateLiteralParser / preserves decoded checks and supports decode-only parts"""  # noqa: E501
    bits: S.LiteralsSchema[int] = S.Literals(0, 1)
    to_bool: T.Transformation[bool, int] = T.Transformation(
        G.transform(_is_one), G.forbidden_encoding
    )
    part = bits.pipe(S.decode_to(S.Boolean.check(S.make_filter(_is_true)), to_bool))
    schema = S.TemplateLiteralParser(part)
    assert S.decode_sync(schema)("1") == (True,)
    assert _fails(S.decode_exit(schema)("0"))
    assert _fails(S.encode_exit(schema)((True,)))


def test_parser_preserves_string_coercion_for_transformed_numeric_parts():
    """TemplateLiteral.test.ts / TemplateLiteralParser / preserves string coercion for transformed numeric parts"""  # noqa: E501
    schema = S.TemplateLiteralParser("a", S.FiniteFromString)
    assert S.decode_sync(schema)("a") == ("a", 0)
    assert S.decode_sync(schema)("a1") == ("a", 1)
    assert _fails(S.decode_exit(schema)("ab"))


def test_parser_enforces_one_of_after_decoding_overlapping_members():
    """TemplateLiteral.test.ts / TemplateLiteralParser / enforces oneOf after decoding overlapping encoded members"""  # noqa: E501
    part = S.Union(
        S.String.pipe(S.decode_to(S.Literal("a"), T.passthrough_supertype())),
        S.String.pipe(S.decode_to(S.Literal("b"), T.passthrough_supertype())),
        mode="one_of",
    )
    schema = S.TemplateLiteralParser(part)
    assert S.decode_sync(schema)("a") == ("a",)
    assert S.decode_sync(schema)("b") == ("b",)
    assert _fails(S.decode_exit(schema)("c"))
    assert S.encode_sync(schema)(("a",)) == "a"

    ambiguous = S.TemplateLiteralParser(S.Union(S.String, S.Number, mode="one_of"))
    assert _fails(S.decode_exit(ambiguous)("1"))
    assert S.encode_sync(ambiguous)(("1",)) == "1"


def test_parser_preserves_shared_unions_when_normalizing():
    """TemplateLiteral.test.ts / TemplateLiteralParser / preserves shared unions when normalizing encoded parts"""  # noqa: E501
    part: S.Codec[str, str] = S.Union(
        S.String.pipe(S.decode_to(S.Literal("a"), T.passthrough_supertype())),
        S.String.pipe(S.decode_to(S.Literal("b"), T.passthrough_supertype())),
        mode="one_of",
    )
    depth = 12
    for _ in range(depth):
        part = S.Union(part, part)
    schema = S.TemplateLiteralParser(part, ":", part)
    source = S.to_encoded(schema).ast
    assert isinstance(source, S.ast.TemplateLiteral)
    assert source.parts[0] is source.parts[2]
    current = source.parts[0]
    for _ in range(depth):
        assert isinstance(current, S.ast.Union)
        assert current.types[0] is current.types[1]
        current = current.types[0]
    assert S.decode_sync(schema)("a:b") == ("a", ":", "b")
    assert S.encode_sync(schema)(("b", ":", "a")) == "b:a"


def test_parser_keeps_greedy_segmentation():
    """TemplateLiteral.test.ts / TemplateLiteralParser / keeps greedy segmentation without requiring tuple round-trips"""  # noqa: E501
    schema = S.TemplateLiteralParser(S.String, ":", S.String)
    encoded = S.encode_sync(schema)(("a", ":", "b:c"))
    assert encoded == "a:b:c"
    assert S.decode_sync(schema)(encoded) == ("a:b", ":", "c")


class _DecodeScale(Tag[float]):
    pass


class _EncodeScale(Tag[float]):
    pass


def _scale_up(value: float, _: ParseOptions) -> Effect[float, Issue, _DecodeScale]:
    return _DecodeScale().map(lambda scale: value * scale)


def _scale_down(value: float, _: ParseOptions) -> Effect[float, Issue, _EncodeScale]:
    return _EncodeScale().map(lambda scale: value / scale)


def test_parser_uses_separate_decoding_and_encoding_services():
    """TemplateLiteral.test.ts / TemplateLiteralParser / uses separate decoding and encoding services"""  # noqa: E501
    scale = T.Transformation(G.transform_effect(_scale_up), G.transform_effect(_scale_down))
    part = S.Number.pipe(S.decode(scale))
    schema = S.TemplateLiteralParser("value:", part)
    decoded = fx.run_blocking_exit(
        S.decode_effect(schema)("value:2").pipe(fx.provide_service(_DecodeScale, 3))
    )
    assert decoded == Success(("value:", 6))
    encoded = fx.run_blocking_exit(
        S.encode_effect(schema)(("value:", 6)).pipe(fx.provide_service(_EncodeScale, 2))
    )
    assert encoded == Success("value:3")


# -------------------------------------------------- Schema / TemplateLiteral


def test_should_expose_the_parts():
    """TemplateLiteral / should expose the parts"""
    parts = ("a", S.String)
    assert S.TemplateLiteral(parts).parts == parts


def test_non_empty_string_plus_string():
    """TemplateLiteral / NonEmptyString + String"""
    SchemaAsserts(S.TemplateLiteral(S.NonEmptyString, S.String)).decoding().succeed("a")


def test_rejects_checks_on_literal_template_literal_and_union_parts():
    """TemplateLiteral / rejects checks on Literal, TemplateLiteral, and Union parts"""
    check: S.Filter[object] = S.make_filter(lambda _: True)
    with pytest.raises(ValueError, match="Invalid TemplateLiteral part Literal"):
        S.TemplateLiteral(S.Literal("a").check(check))
    with pytest.raises(ValueError, match="Invalid TemplateLiteral part TemplateLiteral"):
        S.TemplateLiteral(S.TemplateLiteral("a").check(check))
    with pytest.raises(ValueError, match="Invalid TemplateLiteral part Union"):
        S.TemplateLiteral(S.Union(S.Literal("a"), S.Literal("b")).check(check))


def test_a():
    """TemplateLiteral / "a\""""
    decoding = SchemaAsserts(S.TemplateLiteral("a")).decoding()
    decoding.succeed("a")
    decoding.fail(None, "Expected string")
    decoding.fail("ab", _MISMATCH)
    decoding.fail("", _MISMATCH)


def test_a_space_b():
    """TemplateLiteral / "a b\""""
    decoding = SchemaAsserts(S.TemplateLiteral("a", " ", "b")).decoding()
    decoding.succeed("a b")
    decoding.fail("a  b", _MISMATCH)


def test_bracketed_string():
    """TemplateLiteral / "[" + string + "]\""""
    decoding = SchemaAsserts(S.TemplateLiteral("[", S.String, "]")).decoding()
    decoding.succeed("[a]")
    decoding.fail("a", _MISMATCH)


def test_a_plus_string():
    """TemplateLiteral / "a" + string"""
    decoding = SchemaAsserts(S.TemplateLiteral("a", S.String)).decoding()
    decoding.succeed("a")
    decoding.succeed("ab")
    decoding.fail(None, "Expected string")
    decoding.fail("", _MISMATCH)


def test_a_plus_number():
    """TemplateLiteral / "a" + number"""
    decoding = SchemaAsserts(S.TemplateLiteral("a", S.Number)).decoding()
    for text in ("a1", "a+1", "a1.2"):
        decoding.succeed(text)
    for sign in ("-", "", "+"):
        for e in ("e", "E"):
            for exponent in ("-45", "+45"):
                decoding.succeed(f"a{sign}1.401298464324817{e}{exponent}")
    decoding.fail(None, "Expected string")
    decoding.fail("", _MISMATCH)
    decoding.fail("aa", _MISMATCH)


def test_a_plus_bigint():
    """TemplateLiteral / "a" + bigint"""
    decoding = SchemaAsserts(S.TemplateLiteral("a", S.BigInt)).decoding()
    decoding.succeed("a0")
    decoding.succeed("a1")
    decoding.succeed("a-1")
    decoding.fail(None, "Expected string")
    for text in ("", "aa", "a1.2", "a+1"):
        decoding.fail(text, _MISMATCH)


def test_string():
    """TemplateLiteral / string"""
    decoding = SchemaAsserts(S.TemplateLiteral(S.String)).decoding()
    for text in ("a", "ab", "", "\n", "\r", "\r\n", "\t"):
        decoding.succeed(text)


def test_newline_plus_string():
    """TemplateLiteral / \\n + string"""
    decoding = SchemaAsserts(S.TemplateLiteral("\n", S.String)).decoding()
    decoding.succeed("\n")
    decoding.succeed("\na")
    decoding.fail("a", _MISMATCH)


def test_a_newline_b_plus_string():
    """TemplateLiteral / a\\nb  + string"""
    decoding = SchemaAsserts(S.TemplateLiteral("a\nb ", S.String)).decoding()
    decoding.succeed("a\nb ")
    decoding.succeed("a\nb c")


def test_a_plus_string_plus_b():
    """TemplateLiteral / "a" + string + "b\""""
    asserts = SchemaAsserts(S.TemplateLiteral("a", S.String, "b"))
    decoding = asserts.decoding()
    for text in ("ab", "acb", "abb"):
        decoding.succeed(text)
    for text in ("", "a", "b"):
        decoding.fail(text, _MISMATCH)
    asserts.encoding().succeed("acb")


def test_a_plus_string_plus_b_plus_string():
    """TemplateLiteral / "a" + string + "b" + string"""
    decoding = SchemaAsserts(S.TemplateLiteral("a", S.String, "b", S.String)).decoding()
    for text in ("ab", "acb", "acbd"):
        decoding.succeed(text)
    decoding.fail("a", _MISMATCH)
    decoding.fail("b", _MISMATCH)


def test_typescript_handbook_example():
    """TemplateLiteral / https://www.typescriptlang.org/docs/handbook/2/template-literal-types.html"""
    email = S.Literals("welcome_email", "email_heading")
    footer = S.Literals("footer_title", "footer_sendoff")
    decoding = SchemaAsserts(S.TemplateLiteral(S.Union(email, footer), "_id")).decoding()
    for text in ("welcome_email_id", "email_heading_id", "footer_title_id", "footer_sendoff_id"):
        decoding.succeed(text)
    decoding.fail("_id", _MISMATCH)


def test_string_plus_0():
    """TemplateLiteral / string + 0"""
    decoding = SchemaAsserts(S.TemplateLiteral(S.String, 0)).decoding()
    decoding.succeed("a0")
    decoding.fail("a", _MISMATCH)


def test_string_plus_1n():
    """TemplateLiteral / string + 1n"""
    decoding = SchemaAsserts(S.TemplateLiteral(S.String, 1)).decoding()
    decoding.succeed("a1")
    decoding.fail("a", _MISMATCH)


def test_string_plus_a_or_0():
    """TemplateLiteral / string + ("a" | 0)"""
    literals = S.Literals("a", 0)
    decoding = SchemaAsserts(S.TemplateLiteral(S.String, literals)).decoding()
    decoding.succeed("a0")
    decoding.succeed("aa")
    decoding.fail("b", _MISMATCH)


def test_string_or_1_plus_number_or_true():
    """TemplateLiteral / (string | 1) + (number | true)"""
    schema = S.TemplateLiteral(
        S.Union(S.String, S.Literal(1)), S.Union(S.Number, S.Literal("true"))
    )
    decoding = SchemaAsserts(schema).decoding()
    for text in ("atrue", "-2", "10.1"):
        decoding.succeed(text)
    decoding.fail("", _MISMATCH)


def test_nested_template_in_a_union():
    """TemplateLiteral / `c${`a${string}b` | "e"}d`"""
    schema = S.TemplateLiteral(
        "c", S.Union(S.TemplateLiteral("a", S.String, "b"), S.Literal("e")), "d"
    )
    decoding = SchemaAsserts(schema).decoding()
    for text in ("ced", "cabd", "casbd", "ca  bd"):
        decoding.succeed(text)
    decoding.fail("", _MISMATCH)


def test_heading_tags():
    """TemplateLiteral / < + h + (1|2n) + >"""
    levels: S.LiteralsSchema[int] = S.Literals(1, 2)
    schema = S.TemplateLiteral("<", S.TemplateLiteral("h", levels), ">")
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("<h1>")
    decoding.succeed("<h2>")
    decoding.fail("<h3>", _MISMATCH)


def test_a_plus_check():
    """TemplateLiteral / "a" + check"""
    decoding = SchemaAsserts(S.TemplateLiteral("a", S.NonEmptyString)).decoding()
    decoding.succeed("ab")
    decoding.fail(None, "Expected string")
    decoding.fail("", _MISMATCH)
    decoding.fail("a", _MISMATCH)


def test_rejects_a_plus_transformation():
    """TemplateLiteral / rejects "a" + transformation"""
    with pytest.raises(ValueError, match=r"cannot have an encoding at parts\[1\]"):
        S.TemplateLiteral("a", S.FiniteFromString)


# -------------------------------------------- Schema / TemplateLiteralParser


def test_parser_should_expose_the_parts():
    """TemplateLiteralParser / should expose the parts"""
    parts = ("a", S.String)
    assert S.TemplateLiteralParser(parts).parts == parts


def test_parser_preserves_greedy_segmentation_at_repeated_anchors():
    """TemplateLiteralParser / preserves greedy segmentation at repeated literal anchors"""
    schema = S.TemplateLiteralParser(S.String, ":", S.String)
    SchemaAsserts(schema).decoding().succeed("a:b:c", ("a:b", ":", "c"))


def test_parser_backtracks_from_an_invalid_anchor():
    """TemplateLiteralParser / backtracks from an invalid literal anchor"""
    schema = S.TemplateLiteralParser(S.String, ":", S.NonEmptyString, "x")
    SchemaAsserts(schema).decoding().succeed("a:b:x", ("a", ":", "b:", "x"))


def test_parser_backtracks_across_an_empty_anchor():
    """TemplateLiteralParser / backtracks across an empty literal anchor"""
    schema = S.TemplateLiteralParser(S.String, "", S.NonEmptyString)
    SchemaAsserts(schema).decoding().succeed("a", ("", "", "a"))


def test_parser_non_empty_string_plus_string():
    """TemplateLiteralParser / NonEmptyString + String"""
    schema = S.TemplateLiteralParser(S.NonEmptyString, S.String)
    SchemaAsserts(schema).decoding().succeed("a", ("a", ""))


def test_parser_a():
    """TemplateLiteralParser / "a\""""
    decoding = SchemaAsserts(S.TemplateLiteralParser("a")).decoding()
    decoding.succeed("a", ("a",))
    decoding.fail("ab", _MISMATCH)
    decoding.fail("", _MISMATCH)
    decoding.fail(None, "Expected string")


def test_parser_a_space_b():
    """TemplateLiteralParser / "a b\""""
    decoding = SchemaAsserts(S.TemplateLiteralParser("a", " ", "b")).decoding()
    decoding.succeed("a b", ("a", " ", "b"))
    decoding.fail("a  b", _MISMATCH)


def test_parser_int_plus_a():
    """TemplateLiteralParser / Int + "a\""""
    asserts = SchemaAsserts(S.TemplateLiteralParser(S.Int, "a"))
    decoding = asserts.decoding()
    decoding.succeed("1a", (1, "a"))
    decoding.fail("1.1a", _MISMATCH)
    encoding = asserts.encoding()
    encoding.succeed((1, "a"), "1a")
    encoding.fail((1.1, "a"), "Expected an integer\n  at [0]")


def test_parser_int_plus_string():
    """TemplateLiteralParser / Int + String"""
    schema = S.TemplateLiteralParser(S.Number.check(S.is_int()), S.String)
    SchemaAsserts(schema).decoding().succeed("1.2", (1, ".2"))


def test_parser_number_from_string_plus_a_plus_non_empty_string():
    """TemplateLiteralParser / NumberFromString + "a" + NonEmptyString"""
    asserts = SchemaAsserts(S.TemplateLiteralParser(S.FiniteFromString, "a", S.NonEmptyString))
    decoding = asserts.decoding()
    decoding.succeed("100ab", (100, "a", "b"))
    decoding.succeed("100ab23a", (100, "a", "b23a"))
    decoding.fail("-ab", "Expected a finite number\n  at [0]")
    encoding = asserts.encoding()
    encoding.succeed((100, "a", "b"), "100ab")
    encoding.fail((100, "a", ""), "Expected a value with a length of at least 1\n  at [2]")


def test_parser_h_plus_1_2_3():
    """TemplateLiteralParser / "h" + (1 | 2 | 3)"""
    levels: S.LiteralsSchema[int] = S.Literals(1, 2, 3)
    SchemaAsserts(S.TemplateLiteralParser("h", levels)).decoding().succeed("h1", ("h", 1))


def test_parser_nested_parser_with_string():
    """TemplateLiteralParser / "c" + (`a${string}b`|"e") + "d\""""
    schema = S.TemplateLiteralParser(
        "c",
        S.Union(S.TemplateLiteralParser("a", S.NonEmptyString, "b"), S.Literal("e")),
        "d",
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("ca bd", ("c", ("a", " ", "b"), "d"))
    decoding.succeed("ced", ("c", "e", "d"))
    decoding.fail("cabd", _MISMATCH)
    decoding.fail("ed", _MISMATCH)


def test_parser_nested_parser_with_number():
    """TemplateLiteralParser / "c" + (`a${number}b`|"e") + "d\""""
    schema = S.TemplateLiteralParser(
        "c",
        S.Union(S.TemplateLiteralParser("a", S.Finite.check(S.is_int()), "b"), S.Literal("e")),
        "d",
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("ced", ("c", "e", "d"))
    decoding.succeed("ca1bd", ("c", ("a", 1, "b"), "d"))
    decoding.fail("ca1.1bd", _MISMATCH)
    decoding.fail("ca-bd", _MISMATCH)


def test_parser_template_part():
    """TemplateLiteralParser / readonly ["<", `h${1 | 2}`, ">"]"""
    levels: S.LiteralsSchema[int] = S.Literals(1, 2)
    schema = S.TemplateLiteralParser("<", S.TemplateLiteral("h", levels), ">")
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("<h1>", ("<", "h1", ">"))
    decoding.succeed("<h2>", ("<", "h2", ">"))
    decoding.fail("<h3>", _MISMATCH)


def test_parser_parser_part():
    """TemplateLiteralParser / readonly ["<", readonly ["h", 1 | 2], ">"]"""
    levels: S.LiteralsSchema[int] = S.Literals(1, 2)
    schema = S.TemplateLiteralParser("<", S.TemplateLiteralParser("h", levels), ">")
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("<h1>", ("<", ("h", 1), ">"))
    decoding.succeed("<h2>", ("<", ("h", 2), ">"))
    decoding.fail("<h3>", _MISMATCH)


# ------------------------------------------------------------------ records


def test_record_template_literal_with_checked_part_selects_keys():
    """Record / Record(TemplateLiteral with checked part, Number) should use the part checks to select keys"""  # noqa: E501
    schema = S.Record(S.TemplateLiteral("a", S.NonEmptyString), S.Number)
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": "ignored", "ab": 1}, {"ab": 1})
    decoding.fail({"a": 1, "ab": "bad"}, 'Expected number\n  at ["ab"]')


def test_struct_with_rest_template_literal_record():
    """StructWithRest / Record(`a${string}`, Number)"""
    schema = S.StructWithRest(S.Struct(A), S.Record(S.TemplateLiteral("a", S.String), S.Finite))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1})
    decoding.succeed({"a": 1, "ab": 2})
    decoding.fail({"a": float("nan"), "ab": 2}, 'Expected a finite number\n  at ["a"]')
    decoding.fail({"a": 1, "ab": "c"}, 'Expected number\n  at ["ab"]')


def test_success_exit_is_kept():
    """A template literal keeps the input string (pyfect)."""
    result = S.decode_unknown_exit(S.TemplateLiteral("a", S.String))("ab")
    assert result == Success("ab")


# ------------------------------------------------- derivations (other files)


@pytest.mark.parametrize("derive", [S.to_codec_json, S.to_codec_string_tree])
def test_codec_1n_plus_string(derive: Any):
    """toCodec.test.ts / toCodecJson and toCodecStringTree / TemplateLiteral / 1n + string"""
    asserts = SchemaAsserts(derive(S.TemplateLiteral(1, S.String)))
    asserts.encoding().succeed("1a")
    asserts.decoding().succeed("1a")


@pytest.mark.parametrize("derive", [S.to_codec_json, S.to_codec_string_tree])
def test_codec_a_plus_bigint(derive: Any):
    """toCodec.test.ts / toCodecJson and toCodecStringTree / TemplateLiteral / "a" + bigint"""
    asserts = SchemaAsserts(derive(S.TemplateLiteral("a", S.BigInt)))
    asserts.encoding().succeed("a1")
    asserts.decoding().succeed("a1")


def test_formatter():
    """toFormatter.test.ts / TemplateLiteral"""
    format = S.to_formatter(S.TemplateLiteral(S.Literal("a"), S.String))
    assert format("a") == '"a"'
    assert format("ab") == '"ab"'


def test_parser_preserves_missing_optional_template_literals():
    """SchemaParser.test.ts / preserves missing optional template literals"""
    template = S.TemplateLiteral("a", S.String)
    tuple_schema = S.Tuple(S.optional_key(template))
    assert S.decode_unknown_exit(tuple_schema)([]) == Success(())
    struct = S.Struct(Value, value=template)
    empty: dict[str, str] = {}
    assert S.decode_unknown_exit(struct)({}) == Success(empty)


def _sample(schema: S.Codec[str, str], count: int = 100) -> list[str]:
    from hypothesis import HealthCheck, given, settings

    values: list[str] = []

    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(S.to_strategy(schema))
    def collect(value: str) -> None:
        values.append(value)

    collect()
    return values


def test_arbitrary_finite_numeric_segments():
    """Arbitrary.test.ts / generates finite numeric template literal segments"""
    schema = S.TemplateLiteral(S.Number)
    assert all(map(S.is_(schema), _sample(schema)))


def test_arbitrary_bit_templates_and_checked_numeric_templates():
    """Arbitrary.test.ts / generates bit templates and preserves checked numeric template shrinks"""
    from hypothesis import find, settings

    bits: S.LiteralsSchema[int] = S.Literals(0, 1)
    assert set(_sample(S.TemplateLiteral(bits), 50)) == {"0", "1"}
    schema = S.TemplateLiteral("a", S.Int.check(S.is_between(minimum=1, maximum=100)))
    assert all(map(S.is_(schema), _sample(schema)))
    assert find(S.to_strategy(schema), lambda _: True, settings=settings(database=None)) == "a1"


def test_arbitrary_finite_numeric_union_segments():
    """Arbitrary.test.ts / generates finite numeric template literal union segments"""
    schema = S.TemplateLiteral(S.Union(S.Number, S.Literal("a")))
    assert all(map(S.is_(schema), _sample(schema)))
