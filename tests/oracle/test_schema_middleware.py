"""Ports of Effect's ``Schema.test.ts``: middleware, ``catchDecoding`` /
``catchEncoding``, decoding defaults, ``checkEffect``, optional fields,
``asOption`` and ``decodeTo`` / ``encodeTo`` as composition. Each test's
docstring is the Effect test title, prefixed by its ``describe`` block.
``TestSchema.Asserts`` is ``testing.SchemaAsserts``; its ``provide(tag,
service)`` gives the schema a service.

Python mappings: ``catchDecodingWithContext`` / ``catchEncodingWithContext``
are ``catch_decoding`` / ``catch_encoding`` (their handlers may need
services; the types carry them); a service ``{ fallback: Effect<A> }`` is a
``Tag[A]`` holding the fallback value. ``Effect.delay(100)`` is a 0.01 s
delay. ``optionalKey`` on a struct key is ``NotRequired``. A middleware
gets the parse as an effect of ``Option``: ``Some(value)`` or ``None``.

Omitted:
- ``undefined``: "Optional Fields / Optional Property", "... / Optional
  Property with Nullability", "... / Optional Property to Exact Optional
  Property", "... / Optional Property with Nullability to Optional
  Property", "asOption / optional -> Option", every "withDecodingDefault"
  and "withDecodingDefaultType" title (``optional`` and the standalone
  ``undefined`` input), and the ``undefined`` inputs of the
  "withDecodingDefaultKey" / "withDecodingDefaultTypeKey" titles (Python
  has one ``None``, a value; a missing key is the only absence).
- "decodeTo as composition", "encodeTo as composition": ported without the
  ``UndefinedOr(Number)`` field's ``undefined`` cases.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Never, NotRequired, TypedDict

from pyfect import Effect
from pyfect import effect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.context import Tag
from pyfect.exit import Failure, Success
from pyfect.option import Option, Some
from pyfect.result import Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import Encoding, Forbidden, InvalidType, InvalidValue, Issue
from pyfect.testing import SchemaAsserts


class _Fallback(Tag[str]):
    pass


class _NumberFallback(Tag[float]):
    pass


def _b(_: Issue) -> Effect[Option[str], Issue]:
    return fx.succeed(Some("b"))


# ------------------------------------------------------------- catchDecoding


def test_catch_decoding_sync_fallback():
    """catchDecoding / sync fallback"""
    schema = S.String.pipe(S.catch_decoding(_b)).check(S.is_non_empty())
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed("a")
    asserts.decoding().succeed(None, "b")
    asserts.decoding().fail("", "Expected a value with a length of at least 1")
    asserts.encoding().succeed("a")
    asserts.encoding().fail(None, "Expected string")


def test_catch_decoding_async_fallback():
    """catchDecoding / async fallback"""
    schema = S.String.pipe(S.catch_decoding(lambda _: _b(_).delay(0.01)))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a")
    decoding.succeed(None, "b")


def _from_service(_: Issue) -> Effect[Option[str], Issue, _Fallback]:
    return _Fallback().map(Some)


def test_catch_decoding_with_context():
    """catchDecodingWithContext"""
    schema = S.String.pipe(S.catch_decoding(_from_service))
    decoding = SchemaAsserts(schema).decoding().provide(_Fallback, "b")
    decoding.succeed("a")
    decoding.succeed(None, "b")


# --------------------------------------------------------- middlewareDecoding


def _zero_unless_not_a_string(issue: Issue) -> Effect[Option[float], Issue, _NumberFallback]:
    if isinstance(issue, Encoding) and isinstance(issue.issue, InvalidType):
        return fx.fail(issue)
    return _NumberFallback().map(Some)


def _provide_zero(
    effect: Effect[Option[float], Issue, _NumberFallback], options: S.ParseOptions
) -> Effect[Option[float], Issue]:
    return effect.pipe(fx.provide_service(_NumberFallback, 0.0))


def test_middleware_decoding_providing_a_service():
    """middlewareDecoding / providing a service"""
    schema = S.FiniteFromString.pipe(S.catch_decoding(_zero_unless_not_a_string)).pipe(
        S.middleware_decoding(_provide_zero)
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("1", 1)
    decoding.succeed("a", 0)
    decoding.fail(None, "Expected string")


def _forbidden(
    effect: Effect[Option[str], Issue], options: S.ParseOptions
) -> Effect[Option[str], Issue]:
    return fx.fail(Forbidden({"message": "my message"}))


def test_middleware_decoding_forced_failure():
    """middlewareDecoding / forced failure"""
    schema = S.String.pipe(S.middleware_decoding(_forbidden))
    SchemaAsserts(schema).decoding().fail("1", "my message")


# -------------------------------------------------------------- catchEncoding

_INT = S.Number.check(S.is_int())
"""Effect's ``Int``, a ``number``: pyfect's ``Int`` is an ``int``."""


def _zero(_: Issue) -> Effect[Option[float], Issue]:
    # ``0``, an ``int``: ``Int`` takes no float.
    return fx.succeed(Some(0))


def test_catch_encoding_sync_fallback():
    """catchEncoding / sync fallback"""
    schema = S.Number.pipe(S.catch_encoding(_zero)).pipe(S.encode_to(_INT))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(1)
    asserts.decoding().fail(1.2, "Expected an integer")
    asserts.encoding().succeed(1)
    asserts.encoding().succeed(None, 0)
    asserts.encoding().fail(1.2, "Expected an integer")


def test_catch_encoding_async_fallback():
    """catchEncoding / async fallback"""
    schema = S.Number.pipe(S.catch_encoding(lambda _: _zero(_).delay(0.01))).pipe(S.encode_to(_INT))
    encoding = SchemaAsserts(schema).encoding()
    encoding.succeed(1)
    encoding.succeed(None, 0)
    encoding.fail(1.2, "Expected an integer")


def _number_from_service(_: Issue) -> Effect[Option[float], Issue, _NumberFallback]:
    return _NumberFallback().map(Some)


def test_catch_encoding_with_context():
    """catchEncodingWithContext"""
    schema = S.Number.pipe(S.catch_encoding(_number_from_service)).pipe(S.encode_to(_INT))
    encoding = SchemaAsserts(schema).encoding().provide(_NumberFallback, 0)
    encoding.succeed(1)
    encoding.succeed(None, 0)
    encoding.fail(1.2, "Expected an integer")


# --------------------------------------------------------- middlewareEncoding


def _b_unless_not_a_number(issue: Issue) -> Effect[Option[str], Issue, _Fallback]:
    if isinstance(issue, InvalidType):
        return fx.fail(issue)
    return _Fallback().map(Some)


def _provide_b(
    effect: Effect[Option[str], Issue, _Fallback], options: S.ParseOptions
) -> Effect[Option[str], Issue]:
    return effect.pipe(fx.provide_service(_Fallback, "b"))


def test_middleware_encoding_providing_a_service():
    """middlewareEncoding / providing a service"""
    schema = S.FiniteFromString.pipe(S.catch_encoding(_b_unless_not_a_number)).pipe(
        S.middleware_encoding(_provide_b)
    )
    encoding = SchemaAsserts(schema).encoding()
    encoding.succeed(1, "1")
    encoding.succeed(math.nan, "b")
    encoding.fail(None, "Expected number")


def test_middleware_encoding_forced_failure():
    """middlewareEncoding / forced failure"""
    schema = S.String.pipe(S.middleware_encoding(_forbidden))
    SchemaAsserts(schema).encoding().fail(1, "my message")


# ------------------------------------------------------------ Optional Fields


class _OptionalNumber(TypedDict):
    a: NotRequired[float]


class _OptionalNullableNumber(TypedDict):
    a: NotRequired[float | None]


def test_optional_fields_exact_optional_property():
    """Optional Fields / Exact Optional Property"""
    asserts = SchemaAsserts(S.Struct(_OptionalNumber, a=S.FiniteFromString))
    asserts.decoding().succeed({"a": "1"}, {"a": 1})
    asserts.decoding().succeed({})
    asserts.encoding().succeed({"a": 1}, {"a": "1"})
    asserts.encoding().succeed({})


def test_optional_fields_exact_optional_property_with_nullability():
    """Optional Fields / Exact Optional Property with Nullability"""
    schema = S.Struct(_OptionalNullableNumber, a=S.NullOr(S.FiniteFromString))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"a": "1"}, {"a": 1})
    asserts.decoding().succeed({})
    asserts.decoding().succeed({"a": None})
    asserts.encoding().succeed({"a": 1}, {"a": "1"})
    asserts.encoding().succeed({})
    asserts.encoding().succeed({"a": None})


class _OptionNumber(TypedDict):
    a: Option[float]


def _some[A](input: Option[A]) -> Option[Option[A]]:
    return Some(input)


def _flatten[A](input: Option[Option[A]]) -> Option[A]:
    return None if input is None else input.value


def test_as_option_optional_key_to_option():
    """asOption / optionalKey -> Option"""
    transformation: T.Transformation[Option[float], float] = T.transform_optional(
        decode=_some, encode=_flatten
    )
    field = S.optional_key(S.FiniteFromString).pipe(S.decode_to(S.Option(S.Number), transformation))
    asserts = SchemaAsserts(S.Struct(_OptionNumber, a=field))
    asserts.decoding().succeed({"a": "1"}, {"a": Some(1)})
    asserts.decoding().succeed({}, {"a": None})
    asserts.encoding().succeed({"a": Some(1)}, {"a": "1"})
    asserts.encoding().succeed({"a": None}, {})


class _From(TypedDict):
    a: str
    b: float


class _To(TypedDict):
    a: float
    b: float


def test_decode_to_as_composition():
    """decodeTo as composition"""
    from_ = S.Struct(_From, b=S.FiniteFromString)
    to = S.Struct(_To, a=S.FiniteFromString)
    asserts = SchemaAsserts(from_.pipe(S.decode_to(to)))
    asserts.decoding().succeed({"a": "1", "b": "2"}, {"a": 1, "b": 2})
    asserts.encoding().succeed({"a": 1, "b": 2}, {"a": "1", "b": "2"})
    asserts.encoding().fail({"a": 1, "b": math.nan}, 'Expected a finite number\n  at ["b"]')


def test_encode_to_as_composition():
    """encodeTo as composition"""
    from_ = S.Struct(_From, b=S.FiniteFromString)
    to = S.Struct(_To, a=S.FiniteFromString)
    # ``to`` encodes to a ``Mapping``, ``from_`` decodes to ``_From``: a
    # passthrough from the supertype says they meet.
    asserts = SchemaAsserts(to.pipe(S.encode_to(from_, T.passthrough_supertype())))
    asserts.decoding().succeed({"a": "1", "b": "2"}, {"a": 1, "b": 2})
    asserts.decoding().fail({"a": "1", "b": None}, 'Expected string\n  at ["b"]')
    asserts.encoding().succeed({"a": 1, "b": 2}, {"a": "1", "b": "2"})
    asserts.encoding().fail({"a": 1, "b": math.nan}, 'Expected a finite number\n  at ["b"]')


# --------------------------------------------------------------- checkEffect


def _not_empty(text: str, options: S.ParseOptions) -> Effect[G.CheckOutput]:
    issue = InvalidValue({"message": "input should not be empty string"}) if text == "" else None
    return fx.succeed(issue).delay(0.01)


def test_check_effect_no_context():
    """checkEffect / no context"""
    schema = S.String.pipe(S.decode(T.Transformation(G.check_effect(_not_empty), G.passthrough())))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed("a")
    decoding.fail("", "input should not be empty string")


def _not_empty_with_service(
    text: str, options: S.ParseOptions
) -> Effect[G.CheckOutput, Never, _Fallback]:
    def check(_: str) -> G.CheckOutput:
        return InvalidValue({"message": "input should not be empty string"}) if text == "" else None

    return _Fallback().map(check)


def test_check_effect_with_context():
    """checkEffect / with context"""
    transformation = T.Transformation(G.check_effect(_not_empty_with_service), G.passthrough())
    schema = S.String.pipe(S.decode(transformation))
    decoding = SchemaAsserts(schema).decoding().provide(_Fallback, "b")
    decoding.succeed("a")
    decoding.fail("", "input should not be empty string")


# ----------------------------------------------------- withDecodingDefaultKey


class _ANumber(TypedDict):
    a: float


class _Nested(TypedDict):
    a: _ANumber


def _one() -> S.DecodeToSchema[float, str]:
    return S.FiniteFromString.pipe(S.with_decoding_default_key(fx.succeed("1")))


def test_with_decoding_default_key_keeps_successful_decoding_defaults_eager():
    """withDecodingDefaultKey / keeps successful decoding defaults eager"""
    schema = S.Struct(_ANumber, a=_one())
    assert schema.ast.parse({}, {}) == Success({"a": 1})


def test_with_decoding_default_key_should_return_a_decoding_default_value_if_the_key_is_missing():
    """withDecodingDefaultKey / should return a decoding default value if the key is missing"""
    decoding = SchemaAsserts(S.Struct(_ANumber, a=_one())).decoding()
    decoding.succeed({}, {"a": 1})
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.fail({"a": None}, 'Expected string\n  at ["a"]')


def test_with_decoding_default_key_by_default_should_pass_through_the_value():
    """withDecodingDefaultKey / by default should pass through the value"""
    SchemaAsserts(S.Struct(_ANumber, a=_one())).encoding().succeed({"a": 1}, {"a": "1"})


def test_with_decoding_default_key_should_omit_the_value_if_the_encoding_strategy_is_set_to_omit():
    """withDecodingDefaultKey / should omit the value if the encoding strategy is set to omit"""
    field = S.FiniteFromString.pipe(
        S.with_decoding_default_key(fx.succeed("1"), encoding_strategy="omit")
    )
    SchemaAsserts(S.Struct(_ANumber, a=field)).encoding().succeed({"a": 1}, {})


def _empty() -> Effect[Mapping[str, object], S.SchemaError]:
    return fx.succeed({})


def test_with_decoding_default_key_nested_default_values():
    """withDecodingDefaultKey / nested default values"""
    inner = S.Struct(_ANumber, a=_one()).pipe(S.with_decoding_default_key(_empty()))
    decoding = SchemaAsserts(S.Struct(_Nested, a=inner)).decoding()
    decoding.succeed({}, {"a": {"a": 1}})
    decoding.succeed({"a": {}}, {"a": {"a": 1}})
    decoding.succeed({"a": {"a": "2"}}, {"a": {"a": 2}})
    decoding.fail({"a": {"a": None}}, 'Expected string\n  at ["a"]["a"]')


_DEFAULT_FAILED = S.SchemaError(InvalidValue({"message": "decoding default failed"}))
_FAILING_STR: Effect[str, S.SchemaError] = fx.fail(_DEFAULT_FAILED)
_FAILING_NUMBER: Effect[float, S.SchemaError] = fx.fail(_DEFAULT_FAILED)


def test_with_decoding_default_key_effect_failing_with_schema_error_propagates_as_decode_failure():
    """withDecodingDefaultKey / Effect failing with SchemaError propagates as decode failure"""
    field = S.FiniteFromString.pipe(S.with_decoding_default_key(_FAILING_STR))
    decoding = SchemaAsserts(S.Struct(_ANumber, a=field)).decoding()
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.fail({}, 'decoding default failed\n  at ["a"]')


def test_with_decoding_default_key_effect_failing_with_schema_error_and_a_defect_preserves_the_mixed_cause():  # noqa: E501
    """withDecodingDefaultKey / Effect failing with SchemaError and a defect preserves the mixed cause"""  # noqa: E501
    # Effect's ``Cause.combine`` (pyfect's ``merge`` would make the error a defect).
    cause: Cause[S.SchemaError] = Cause((Fail(_DEFAULT_FAILED), Die(RuntimeError("defect"))))
    field = S.FiniteFromString.pipe(S.with_decoding_default_key(_mixed(cause)))
    exit = S.decode_unknown_exit(S.Struct(_ANumber, a=field))({})
    assert isinstance(exit, Failure)
    assert any(isinstance(r, Die) for r in exit.cause.reasons)
    match exit.cause.find_error():
        case Ok(error):
            assert error.message == 'decoding default failed\n  at ["a"]'
        case other:
            raise AssertionError(other)


def _mixed(cause: Cause[S.SchemaError]) -> Effect[str, S.SchemaError]:
    return fx.fail_cause(cause)


def test_with_decoding_default_key_default_effect_can_require_a_service():
    """withDecodingDefaultKey / default Effect can require a service"""
    field = S.FiniteFromString.pipe(S.with_decoding_default_key(_Fallback()))
    decoding = SchemaAsserts(S.Struct(_ANumber, a=field)).decoding().provide(_Fallback, "3")
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.succeed({}, {"a": 3})


# ------------------------------------------------- withDecodingDefaultTypeKey


def _type_one() -> S.DecodeToSchema[float, str]:
    return S.FiniteFromString.pipe(S.with_decoding_default_type_key(fx.succeed(1.0)))


def test_with_decoding_default_type_key_should_return_a_decoding_default_value_if_the_key_is_missing():  # noqa: E501
    """withDecodingDefaultTypeKey / should return a decoding default value if the key is missing"""
    decoding = SchemaAsserts(S.Struct(_ANumber, a=_type_one())).decoding()
    decoding.succeed({}, {"a": 1})
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.fail({"a": None}, 'Expected string\n  at ["a"]')


def test_with_decoding_default_type_key_by_default_should_pass_through_the_value():
    """withDecodingDefaultTypeKey / by default should pass through the value"""
    SchemaAsserts(S.Struct(_ANumber, a=_type_one())).encoding().succeed({"a": 1}, {"a": "1"})


def test_with_decoding_default_type_key_should_omit_the_value_if_the_encoding_strategy_is_set_to_omit():  # noqa: E501
    """withDecodingDefaultTypeKey / should omit the value if the encoding strategy is set to omit"""
    field = S.FiniteFromString.pipe(
        S.with_decoding_default_type_key(fx.succeed(1.0), encoding_strategy="omit")
    )
    SchemaAsserts(S.Struct(_ANumber, a=field)).encoding().succeed({"a": 1}, {})


def test_with_decoding_default_type_key_nested_default_values():
    """withDecodingDefaultTypeKey / nested default values"""
    default: _ANumber = {"a": 1}
    inner = S.Struct(_ANumber, a=_type_one()).pipe(
        S.with_decoding_default_type_key(fx.succeed(default))
    )
    decoding = SchemaAsserts(S.Struct(_Nested, a=inner)).decoding()
    decoding.succeed({}, {"a": {"a": 1}})
    decoding.succeed({"a": {}}, {"a": {"a": 1}})
    decoding.succeed({"a": {"a": "2"}}, {"a": {"a": 2}})
    decoding.fail({"a": {"a": None}}, 'Expected string\n  at ["a"]["a"]')


def test_with_decoding_default_type_key_effect_failing_with_schema_error_propagates_as_decode_failure():  # noqa: E501
    """withDecodingDefaultTypeKey / Effect failing with SchemaError propagates as decode failure"""
    field = S.FiniteFromString.pipe(S.with_decoding_default_type_key(_FAILING_NUMBER))
    decoding = SchemaAsserts(S.Struct(_ANumber, a=field)).decoding()
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.fail({}, 'decoding default failed\n  at ["a"]')


def test_with_decoding_default_type_key_default_effect_can_require_a_service():
    """withDecodingDefaultTypeKey / default Effect can require a service"""
    field = S.FiniteFromString.pipe(S.with_decoding_default_type_key(_NumberFallback()))
    decoding = SchemaAsserts(S.Struct(_ANumber, a=field)).decoding().provide(_NumberFallback, 3.0)
    decoding.succeed({"a": "2"}, {"a": 2})
    decoding.succeed({}, {"a": 3})
