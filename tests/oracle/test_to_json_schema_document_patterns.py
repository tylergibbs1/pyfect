"""Ports of the pattern and string-length titles of Effect's
``toJsonSchemaDocument.test.ts``. Each test's docstring is the Effect test title,
prefixed by its ``describe`` blocks.

``Schema.isPattern(/source/flags)`` is ``S.is_ecma_pattern("source", "flags")``;
its matches were compared with ``RegExp.prototype.test`` under Node
(``test_ecma_flags_match_node``). ``assertJsonSchemaAcceptsEffectValues`` is
``_accepts``, on the Draft 2020-12 validator of ``_json_schema_validator.py``.

A Python ``str`` is a sequence of code points, as JSON Schema's lengths are, where
a JavaScript string is UTF-16 code units. So a length check is exported exactly
(Effect halves a lower bound), and a lone surrogate in a literal check is a
character of its own, never half of a pair: the literal pattern stays exact.
Those titles keep Python's expected values, and assert what they are about: the
JSON Schema accepts every value the schema accepts.
"""

from collections.abc import Sequence
from typing import Any, TypedDict

import pytest

from pyfect import schema as S
from pyfect.json_schema import JsonSchema

from ._json_schema_validator import compile as compile_json_schema


def _check(schema: S.Top, expected: JsonSchema) -> None:
    document = S.to_json_schema_document(schema, on_excess_property="error")
    assert document.schema == expected
    assert document.definitions == {}


def _accepts(schema: S.Codec[Any, Any], values: Sequence[object]) -> None:
    validate = compile_json_schema(S.to_json_schema_document(schema, on_excess_property="error"))
    is_ = S.is_(schema)
    for value in values:
        if is_(value):
            assert validate(value), value


def test_is_pattern():
    """checks / isPattern"""
    _check(
        S.String.check(S.is_ecma_pattern("^abb+$", "u")), {"type": "string", "pattern": "^abb+$"}
    )


def test_omits_is_pattern_when_its_flags_cannot_be_represented():
    """checks / omits isPattern when its flags cannot be represented"""
    for flags in ("", "y", "iu", "mu", "su"):
        _check(S.String.check(S.is_ecma_pattern("^abb+$", flags)), {"type": "string"})


def test_preserves_representable_is_pattern_semantics():
    """checks / preserves representable isPattern semantics"""
    for source, flags, pattern in [
        ("^abb+$", "gu", "^abb+$"),
        ("abb+", "uy", "^(?:abb+)"),
        ("abb+", "guy", "^(?:abb+)"),
        ("^[é]+$", "u", "^[é]+$"),
        ("^[a-z]+$", "u", "^[a-z]+$"),
        (r"^[\x20-\uD7FF\uE000-\uFFFF]+$", "u", "^[\\x20-\\uD7FF\\uE000-\\uFFFF]+$"),
        (r"^[a-b-\uE000]+$", "u", "^[a-b-\\uE000]+$"),
        (r"^[\d-]+$", "u", "^[\\d-]+$"),
    ]:
        schema = S.String.check(S.is_ecma_pattern(source, flags))
        _check(schema, {"type": "string", "pattern": pattern})


def test_omits_is_pattern_without_the_unicode_flag():
    """checks / omits isPattern without the Unicode flag"""
    for source, flags, values in [
        ("^.$", "", ["a", "😀", "\ud800"]),
        (r"[\uD7FF-\uE000]", "y", ["😀"]),
        (r"^[\uD7FF-\uE000]{2}$", "", ["😀"]),
    ]:
        schema = S.String.check(S.is_ecma_pattern(source, flags))
        _check(schema, {"type": "string"})
        _accepts(schema, values)


