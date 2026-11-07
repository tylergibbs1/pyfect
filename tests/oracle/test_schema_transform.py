"""Ports of Effect's ``Schema.test.ts``: the built-in codecs and the
``decodeTo`` / ``encodeTo`` / ``decode`` / ``encode`` / ``flip`` titles. Each
test's docstring is the Effect test title, prefixed by its ``describe``
block. ``TestSchema.Asserts`` is ``testing.SchemaAsserts``.

Python mappings: ``SchemaTransformation`` is ``T``, ``SchemaGetter`` is
``G``; ``decodeTo(to, { decode, encode })`` is ``S.decode_to(to,
T.Transformation(decode, encode))``; ``composeTransformation(a, b)`` is
``a.compose(b)``; ``Schema.check(...)`` in a pipe is the ``.check(...)``
method. A struct is ``S.Struct(TypedDict)``: ``optionalKey`` on a struct
key is ``NotRequired``, and ``decodeTo(Schema.optionalKey(target))`` (a key
optional on the decoded side) is a ``NotRequired`` key decoded by ``target``.
A zone is a ``ZoneInfo`` / ``timezone``, a zoned date-time an aware
``datetime``, an ``Option`` ``Some | None``, ``Redacted`` ``pyfect.redacted``.

Omitted:
- "Transformations / DateFromString", "... / DateFromMillis": JavaScript's
  ``Date`` (an invalid ``Date``) has no Python counterpart;
  ``DateTimeUtcFromString`` / ``DateTimeUtcFromMillis`` are the codecs.
- "Transformations / BigDecimalFromString": no ``BigDecimal`` yet.
- "flip / should work with withConstructorDefault": ported in
  ``test_schema_constructor_default.py``.
- "UnknownFromJsonString / fromJsonString / reviver option" and "...
  replacer and space options" (the replacer half): JavaScript's
  ``reviver`` / ``replacer`` callbacks (``space`` is ported in
  ``test_from_json_string_space``).
- The "decodeUnknownPromise / encodeUnknownPromise" titles: ported in
  ``test_schema_leftovers.py`` (without ``SchemaParser``'s issue forms).
- The synchronous adapters run an asynchronous decoding to completion
  instead of throwing or dying as Effect's do (see
  the async decoding test): Python's runtime can drive it in place.
- "OptionFromOptionalNullOr / onNoneEncoding: undefined", the ``undefined``
  inputs of the other two titles, and the ``null`` input of "default
  (omit)"'s encoding failure: Python has one ``None``, which is an empty
  ``Option`` (``1`` stands for the non-``Option`` value).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, Never, NotRequired, TypedDict, TypeIs, cast
from zoneinfo import ZoneInfo

import pytest

from pyfect import redacted, testing
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.clock import sleep
from pyfect.context import Tag
from pyfect.date_time import format_iso_zoned
from pyfect.effect import Effect, fail_cause, succeed
from pyfect.errors import AsyncFiberError
from pyfect.exit import Failure
from pyfect.option import Option, Some
from pyfect.result import Err, Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import InvalidValue, Issue, is_issue
from pyfect.testing import SchemaAsserts

# ------------------------------------------------------------ Transformations


def test_number_from_string():
    """Transformations / NumberFromString"""
    asserts = SchemaAsserts(S.NumberFromString)
    decoding = asserts.decoding()
    decoding.succeed("1", 1)
    assert math.isnan(S.decode_unknown_sync(S.NumberFromString)("NaN"))
    decoding.succeed("Infinity", math.inf)
    decoding.succeed("+Infinity", math.inf)
    decoding.succeed("-Infinity", -math.inf)
    encoding = asserts.encoding()
    encoding.succeed(1, "1")
    encoding.succeed(math.nan, "NaN")
    encoding.succeed(math.inf, "Infinity")
    encoding.succeed(-math.inf, "-Infinity")
    encoding.fail("a", "Expected number")


def test_finite_from_string():
    """Transformations / FiniteFromString"""
    asserts = SchemaAsserts(S.FiniteFromString)
    decoding = asserts.decoding()
    decoding.succeed("1", 1)
    for input in ("a", "NaN", "Infintiy", "+Infintiy", "-Infintiy"):
        decoding.fail(input, "Expected a finite number")
    encoding = asserts.encoding()
    encoding.succeed(1, "1")
    encoding.fail("a", "Expected number")


def test_big_int_from_string():
    """Transformations / BigIntFromString"""
    asserts = SchemaAsserts(S.BigIntFromString)
    asserts.decoding().succeed("0", 0)
    asserts.decoding().fail("a", "Expected a string representing a bigint")
    asserts.encoding().succeed(0, "0")


def test_time_zone_named_from_string():
    """Transformations / TimeZoneNamedFromString"""
    asserts = SchemaAsserts(S.TimeZoneNamedFromString)
    asserts.decoding().succeed("Europe/London", ZoneInfo("Europe/London"))
    asserts.encoding().succeed(ZoneInfo("Europe/London"), "Europe/London")
    asserts.encoding().fail("a", "Expected DateTime.TimeZone.Named")


def test_time_zone_from_string():
    """Transformations / TimeZoneFromString"""
    asserts = SchemaAsserts(S.TimeZoneFromString)
    plus_three = timezone(timedelta(hours=3))
    decoding = asserts.decoding()
    decoding.succeed("Europe/London", ZoneInfo("Europe/London"))
    decoding.succeed("+03:00", plus_three)
    encoding = asserts.encoding()
    encoding.succeed(ZoneInfo("Europe/London"), "Europe/London")
    encoding.succeed(plus_three, "+03:00")
    encoding.fail("a", "Expected DateTime.TimeZone")


def test_date_time_zoned_from_string():
    """Transformations / DateTimeZonedFromString"""
    asserts = SchemaAsserts(S.DateTimeZonedFromString)
    zoned = datetime(2021, 1, 1, tzinfo=UTC).astimezone(ZoneInfo("Europe/London"))
    asserts.decoding().fail("invalid", "Expected a valid Zoned DateTime string")
    asserts.encoding().succeed(zoned, format_iso_zoned(zoned))
    asserts.encoding().fail("a", "Expected DateTime.Zoned")


def test_finite_from_string_and_is_greater_than():
    """Transformations / FiniteFromString & isGreaterThan"""
    asserts = SchemaAsserts(S.FiniteFromString.check(S.is_greater_than(2)))
    asserts.decoding().succeed("3", 3)
    asserts.decoding().fail("1", "Expected a value greater than 2")
    asserts.encoding().succeed(3, "3")
    asserts.encoding().fail(1, "Expected a value greater than 2")


# ------------------------------------------------------------------- decodeTo


class _A(TypedDict):
    a: str


class _OptionalA(TypedDict):
    a: NotRequired[str]


_MISSING_A = 'Missing key\n  at ["a"]'


def test_decode_to_should_expose_the_source_and_the_target_schemas():
    """decodeTo / should expose the source and the target schemas"""
    schema = S.FiniteFromString
    assert isinstance(schema.from_, S.Bottom)
    assert schema.from_.ast.tag == "String"
    assert schema.to is S.Finite


def test_decode_to_required_to_required():
    """decodeTo / required to required"""
    field = S.String.pipe(S.decode_to(S.String, T.passthrough()))
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().fail({}, _MISSING_A)
    asserts.encoding().succeed({"a": "a"})
    asserts.encoding().fail({}, _MISSING_A)


def test_decode_to_required_to_optional():
    """decodeTo / required to optional"""
    transformation = T.Transformation(G.required(), G.with_default(succeed("default")))
    field = S.String.pipe(S.decode_to(S.String, transformation))
    asserts = SchemaAsserts(S.Struct(_OptionalA, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().fail({}, _MISSING_A)
    asserts.encoding().succeed({"a": "a"})
    asserts.encoding().succeed({}, {"a": "default"})


def test_decode_to_optional_key_to_required():
    """decodeTo / optionalKey to required"""
    transformation = T.Transformation(G.with_default(succeed("default")), G.passthrough())
    field = S.optional_key(S.String).pipe(S.decode_to(S.String, transformation))
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().succeed({}, {"a": "default"})
    asserts.encoding().succeed({"a": "a"})


def test_decode_to_double_transformation():
    """decodeTo / double transformation"""
    asserts = SchemaAsserts(S.Trim.pipe(S.decode_to(S.FiniteFromString, T.passthrough())))
    asserts.decoding().succeed(" 2 ", 2)
    asserts.decoding().fail(" a2 ", "Expected a finite number")
    asserts.encoding().succeed(2, "2")


_AT_LEAST_3 = 'Expected a value with a length of at least 3\n  at ["a"]'


def test_decode_to_double_transformation_with_checks():
    """decodeTo / double transformation with checks"""
    field = (
        S.String.check(S.is_min_length(2))
        .pipe(S.decode_to(S.String.check(S.is_min_length(3)), T.passthrough()))
        .pipe(S.decode_to(S.String, T.passthrough()))
    )
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "aaa"})
    asserts.decoding().fail({"a": "aa"}, _AT_LEAST_3)
    asserts.encoding().succeed({"a": "aaa"})
    asserts.encoding().fail({"a": "aa"}, _AT_LEAST_3)


class _InnerEncoded(TypedDict):
    b: NotRequired[str]


class _Inner(TypedDict):
    b: str


class _Outer(TypedDict):
    a: _Inner


def test_decode_to_nested_defaults():
    """decodeTo / nested defaults"""
    b = S.optional_key(S.String).pipe(
        S.decode_to(
            S.String, T.Transformation(G.with_default(succeed("default-b")), G.passthrough())
        )
    )
    inner = S.Struct(_Inner, b=b)
    empty: _InnerEncoded = {}
    # A struct's Encoded is a ``Mapping``: the transformation says so.
    defaulted: T.Transformation[Mapping[str, object], _InnerEncoded] = T.Transformation(
        G.with_default(succeed(empty)), G.passthrough_supertype()
    )
    a = S.optional_key(S.Struct(_InnerEncoded)).pipe(S.decode_to(inner, defaulted))
    decoding = SchemaAsserts(S.Struct(_Outer, a=a)).decoding()
    decoding.succeed({"a": {"b": "b"}})
    decoding.succeed({"a": {}}, {"a": {"b": "default-b"}})
    decoding.succeed({}, {"a": {"b": "default-b"}})


def test_decode_double_transformation():
    """decode / double transformation"""
    schema = S.String.pipe(S.decode(T.trim().compose(T.to_lower_case())))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(" A ", "a")
    asserts.encoding().succeed(" A ", " A ")


# ------------------------------------------------------------------- encodeTo


def test_encode_to_required_to_required():
    """encodeTo / required to required"""
    field = S.String.pipe(S.encode_to(S.String, T.passthrough()))
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().fail({}, _MISSING_A)
    asserts.encoding().succeed({"a": "a"})
    asserts.encoding().fail({}, _MISSING_A)


def test_encode_to_required_to_optional_key():
    """encodeTo / required to optionalKey"""
    transformation = T.Transformation(G.with_default(succeed("default")), G.passthrough())
    field = S.String.pipe(S.encode_to(S.optional_key(S.String), transformation))
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().succeed({}, {"a": "default"})
    asserts.encoding().succeed({"a": "a"})


def test_encode_to_optional_key_to_required():
    """encodeTo / optionalKey to required"""
    transformation = T.Transformation(G.required(), G.with_default(succeed("default")))
    field = S.String.pipe(S.encode_to(S.String, transformation))
    asserts = SchemaAsserts(S.Struct(_OptionalA, a=field))
    asserts.decoding().succeed({"a": "a"})
    asserts.decoding().fail({}, _MISSING_A)
    asserts.encoding().succeed({"a": "a"})
    asserts.encoding().succeed({}, {"a": "default"})


def test_encode_to_double_transformation():
    """encodeTo / double transformation"""
    asserts = SchemaAsserts(S.FiniteFromString.pipe(S.encode_to(S.Trim, T.passthrough())))
    asserts.decoding().succeed(" 2 ", 2)
    asserts.decoding().fail(" a2 ", "Expected a finite number")
    asserts.encoding().succeed(2, "2")


def test_encode_to_double_transformation_with_checks():
    """encodeTo / double transformation with checks"""
    field = S.String.pipe(S.encode_to(S.String.check(S.is_min_length(3)), T.passthrough())).pipe(
        S.encode_to(S.String.check(S.is_min_length(2)), T.passthrough())
    )
    asserts = SchemaAsserts(S.Struct(_A, a=field))
    asserts.decoding().succeed({"a": "aaa"})
    asserts.decoding().fail({"a": "aa"}, _AT_LEAST_3)
    asserts.encoding().succeed({"a": "aaa"})
    asserts.encoding().fail({"a": "aa"}, _AT_LEAST_3)


def test_encode_double_transformation():
    """encode / double transformation"""
    schema = S.String.pipe(S.encode(T.trim().compose(T.to_lower_case()).flip()))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(" A ", " A ")
    asserts.encoding().succeed(" A ", "a")


# ----------------------------------------------------------------------- flip


def test_flip_should_expose_the_schema():
    """flip / should expose the schema"""
    schema = S.Struct(_A)
    assert S.flip(schema).schema is schema


def test_flip_string_min_length_3_number_greater_than_2():
    """flip / string & isMinLength(3) <-> number & isGreaterThan(2)"""
    schema = S.flip(S.FiniteFromString.check(S.is_greater_than(2))).check(S.is_min_length(3))
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail(2, "Expected a value greater than 2")
    asserts.decoding().fail(3, "Expected a value with a length of at least 3")
    asserts.encoding().succeed("123", 123)


def _flip_check_flip[T_, E](schema: S.Bottom[T_, E], check: S.Check[E]) -> S.Codec[T_, E]:
    return S.flip(S.flip(schema).check(check))


def _long_a(value: S.ast.Annotations) -> bool:
    return len(str(value["a"])) > 1


def test_flip_struct_and_flip_and_check_and_flip_should_apply_the_check_to_the_encoded_side():
    """flip / Struct & flip & check & flip should apply the check to the encoded side"""
    check = S.make_filter(_long_a, expected="a length > 1")
    schema = _flip_check_flip(S.Struct(_A).__codec__(), check)
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Objects)
    assert node.checks is None
    assert node.encoding_checks is not None and len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail({"a": "a"}, "Expected a length > 1")
    asserts.decoding().succeed({"a": "aa"})
    asserts.encoding().fail({"a": "a"}, "Expected a length > 1")
    asserts.encoding().succeed({"a": "aa"})


def _long_head(value: tuple[str]) -> bool:
    return len(value[0]) > 1


def test_flip_tuple_and_flip_and_check_and_flip_should_apply_the_check_to_the_encoded_side():
    """flip / Tuple & flip & check & flip should apply the check to the encoded side"""
    check = S.make_filter(_long_head, expected="head length > 1")
    schema = _flip_check_flip(S.Tuple(S.String), check)
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Arrays)
    assert node.checks is None
    assert node.encoding_checks is not None and len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail(["a"], "Expected head length > 1")
    asserts.decoding().succeed(["aa"], ("aa",))
    asserts.encoding().fail(("a",), "Expected head length > 1")
    asserts.encoding().succeed(("aa",))


def _is_aa(value: str) -> bool:
    return value == "aa"


def test_flip_union_and_flip_and_check_and_flip_should_apply_the_check_to_the_encoded_side():
    """flip / Union & flip & check & flip should apply the check to the encoded side"""
    check = S.make_filter(_is_aa, expected='"aa"')
    union: S.Bottom[str] = S.Union(S.Literal("a"), S.Literal("aa"))
    schema = _flip_check_flip(union, check)
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Union)
    assert node.checks is None
    assert node.encoding_checks is not None and len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail("a", 'Expected "aa"')
    asserts.decoding().succeed("aa")
    asserts.encoding().fail("a", 'Expected "aa"')
    asserts.encoding().succeed("aa")


def _is_str(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def _long(value: str) -> bool:
    return len(value) > 1


def test_flip_declaration_and_flip_and_check_and_flip_should_apply_the_check_to_the_encoded_side():
    """flip / Declaration & flip & check & flip should apply the check to the encoded side"""
    check = S.make_filter(_long, expected="a length > 1")
    schema = _flip_check_flip(S.declare(_is_str, expected="string declaration"), check)
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Declaration)
    assert node.checks is None
    assert node.encoding_checks is not None and len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail("a", "Expected a length > 1")
    asserts.decoding().succeed("aa")
    asserts.encoding().fail("a", "Expected a length > 1")
    asserts.encoding().succeed("aa")


class _B(TypedDict):
    b: str


def _a_of_b(value: _B) -> _A:
    return {"a": value["b"]}


def _b_of_a(value: Mapping[str, object]) -> _B:
    # A struct's Encoded is a ``Mapping``: the encoding getter takes one.
    return {"b": str(value["a"])}


def test_flip_struct_and_flip_and_check_and_flip_with_encoding_chain_should_check_the_local_value():
    """flip / Struct & flip & check & flip with encoding chain should check the local value"""
    check = S.make_filter(_long_a, expected="a length > 1")
    local = _flip_check_flip(S.Struct(_A).__codec__(), check)
    transformation: T.Transformation[Mapping[str, object], _B] = T.Transformation(
        G.transform(_a_of_b), G.transform(_b_of_a)
    )
    schema = S.Struct(_B).pipe(S.decode_to(local, transformation))
    node = schema.ast
    assert isinstance(node, S.ast.Objects)
    assert node.encoding is not None and len(node.encoding) == 1
    assert node.encoding_checks is not None and len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail({"b": "a"}, "Expected a length > 1")
    asserts.decoding().succeed({"b": "aa"}, {"a": "aa"})
    asserts.encoding().fail({"a": "a"}, "Expected a length > 1")
    asserts.encoding().succeed({"a": "aa"}, {"b": "aa"})


# ------------------------------------------------------------ codecs and Option


def test_redacted_from_value_should_decode_a_value():
    """RedactedFromValue / should decode a value"""
    asserts = SchemaAsserts(S.RedactedFromValue(S.FiniteFromString.check(S.is_int())))
    decoding = asserts.decoding()
    decoding.succeed("123", redacted.make(123))
    decoding.fail(None, "Expected string")
    decoding.fail("1.2", "Expected an integer")
    encoding = asserts.encoding()
    encoding.succeed(redacted.make(123), "123")
    encoding.fail("schema-secret", "Expected Redacted")
    encoding.fail(redacted.make("schema-secret"), 'Expected a valid value\n  at ["value"]')
    encoding.fail(redacted.make(1.2), 'Expected a valid value\n  at ["value"]')


def test_option_from_null_or():
    """OptionFromNullOr"""
    asserts = SchemaAsserts(S.OptionFromNullOr(S.FiniteFromString))
    none: Option[float] = None
    asserts.decoding().succeed(None, none)
    asserts.decoding().succeed("1", Some(1))
    asserts.decoding().fail("a", "Expected a finite number")
    asserts.encoding().succeed(none, None)
    asserts.encoding().succeed(Some(1), "1")


class _OptionalNullOrNumber(TypedDict):
    a: Option[float]


def test_option_from_optional_null_or_default_omit():
    """OptionFromOptionalNullOr / default (omit)"""
    schema = S.Struct(_OptionalNullOrNumber, a=S.OptionFromOptionalNullOr(S.FiniteFromString))
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed({}, {"a": None})
    decoding.succeed({"a": None}, {"a": None})
    decoding.succeed({"a": "1"}, {"a": Some(1)})
    decoding.fail({"a": "a"}, 'Expected a finite number\n  at ["a"]')
    encoding = asserts.encoding()
    encoding.succeed({"a": None}, {})
    encoding.succeed({"a": Some(1)}, {"a": "1"})
    encoding.fail({"a": 1}, 'Expected Option\n  at ["a"]')


def test_option_from_optional_null_or_on_none_encoding_null():
    """OptionFromOptionalNullOr / onNoneEncoding: null"""
    field = S.OptionFromOptionalNullOr(S.FiniteFromString, on_none_encoding=None)
    asserts = SchemaAsserts(S.Struct(_OptionalNullOrNumber, a=field))
    decoding = asserts.decoding()
    decoding.succeed({}, {"a": None})
    decoding.succeed({"a": None}, {"a": None})
    decoding.succeed({"a": "1"}, {"a": Some(1)})
    encoding = asserts.encoding()
    encoding.succeed({"a": None}, {"a": None})
    encoding.succeed({"a": Some(1)}, {"a": "1"})


def test_unknown_from_json_string_use_case_unknown_json_string():
    """UnknownFromJsonString / fromJsonString / use case: Unknown <-> JSON string"""
    asserts = SchemaAsserts(S.UnknownFromJsonString)
    asserts.decoding().succeed('{"a":1}', {"a": 1})
    asserts.decoding().fail('{"a"', "Expected a valid JSON string")
    asserts.encoding().succeed({"a": 1}, '{"a":1}')


class _BNumber(TypedDict):
    b: float


def test_from_json_string_use_case_create_a_json_string_serializer_for_an_existing_schema():
    """UnknownFromJsonString / fromJsonString / use case: create a JSON string serializer for an existing schema"""  # noqa: E501
    asserts = SchemaAsserts(S.from_json_string(S.Struct(_BNumber)))
    asserts.decoding().succeed('{"b":1}', {"b": 1})
    asserts.decoding().fail('{"a":null}', 'Missing key\n  at ["b"]')


class _ANumber(TypedDict):
    a: float


def test_from_json_string_space():
    """UnknownFromJsonString / fromJsonString / replacer and space options"""
    encoding = SchemaAsserts(S.from_json_string(S.Struct(_ANumber), space=2)).encoding()
    encoding.succeed({"a": 1}, '{\n  "a": 1\n}')


class _AJson(TypedDict):
    a: _BNumber


def test_from_json_string_use_case_parse_stringify_a_nested_schema():
    """UnknownFromJsonString / fromJsonString / use case: parse / stringify a nested schema"""
    schema = S.Struct(_AJson, a=S.from_json_string(S.Struct(_BNumber)))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"a": '{"b":2}'}, {"a": {"b": 2}})
    asserts.decoding().fail({"a": '{"a":null}'}, 'Missing key\n  at ["a"]["b"]')


def test_is_finite_from_string():
    """is / FiniteFromString"""
    is_ = S.is_(S.FiniteFromString)
    assert is_(1)
    assert not is_("a")


def test_asserts_finite_from_string():
    """asserts / FiniteFromString"""
    S.asserts(S.FiniteFromString, 1)
    with pytest.raises(S.SchemaError, match=r"^Expected number$"):
        S.asserts(S.FiniteFromString, "a")


@pytest.mark.parametrize(
    ("name", "transformation", "check", "decoded", "message"),
    [
        (
            "Capitalize",
            T.capitalize(),
            S.is_capitalized(),
            "Abc",
            "the first character in uppercase",
        ),
        (
            "Uncapitalize",
            T.uncapitalize(),
            S.is_uncapitalized(),
            "aBC",
            "the first character in lowercase",
        ),
        ("Lowercase", T.to_lower_case(), S.is_lowercased(), "abc", "all characters in lowercase"),
        ("Uppercase", T.to_upper_case(), S.is_uppercased(), "ABC", "all characters in uppercase"),
    ],
)
def test_string_case(
    name: str,
    transformation: T.Transformation[str, str],
    check: S.Check[str],
    decoded: str,
    message: str,
):
    """Capitalize / Uncapitalize / Lowercase / Uppercase"""
    source = {"Capitalize": "abc", "Uncapitalize": "ABC", "Lowercase": "ABC", "Uppercase": "abc"}[
        name
    ]
    bad = {"Capitalize": "abc", "Uncapitalize": "ABC", "Lowercase": "ABC", "Uppercase": "abc"}[name]
    asserts = SchemaAsserts(S.String.pipe(S.decode_to(S.String.check(check), transformation)))
    asserts.decoding().succeed(source, decoded)
    asserts.encoding().succeed(decoded)
    asserts.encoding().fail(bad, f"Expected a string with {message}")


def test_succeed():
    """succeed"""
    zero: S.LiteralSchema[Literal[0]] = S.Literal(0)
    a = S.Literal("a")
    schema = zero.pipe(S.decode_to(a, T.Transformation(G.succeed("a"), G.succeed(0))))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(0, "a")
    asserts.decoding().fail(1, "Expected 0")
    asserts.encoding().succeed("a", 0)
    asserts.encoding().fail("b", 'Expected "a"')


# ------------------------------------------------------------------ adapters


def test_decode_unknown_option_finite_from_string():
    """decodeUnknownOption / encodeUnknownOption / FiniteFromString"""
    assert S.decode_unknown_option(S.FiniteFromString)("1") == Some(1)
    assert S.decode_unknown_option(S.FiniteFromString)(None) is None
    assert S.encode_unknown_option(S.FiniteFromString)(1) == Some("1")
    assert S.encode_unknown_option(S.FiniteFromString)(None) is None


def test_decode_unknown_result_finite_from_string():
    """decodeUnknownResult / encodeUnknownResult / FiniteFromString"""
    assert S.decode_unknown_result(S.FiniteFromString)("1") == Ok(1)
    match S.decode_unknown_result(S.FiniteFromString)(None):
        case Err(error):
            assert error.message == "Expected string"
        case other:
            raise AssertionError(other)
    assert S.encode_unknown_result(S.FiniteFromString)(1) == Ok("1")
    match S.encode_unknown_result(S.FiniteFromString)(None):
        case Err(error):
            assert error.message == "Expected number"
        case other:
            raise AssertionError(other)


def test_decode_unknown_sync_finite_from_string():
    """decodeUnknownSync / encodeUnknownSync / FiniteFromString"""
    assert S.decode_unknown_sync(S.FiniteFromString)("1") == 1
    assert S.encode_unknown_sync(S.FiniteFromString)(1) == "1"
    with pytest.raises(S.SchemaError, match=r"^Expected string$"):
        S.decode_unknown_sync(S.FiniteFromString)(None)
    with pytest.raises(S.SchemaError, match=r"^Expected number$"):
        S.encode_unknown_sync(S.FiniteFromString)(None)


class _Defect(Exception):
    pass


_DEFECT = _Defect("defect")
_MIXED: Cause[Issue] = Cause((Fail(InvalidValue({"message": "schema issue"})), Die(_DEFECT)))
_DIES: Cause[Issue] = Cause((Die(_DEFECT),))


def _failing(cause: Cause[Issue]) -> tuple[S.Bottom[str, str], S.Bottom[str, str]]:
    getter: G.Getter[str, str] = G.transform_optional_effect(lambda _, __: fail_cause(cause))
    return (
        S.String.pipe(S.decode(T.Transformation(getter, G.passthrough()))),
        S.String.pipe(S.encode(T.Transformation(G.passthrough(), getter))),
    )


def _raises_with_defect(message: str, run: Callable[[], object]) -> None:
    with pytest.raises(RuntimeError) as raised:
        run()
    assert raised.value.args == (message,)
    assert raised.value.__cause__ is _DEFECT


@pytest.mark.parametrize(
    "cause", [_DIES, _MIXED], ids=["not a schema issue", "a schema issue and a defect"]
)
def test_option_adapters_throw_when_the_cause_is_not_only_schema_issues(cause: Cause[Issue]):
    """decodeUnknownOption / encodeUnknownOption / should throw an error when the cause is not a schema issue
    decodeUnknownOption / encodeUnknownOption / should throw an error when the cause contains both a schema issue and a defect"""  # noqa: E501
    decoding, encoding = _failing(cause)
    message = "Option adapter can only return none for schema issues"
    _raises_with_defect(message, lambda: S.decode_unknown_option(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_option(encoding)("a"))


def test_result_adapters_throw_when_the_cause_contains_both_a_schema_issue_and_a_defect():
    """decodeUnknownResult / encodeUnknownResult / should throw an error when the cause contains both a schema issue and a defect"""  # noqa: E501
    decoding, encoding = _failing(_MIXED)
    message = "Result adapter can only return schema issues"
    _raises_with_defect(message, lambda: S.decode_unknown_result(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_result(encoding)("a"))


def test_sync_adapters_throw_when_the_cause_contains_both_a_schema_issue_and_a_defect():
    """decodeUnknownSync / encodeUnknownSync / should throw an error when the cause contains both a schema issue and a defect"""  # noqa: E501
    decoding, encoding = _failing(_MIXED)
    message = "Sync adapter can only throw schema errors"
    _raises_with_defect(message, lambda: S.decode_unknown_sync(decoding)("a"))
    _raises_with_defect(message, lambda: S.encode_unknown_sync(encoding)("a"))


def test_exit_adapters_preserve_mixed_schema_issue_and_defect_causes():
    """decodeUnknownExit / encodeUnknownExit / should preserve mixed schema issue and defect causes"""  # noqa: E501
    decoding, encoding = _failing(_MIXED)
    for exit in (S.decode_unknown_exit(decoding)("a"), S.encode_unknown_exit(encoding)("a")):
        assert isinstance(exit, Failure)
        assert any(isinstance(r, Die) for r in exit.cause.reasons)
        match exit.cause.find_error():
            case Ok(error):
                assert isinstance(error, S.SchemaError)
            case other:
                raise AssertionError(other)


def _declaration(cause: Cause[Issue]) -> S.Bottom[str]:
    def parser(*_: object) -> Effect[str, Issue]:
        return fail_cause(cause)

    def run(_: object) -> Callable[..., Effect[str, Issue]]:
        return parser

    return S.declare_constructor((), run)


def test_make_option_throws_when_the_cause_is_not_a_schema_issue():
    """makeOption / should throw an error when the cause is not a schema issue"""
    # Effect fails a ``withConstructorDefault``; a declaration's parser gives
    # the same cause.
    schema = _declaration(_DIES)
    _raises_with_defect(
        "Option adapter can only return none for schema issues", lambda: schema.make_option("a")
    )


def test_make_throws_when_the_cause_contains_both_a_schema_issue_and_a_defect():
    """make / should throw an error when the cause contains both a schema issue and a defect"""
    schema = _declaration(_MIXED)
    _raises_with_defect(
        "Constructor adapter can only throw schema issues", lambda: schema.make("a")
    )


@testing.effect
def test_make_effect_preserves_mixed_schema_issue_and_defect_causes():
    """makeEffect / should preserve mixed schema issue and defect causes"""
    schema = _declaration(_MIXED)
    exit = yield from schema.make_effect("a").exit()
    assert isinstance(exit, Failure)
    assert any(isinstance(r, Die) for r in exit.cause.reasons)
    match exit.cause.find_error():
        case Ok(error):
            assert is_issue(error)
        case other:
            raise AssertionError(other)


def _slow(value: Option[str], _: object) -> Effect[Option[str]]:
    return sleep(0.001).as_(value)


_ASYNC = S.String.pipe(
    S.decode(T.Transformation(G.transform_optional_effect(_slow), G.passthrough()))
)


def test_sync_adapters_block_on_async_decoding():
    """decodeUnknownResult / should throw on async decoding
    decodeUnknownExit / should die on async decoding"""
    with pytest.raises(RuntimeError):
        S.decode_unknown_result(_ASYNC)("1")
    ran = S.decode_unknown_exit(_ASYNC)("1")
    assert isinstance(ran, Failure)
    assert isinstance(ran.cause.defects[0], AsyncFiberError)


class _MagicNumber(Tag[float]):
    pass


def _times_magic(n: float, _: object) -> Effect[float, Never, _MagicNumber]:
    return _MagicNumber().map(lambda magic: n * magic)


_NEEDS_MAGIC = S.Number.pipe(
    S.decode(T.Transformation(G.transform_effect(_times_magic), G.passthrough()))
)


def test_decode_unknown_result_should_throw_on_missing_dependency():
    """decodeUnknownResult / should throw on missing dependency"""
    with pytest.raises(RuntimeError, match=r"^Result adapter can only return schema issues"):
        S.decode_unknown_result(cast("S.Bottom[float]", _NEEDS_MAGIC))(1)


def test_decode_unknown_exit_should_die_on_missing_dependency():
    """decodeUnknownExit / should die on missing dependency"""
    # Effect passes the schema ``as any``: its service is never provided.
    exit = S.decode_unknown_exit(cast("S.Bottom[float]", _NEEDS_MAGIC))(1)
    assert isinstance(exit, Failure)
    assert all(isinstance(r, Die) for r in exit.cause.reasons)


# ----------------------------------------------------------- annotateEncoded


def test_annotate_encoded_non_transforming_schema():
    """annotateEncoded / non-transforming schema"""
    schema = S.String.annotate_encoded(title="encoded title")
    assert (S.to_encoded(schema).ast.annotations or {}).get("title") == "encoded title"


def test_annotate_encoded_transforming_schema():
    """annotateEncoded / transforming schema"""
    schema = S.NumberFromString.annotate_encoded(title="encoded title")
    assert (S.to_encoded(schema).ast.annotations or {}).get("title") == "encoded title"
    assert (S.to_type(schema).ast.annotations or {}).get("title") is None


# ------------------------------------- duration and offset transformations


def test_duration_and_offset_transformations_decode_through_decode_to():
    """pyfect: ``T.duration_from_*`` and ``T.time_zone_offset_from_number``
    (Effect's ``durationFrom*`` / ``timeZoneOffsetFromNumber``, which its
    tests reach only through the schemas built on them)"""
    from_text = S.String.pipe(S.decode_to(S.Duration, T.duration_from_string))
    SchemaAsserts(from_text).decoding().succeed("2 seconds", timedelta(seconds=2))
    SchemaAsserts(from_text).encoding().succeed(timedelta(milliseconds=5), "5 millis")
    from_nanos = S.BigInt.pipe(S.decode_to(S.Duration, T.duration_from_nanos))
    SchemaAsserts(from_nanos).decoding().succeed(3000, timedelta(microseconds=3))
    from_millis = S.Number.pipe(S.decode_to(S.Duration, T.duration_from_millis))
    SchemaAsserts(from_millis).encoding().succeed(timedelta(milliseconds=1.5), 1.5)
    offset = S.Int.pipe(S.decode_to(S.TimeZoneOffset, T.time_zone_offset_from_number))
    decoding = SchemaAsserts(offset).decoding()
    decoding.succeed(3_600_000, timezone(timedelta(hours=1)))
    decoding.fail(86_400_000, "Expected an offset strictly between -24 and +24 hours")
