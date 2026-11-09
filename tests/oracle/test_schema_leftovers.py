"""Ports of Effect's ``schema/Schema.test.ts`` titles the other ``test_schema*.py``
files left: the promise adapters, ``brand``, ``Literal(s).transform``,
``NullOr``, ``OptionFromOptionalKey``, ``Uint8Array`` (``S.Bytes``), ``URL``
and ``make``'s options. Each test's docstring is the Effect test title,
prefixed by its ``describe`` block. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``; JavaScript's ``undefined`` input is ``None``.

Ported in part: "decodeUnknownPromise / encodeUnknownPromise /
FiniteFromString" (``SchemaParser``'s issue-rejecting forms are not
exported), "NullOr / NullOr(String)" (``1`` for the ``undefined`` it
rejects).

Omitted: "Date": ``Schema.Date`` is ``S.DateTimeUtc`` (section 4), with its
own titles in ``test_schema_composites.py``.
"""

import asyncio
from dataclasses import dataclass
from typing import Literal, NewType, NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect.brand import Brand
from pyfect.cause import Cause, Die, Fail
from pyfect.option import Option, Some
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue, Issue
from pyfect.testing import SchemaAsserts

_DEFECT = RuntimeError("defect")
_MIXED: Cause[Issue] = Cause((Fail(InvalidValue({"message": "schema issue"})), Die(_DEFECT)))


def test_promise_adapters_finite_from_string():
    """decodeUnknownPromise / encodeUnknownPromise / FiniteFromString"""
    decode = S.decode_unknown_promise(S.FiniteFromString)
    encode = S.encode_unknown_promise(S.FiniteFromString)
    assert asyncio.run(decode("1")) == 1
    with pytest.raises(S.SchemaError) as decoding:
        asyncio.run(decode(None))
    assert decoding.value.message == "Expected string"
    assert asyncio.run(encode(1)) == "1"
    with pytest.raises(S.SchemaError) as encoding:
        asyncio.run(encode(None))
    assert encoding.value.message == "Expected number"


def test_promise_adapters_reject_when_the_cause_contains_both_a_schema_issue_and_a_defect():
    """decodeUnknownPromise / encodeUnknownPromise / should reject with an error when the cause contains both a schema issue and a defect"""  # noqa: E501
    from pyfect.effect import fail_cause

    getter: G.Getter[str, str] = G.transform_optional_effect(lambda _, __: fail_cause(_MIXED))
    decoding = S.String.pipe(S.decode(T.Transformation(getter, G.passthrough())))
    encoding = S.String.pipe(S.encode(T.Transformation(G.passthrough(), getter)))
    for run in (S.decode_unknown_promise(decoding), S.encode_unknown_promise(encoding)):
        with pytest.raises(RuntimeError) as raised:
            asyncio.run(run("a"))
        assert raised.value.args == ("Promise adapter can only reject schema errors",)
        assert raised.value.__cause__ is _DEFECT


# --------------------------------------------------------------------- brand
# Effect's ``brand(identifier)`` is ``fromBrand(identifier, Brand.nominal())``;
# a Python brand is a ``NewType``, named by ``identifier=``.
Positive = NewType("Positive", str)
Int = NewType("Int", Positive)


def test_brand_single_brand():
    """brand / single brand"""
    schema = S.String.pipe(S.from_brand(Brand[str, Positive].nominal(), identifier="Positive"))
    assert schema.ast is S.String.ast
    assert schema.schema is S.String
    assert schema.identifier == "Positive"


def _double() -> S.BrandSchema[Int, str]:
    positive = S.String.pipe(S.from_brand(Brand[str, Positive].nominal(), identifier="Positive"))
    as_int: Brand[Positive, Int] = Brand[Positive, Int].nominal()
    return positive.pipe(S.from_brand(as_int, identifier="Int"))


def test_brand_double_brand():
    """brand / double brand"""
    schema = _double()
    assert schema.ast is S.String.ast
    assert isinstance(schema.schema, S.BrandSchema)
    assert schema.schema.identifier == "Positive"
    assert schema.identifier == "Int"


def test_brand_override_the_default_identifier():
    """brand / override the default identifier"""
    schema = _double().annotate(identifier="MyInt")
    assert schema.ast.annotations == {"identifier": "MyInt"}
    assert schema.identifier == "Int"


# ------------------------------------------------- Literal(s), NullOr, Option


def test_literal_transform():
    """Literal / transform"""
    schema = S.Literal(0).transform("a")
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed(0, "a")
    decoding.fail(1, "Expected 0")
    encoding = asserts.encoding()
    encoding.succeed("a", 0)
    encoding.fail("b", 'Expected "a"')


def test_literals_transform():
    """Literals / transform"""
    literals: S.LiteralsSchema[Literal[0, 1]] = S.Literals(0, 1)
    schema = literals.transform(["a", "b"])
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed(0, "a")
    decoding.succeed(1, "b")
    decoding.fail(2, "Expected 0 | 1")
    encoding = asserts.encoding()
    encoding.succeed("a", 0)
    encoding.succeed("b", 1)
    encoding.fail("c", 'Expected "a" | "b"')


def test_literals_transform_takes_one_literal_per_member():
    literals: S.LiteralsSchema[Literal[0, 1]] = S.Literals(0, 1)
    with pytest.raises(ValueError, match="one literal per member"):
        literals.transform(["a"])


def test_null_or_string():
    """NullOr / NullOr(String)"""
    decoding = SchemaAsserts(S.NullOr(S.NonEmptyString)).decoding()
    decoding.succeed("a")
    decoding.succeed(None)
    decoding.fail(1, "Expected string | null")
    decoding.fail("", "Expected a value with a length of at least 1")


class _OptionalNumber(TypedDict):
    a: NotRequired[Option[float]]


def test_option_from_optional_key():
    """OptionFromOptionalKey"""
    schema = S.Struct(_OptionalNumber, a=S.OptionFromOptionalKey(S.FiniteFromString))
    asserts = SchemaAsserts(schema)
    asserts.verify_generation()
    decoding = asserts.decoding()
    decoding.succeed({}, {"a": None})
    decoding.succeed({"a": "1"}, {"a": Some(1)})
    decoding.fail({"a": None}, 'Expected string\n  at ["a"]')
    decoding.fail({"a": "a"}, 'Expected a finite number\n  at ["a"]')
    encoding = asserts.encoding()
    encoding.succeed({"a": None}, {})
    encoding.succeed({"a": Some(1)}, {"a": "1"})


def test_uint8_array():
    """Uint8Array"""
    SchemaAsserts(S.Bytes).verify_generation()


# ---------------------------------------------------------------------- make
# ``Schema.make(ast, options)`` assigns ``options`` to the schema; a Python
# schema carries them as the fields of a ``Bottom`` dataclass.


@dataclass(frozen=True, slots=True, eq=False)
class _Custom(S.Bottom[str]):
    custom: str


def test_make_assigns_options():
    """make / assigns options"""
    schema = _Custom(S.String.ast, custom="value")
    assert S.is_schema(schema)
    assert schema.custom == "value"
    rebuilt = schema.annotate()
    assert rebuilt.custom == "value"


def test_url():
    """URL"""
    SchemaAsserts(S.URL).verify_generation()