# Each row: source, flags, inputs, and what ``new RegExp(source, flags).test`` gave
# under Node for each input.
_NODE_MATCHES: list[tuple[str, str, list[str], list[bool]]] = [
    ("^.$", "", ["a", "😀", "\ud800", "\n"], [True, False, True, False]),
    (r"[\uD7FF-\uE000]", "y", ["😀", "a\ud7ff", "\ud7ff"], [True, False, True]),
    (r"^[\uD7FF-\uE000]{2}$", "", ["😀", "\ud7ff\ue000"], [True, True]),
    ("^.$", "u", ["a", "😀", "\ud800", "\n"], [True, True, True, False]),
    ("^.$", "su", ["\n", "😀"], [True, True]),
    ("^b$", "mu", ["a\nb", "a\u2028b\r", "ab"], [True, True, False]),
    ("^é+$", "iu", ["ÉÉ", "éÉ", "E"], [True, True, False]),
    (r"^\w+$", "iu", ["\u017f", "\u212a", "abc", "é"], [True, True, True, False]),
    (r"\bk", "iu", ["K", "ak"], [True, False]),
    ("abb+", "uy", ["abbb", "xabb"], [True, False]),
    ("abb+", "guy", ["abbb", "xabb"], [True, False]),
    ("^😀{2}$", "", ["😀😀", "😀\ude00"], [False, True]),
    ("^😀{2}$", "u", ["😀😀", "😀\ude00"], [True, False]),
    ("^[😀]$", "", ["😀", "\ud83d"], [False, True]),
    (r"^\uD83D\uDE00$", "u", ["😀"], [True]),
    (r"^\uD83D$", "", ["😀", "\ud83d"], [False, True]),
    (r"^\S$", "", ["😀", "\ud83d"], [False, True]),
    ("^[^a]$", "", ["😀", "b"], [False, True]),
    (r"^[\s\S]{2}$", "", ["😀"], [True]),
    ("^.$", "u", ["\ud83d\ude00"], [True]),
    ("ß", "iu", ["\u1e9e", "SS"], [True, False]),
]


@pytest.mark.parametrize(("source", "flags", "inputs", "expected"), _NODE_MATCHES)
def test_ecma_flags_match_node(source: str, flags: str, inputs: list[str], expected: list[bool]):
    """``is_ecma_pattern`` with flags matches as ``RegExp.prototype.test`` does under Node."""
    is_ = S.is_(S.String.check(S.is_ecma_pattern(source, flags)))
    assert [is_(value) for value in inputs] == expected


@pytest.mark.parametrize("flags", ["x", "uu", "uv", "v", "i", "gi"])
def test_ecma_flags_refused(flags: str):
    """Flags ``new RegExp`` rejects, and ``v`` and ``i`` without ``u``, raise."""
    with pytest.raises(S.EcmaPatternError):
        S.is_ecma_pattern("a", flags)


def test_ecma_flags_are_canonical_in_the_payload():
    """The flags are written as ``RegExp.prototype.flags`` orders them."""
    check = S.is_ecma_pattern("a", "yug")
    assert check.annotations is not None
    representation: Any = check.annotations["representation"]
    assert representation["payload"] == {"source": "a", "flags": "guy"}


def test_loosens_literal_patterns_only_at_surrogate_pair_boundaries():
    """checks / loosens literal patterns only at surrogate-pair boundaries"""
    # Effect writes ``^abc``, ``xyz$`` and ``x``: in JavaScript ``"abc😀"`` starts
    # with ``"abc\uD83D"``. A Python ``str`` holds the code point, so the lone
    # surrogate is a character the check requires, and the pattern stays exact.
    for check, pattern, values in [
        (S.is_starting_with("abc\ud83d"), "^abc\ud83d", ["abc😀", "abc\ud83d"]),
        (S.is_ending_with("\ude00xyz"), "\ude00xyz$", ["😀xyz", "\ude00xyz"]),
        (S.is_including("\ude00x\ud83d"), "\ude00x\ud83d", ["😀x😀", "\ude00x\ud83d"]),
    ]:
        schema = S.String.check(check)
        _check(schema, {"type": "string", "pattern": pattern})
        _accepts(schema, values)


class _Abc(TypedDict):
    abc: str


def test_does_not_use_approximate_literal_patterns_as_record_selectors():
    """checks / does not use approximate literal patterns as record selectors"""
    schema = S.StructWithRest(
        S.Struct(_Abc), S.Record(S.String.check(S.is_starting_with("abc\ud83d")), S.Finite)
    )
    # Effect's value has the key ``"abc😀"``, which its record selects in JavaScript;
    # in Python the key the record selects holds the lone surrogate.
    _accepts(schema, [{"abc": "text", "abc\ud83d": 1}])


