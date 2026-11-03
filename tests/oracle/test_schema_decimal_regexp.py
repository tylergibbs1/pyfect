"""Ports of Effect's ``BigDecimal`` and ``RegExp`` schema tests, from
``schema/Schema.test.ts``, ``schema/toCodec.test.ts``,
``schema/toEquivalence.test.ts``, ``schema/toFormatter.test.ts`` and
``schema/toJsonSchemaDocument.test.ts``.

Each test's docstring is the Effect test title, prefixed with its file.
A ``RegExp`` is an ``re.Pattern[str]``; JavaScript's ``g`` flag has no
Python counterpart, so the ``toEquivalence`` case comparing ``i`` with
``g`` compares ``i`` with ``m``.
"""

import re
from typing import Never

from pyfect import big_decimal as bd
from pyfect import schema as S
from pyfect.testing import SchemaAsserts


def _bd(text: str) -> bd.BigDecimal:
    return bd.from_string_unsafe(text)


def test_big_decimal_from_string() -> None:
    """Schema: BigDecimalFromString"""
    asserts = SchemaAsserts(S.BigDecimalFromString)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed("0", _bd("0"))
    decoding.succeed("123.456", _bd("123.456"))
    encoding = asserts.encoding()
    encoding.succeed(bd.make(0, 0), "0")
    encoding.succeed(bd.make(123456, 3), "123.456")
    encoding.fail("a", "Expected BigDecimal")


def test_big_decimal() -> None:
    """Schema: BigDecimal"""
    asserts = SchemaAsserts(S.BigDecimal)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed(_bd("123.45"))
    decoding.fail(None, "Expected BigDecimal")
    asserts.encoding().succeed(_bd("123.45"))


def test_is_greater_than_big_decimal() -> None:
    """Schema: BigDecimal checks / isGreaterThanBigDecimal"""
    schema = S.BigDecimal.check(S.is_greater_than_big_decimal(_bd("1")))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(_bd("2"))
    decoding.fail(_bd("1"), "Expected a value greater than 1")


def test_is_greater_than_or_equal_to_big_decimal() -> None:
    """Schema: BigDecimal checks / isGreaterThanOrEqualToBigDecimal"""
    schema = S.BigDecimal.check(S.is_greater_than_or_equal_to_big_decimal(_bd("1")))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(_bd("1"))
    decoding.fail(_bd("0"), "Expected a value greater than or equal to 1")


def test_is_less_than_big_decimal() -> None:
    """Schema: BigDecimal checks / isLessThanBigDecimal"""
    schema = S.BigDecimal.check(S.is_less_than_big_decimal(_bd("1")))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(_bd("0"))
    decoding.fail(_bd("1"), "Expected a value less than 1")


def test_is_less_than_or_equal_to_big_decimal() -> None:
    """Schema: BigDecimal checks / isLessThanOrEqualToBigDecimal"""
    schema = S.BigDecimal.check(S.is_less_than_or_equal_to_big_decimal(_bd("1")))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(_bd("1"))
    decoding.fail(_bd("2"), "Expected a value less than or equal to 1")


def test_is_between_big_decimal() -> None:
    """Schema: BigDecimal checks / isBetweenBigDecimal"""
    check = S.is_between_big_decimal(minimum=_bd("1"), maximum=_bd("5"))
    decoding = SchemaAsserts(S.BigDecimal.check(check)).decoding()
    decoding.succeed(_bd("3"))
    decoding.fail(_bd("0"), "Expected a value between 1 and 5")


def test_to_equivalence_big_decimal() -> None:
    """toEquivalence: BigDecimal"""
    equivalence = S.to_equivalence(S.BigDecimal)
    assert equivalence(_bd("1.5"), _bd("1.50"))
    assert not equivalence(_bd("1.5"), _bd("2"))
    assert equivalence(_bd("0"), _bd("0"))


def _reg_exp_codec(asserts: SchemaAsserts[Never, Never]) -> None:
    encoding = asserts.encoding()
    encoding.succeed(re.compile("a"), {"source": "a", "flags": ""})
    encoding.succeed(re.compile("a", re.I), {"source": "a", "flags": "i"})
    decoding = asserts.decoding()
    decoding.succeed({"source": "a", "flags": ""}, re.compile("a"))
    decoding.succeed({"source": "a", "flags": "i"}, re.compile("a", re.I))
    decoding.fail({"source": "(", "flags": ""}, "Expected valid RegExp source and flags")
    decoding.fail({"source": "a", "flags": "x"}, "Expected valid RegExp source and flags")


def test_reg_exp() -> None:
    """Schema: RegExp"""
    SchemaAsserts(S.RegExp).verify_generation()


def test_to_codec_json_reg_exp() -> None:
    """toCodec: toCodecJson / RegExp"""
    _reg_exp_codec(SchemaAsserts(S.to_codec_json(S.RegExp)))


def test_to_codec_string_tree_reg_exp() -> None:
    """toCodec: toCodecStringTree / RegExp"""
    _reg_exp_codec(SchemaAsserts(S.to_codec_string_tree(S.RegExp)))


def test_to_equivalence_reg_exp() -> None:
    """toEquivalence: RegExp"""
    equivalence = S.to_equivalence(S.RegExp)
    assert equivalence(re.compile("a"), re.compile("a"))
    assert equivalence(re.compile("a", re.I), re.compile("a", re.I))
    assert not equivalence(re.compile("a"), re.compile("b"))
    assert not equivalence(re.compile("a", re.I), re.compile("a", re.M))


def test_to_formatter_reg_exp() -> None:
    """toFormatter: RegExp"""
    format = S.to_formatter(S.RegExp)
    assert format(re.compile("a")) == "/a/"
    assert format(re.compile("a", re.I)) == "/a/i"


def test_to_json_schema_document_reg_exp() -> None:
    """toJsonSchemaDocument: RegExp"""
    # Effect's ``assertJsonSchemaDocument`` rejects excess properties.
    document = S.to_json_schema_document(S.RegExp, on_excess_property="error")
    assert document.schema == {
        "type": "object",
        "properties": {"source": {"type": "string"}, "flags": {"type": "string"}},
        "required": ["source", "flags"],
        "additionalProperties": False,
    }


def test_a_pattern_with_flags_javascript_lacks_is_not_encoded() -> None:
    """Review: ``{source, flags}`` cannot carry ``re.VERBOSE`` or
    ``re.ASCII``; writing such a pattern without them would decode to a
    different pattern, so encoding fails, and equivalence compares every
    flag."""
    encoding = SchemaAsserts(S.to_codec_json(S.RegExp)).encoding()
    expected = "Expected a pattern whose flags are among i, m and s"
    encoding.fail(re.compile("a b", re.VERBOSE), expected)
    encoding.fail(re.compile("a", re.ASCII), expected)
    equivalence = S.to_equivalence(S.RegExp)
    assert not equivalence(re.compile("a b"), re.compile("a b", re.VERBOSE))