def test_omits_literal_patterns_whose_entire_constraint_is_a_surrogate_pair_boundary():
    """checks / omits literal patterns whose entire constraint is a surrogate-pair boundary"""
    # Effect omits these; here the lone surrogate is the whole constraint, exported.
    for check, pattern, values in [
        (S.is_starting_with("\ud83d"), "^\ud83d", ["😀", "\ud83d"]),
        (S.is_ending_with("\ude00"), "\ude00$", ["😀", "\ude00"]),
        (S.is_including("\ude00\ud83d"), "\ude00\ud83d", ["😀😀", "\ude00\ud83d"]),
    ]:
        schema = S.String.check(check)
        _check(schema, {"type": "string", "pattern": pattern})
        _accepts(schema, values)


def test_exports_the_tightest_code_point_bounds_that_accept_every_valid_string():
    """checks / isBetweenLength / exports the tightest code-point bounds that accept every valid string"""  # noqa: E501
    # Effect writes ``minLength: 2`` for UTF-16 lengths; code point lengths are exact.
    schema = S.String.check(S.is_between_length(3, 4))
    _check(schema, {"type": "string", "minLength": 3, "maxLength": 4})
    _accepts(schema, ["ab", "a😀", "😀😀", "abcde", "abc", "a😀b😀"])


def test_exports_both_applicable_bounds_when_the_input_type_is_a_union():
    """checks / isMinLength / exports both applicable bounds when the input type is a union"""
    schema = S.Union(S.String, S.Array(S.String)).check(S.is_min_length(2))
    _accepts(schema, ["😀", "ab", ["a", "b"], ["a"]])


_SEGMENT = S.String.check(S.is_ecma_pattern("^abc$"))
_TEMPLATES: list[tuple[str, Any]] = [
    ("direct", S.TemplateLiteral("item.", _SEGMENT)),
    ("named", S.TemplateLiteral("item.", _SEGMENT.annotate(identifier="Segment"))),
    ("named template", S.TemplateLiteral("item.", _SEGMENT).annotate(identifier="Item")),
    ("nested template", S.TemplateLiteral("item.", S.TemplateLiteral(_SEGMENT))),
    ("union", S.TemplateLiteral("item.", S.Union(_SEGMENT, S.Literal("def")))),
]


_ItemXyz = TypedDict("_ItemXyz", {"item.xyz": str})


@pytest.mark.parametrize(("name", "part"), _TEMPLATES)
def test_template_record_value_checks_skip_explicit_properties_in_strict_mode(name: str, part: Any):
    """TemplateLiteral segments / does not apply %s template record value checks to explicit properties in strict mode"""  # noqa: E501
    struct = S.Struct(_ItemXyz)
    schema = S.StructWithRest(struct, S.Record(part, S.Finite))
    value = {"item.abc": 1, "item.xyz": "text"}
    assert S.decode_unknown_sync(schema, on_excess_property="error")(value) == value
    document = S.to_json_schema_document(schema, on_excess_property="error")
    validate = compile_json_schema(document)
    assert validate(value)
    assert not validate({"item.abc": "not a number", "item.xyz": "text"})
    assert not validate({"item.abc": 1, "item.xyz": "text", "other": 1})
    assert "patternProperties" not in document.schema
    assert "propertyNames" in document.schema


def test_keeps_one_of_when_a_check_on_the_whole_template_is_exported_exactly():
    """TemplateLiteral segments / keeps oneOf when a check on the whole template is exported exactly"""  # noqa: E501
    template = S.TemplateLiteral("item.", S.String).check(S.is_ecma_pattern(r"^item\.abc$"))
    schema = S.Union(template, S.Literal("item.abc"), mode="one_of")
    assert not S.is_(schema)("item.abc")
    assert not S.is_(schema)("item.xyz")
    document = S.to_json_schema_document(schema)
    validate = compile_json_schema(document)
    assert not validate("item.abc")
    assert not validate("item.xyz")
    assert "oneOf" in document.schema
