"""Ports of Effect's ``schema/Schema.test.ts``: tuples, arrays, ``suspend``, the
collection and data-type declarations and the date-time, zone and
``instanceOf`` declarations. Each test's docstring is the Effect test title,
prefixed by its ``describe`` block. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

Python mappings: ``Schema.Tuple([...])`` is ``S.Tuple(...)`` and decodes to
a ``tuple``; ``Array`` / ``NonEmptyArray`` decode to a ``tuple``, ``List``
(Effect's ``mutable(Array(...))``) to a ``list``; ``optionalKey`` on a
tuple element is ``S.optional_key``; ``TupleWithRest(schema, [rest,
...post])`` is ``S.TupleWithRest(schema, rest, *post)``. ``ReadonlySet`` /
``HashSet`` are ``S.FrozenSet`` (a ``frozenset``), ``ReadonlyMap`` /
``HashMap`` ``S.Map`` (a ``dict``), ``Chunk`` an ``Array`` (a tuple). A
declaration reports a part at the Python attribute holding it: Effect's
``["success"]`` / ``["failure"]`` of a ``Result`` are ``["value"]`` /
``["error"]`` (``Ok.value``, ``Err.error``). ``Option.none()`` is ``None``,
so an ``Option`` accepts ``None`` and the "not an Option" input is ``1``.
A ``Die`` holds an exception, so a ``Cause`` / ``Exit`` defect schema makes
one (``S.instance_of(...)``; Effect's ``Unknown`` / ``Defect()``).

Ported with a substitute: "Cause / Cause(FiniteFromString,
FiniteFromString)": a ``Die`` holds an exception, so its defect schema is
``instance_of(ValueError)``.

Omitted:
- Ported in ``test_schema_transform.py``: "RedactedFromValue / should
  decode a value", "OptionFromNullOr", "OptionFromOptionalNullOr / ...".
- Python's ``List`` is its own schema, not ``mutable(...)`` of another:
  "mutable / does not support withDecodingDefaultType before mutable",
  "mutable / preserves annotations, checks, encoding checks, and context".
- ``undefined``: "OptionFromUndefinedOr", "OptionFromNullishOr / ...".
- JavaScript's ``Date``: "DateTimeUtcFromValidDate", "Date";
  "DateTimeUtcFromString" and "DateTimeUtcFromMillis" are ported in
  ``test_schema_codecs.py``.
- Ported in ``test_schema_errors.py``: "Defect", "ErrorInstance and Defect
  memoize equivalent options", "Error", "Exit / Exit(FiniteFromString,
  String, Defect)", "Cause / strict encoding preserves the default wire
  format for every reason variant".
- "CauseReason / CauseReason(FiniteFromString, FiniteFromString)": only
  draws values, and a defect schema here is an ``instance_of`` an
  exception class, which has no strategy.
- "withConstructorDefault / Tuple / Tuple & Some", "... / nested defaults
  (Struct)", "... / inner defaults (Tuple)", "... / nested defaults
  (Tuple)": ported in ``test_schema_constructor_default.py``.
- "Tuple / A required element cannot follow an optional element" with
  ``Schema.optional`` and "TupleWithRest / An optional element cannot
  follow a rest element": ``optional`` is ``optionalKey`` of ``UndefinedOr``
  (no ``undefined``), and a rest schema is a ``Codec``, so an optional rest
  element is a type error (pinned in ``tests/type_checks.py``).
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, TypedDict, TypeIs
from zoneinfo import ZoneInfo

import pytest

from pyfect import byte_size, cause, exit, redacted
from pyfect import effect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.option import Option, Some
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions
from pyfect.testing import SchemaAsserts

# ------------------------------------------------------------------- Tuple


def test_tuple_a_required_element_cannot_follow_an_optional_element():
    """Tuple / A required element cannot follow an optional element"""
    with pytest.raises(
        ValueError, match=r"^A required element cannot follow an optional element\. ts\(1257\)$"
    ):
        S.Tuple(S.optional_key(S.String), S.String)


def test_tuple_should_fail_on_unexpected_indexes():
    """Tuple / should fail on unexpected indexes"""
    asserts = SchemaAsserts(S.Tuple(S.String))
    asserts.decoding().fail(["a", "b"], "Expected no excess property\n  at [1]")
    asserts.decoding(errors="all").fail(
        ["a", "b", "c"],
        "Expected no excess property\n  at [1]\nExpected no excess property\n  at [2]",
    )


def test_tuple_readonly_string():
    """Tuple / readonly [string]"""
    schema = S.Tuple(S.NonEmptyString)
    asserts = SchemaAsserts(schema)
    assert schema.elements == (S.NonEmptyString,)

    make = asserts.make()
    make.succeed(("a",))
    make.fail(("",), "Expected a value with a length of at least 1\n  at [0]")

    decoding = asserts.decoding()
    decoding.succeed(["a"], ("a",))
    decoding.fail(None, "Expected array")
    decoding.fail([], "Missing key\n  at [0]")
    decoding.fail([1], "Expected string\n  at [0]")

    encoding = asserts.encoding()
    encoding.succeed(("a",))
    encoding.fail((), "Missing key\n  at [0]")
    encoding.fail((1,), "Expected string\n  at [0]")


def test_tuple_readonly_string_optional():
    """Tuple / readonly [string?]"""
    asserts = SchemaAsserts(S.Tuple(S.optional_key(S.String)))
    for direction in (asserts.make(), asserts.decoding(), asserts.encoding()):
        direction.succeed(("a",))
        direction.succeed(())


# ------------------------------------------------------------------- Array


def test_array_should_expose_the_element_schema_via_value():
    """Array / should expose the element schema via .value"""
    schema = S.Array(S.String)
    assert schema.value is S.String
    assert schema.annotate().value is S.String


def test_array_readonly_string_array():
    """Array / readonly string[]"""
    asserts = SchemaAsserts(S.Array(S.String))
    asserts.make().succeed(("a", "b"))
    decoding = asserts.decoding()
    decoding.succeed(["a", "b"], ("a", "b"))
    decoding.fail(["a", 1], "Expected string\n  at [1]")
    encoding = asserts.encoding()
    encoding.succeed(("a", "b"))
    encoding.fail(("a", 1), "Expected string\n  at [1]")


# ----------------------------------------------------------- NonEmptyArray


def test_non_empty_array_should_expose_the_element_schema_via_value():
    """NonEmptyArray / should expose the element schema via .value"""
    assert S.NonEmptyArray(S.String).value is S.String


def test_non_empty_array_readonly_string_array():
    """NonEmptyArray / readonly string[]"""
    asserts = SchemaAsserts(S.NonEmptyArray(S.String))
    make = asserts.make()
    make.succeed(("a",))
    make.succeed(("a", "b"))
    for direction in (asserts.decoding(), asserts.encoding()):
        direction.succeed(("a",))
        direction.succeed(("a", "b"))
        direction.fail((), "Missing key\n  at [0]")
        direction.fail(("a", 1), "Expected string\n  at [1]")


# ----------------------------------------------------------- TupleWithRest


def test_tuple_with_rest_a_required_element_cannot_follow_an_optional_element():
    """TupleWithRest / A required element cannot follow an optional element"""
    with pytest.raises(
        ValueError, match=r"^A required element cannot follow an optional element\. ts\(1257\)$"
    ):
        S.TupleWithRest(S.Tuple(S.optional_key(S.String)), S.Boolean, S.String)


def test_tuple_with_rest_finite_from_string_string_plus_boolean_string():
    """TupleWithRest / [FiniteFromString, String] + [Boolean, String]"""
    schema = S.TupleWithRest(S.Tuple(S.FiniteFromString, S.String), S.Boolean, S.String)
    asserts = SchemaAsserts(schema)

    decoding = asserts.decoding()
    decoding.succeed(["1", "a", "b"], (1, "a", "b"))
    decoding.succeed(["1", "a", True, "b"], (1, "a", True, "b"))
    decoding.succeed(["1", "a", True, True, "b"], (1, "a", True, True, "b"))
    decoding.fail(["1", "a"], "Missing key\n  at [2]")
    decoding.fail(["1", "a", True], "Expected string\n  at [2]")
    decoding.fail(["1", "a", "b", "c"], "Expected boolean\n  at [2]")
    decoding.fail(["1", "a", True, "b", "c"], "Expected boolean\n  at [3]")

    encoding = asserts.encoding()
    encoding.succeed((1, "a", "b"), ("1", "a", "b"))
    encoding.succeed((1, "a", True, "b"), ("1", "a", True, "b"))


def test_tuple_with_rest_finite_from_string_string_plus_boolean_string_number():
    """TupleWithRest / [FiniteFromString, String] + [Boolean, String, Number]"""
    schema = S.TupleWithRest(
        S.Tuple(S.FiniteFromString, S.String), S.Boolean, S.String, S.FiniteFromString
    )
    asserts = SchemaAsserts(schema)

    decoding = asserts.decoding()
    decoding.succeed(["1", "a", "b", "2"], (1, "a", "b", 2))
    decoding.succeed(["1", "a", True, "b", "2"], (1, "a", True, "b", 2))
    decoding.succeed(["1", "a", True, True, "b", "2"], (1, "a", True, True, "b", 2))
    decoding.fail(["1", "a"], "Missing key\n  at [2]")
    decoding.fail(["1", "a", "b"], "Missing key\n  at [3]")
    decoding.fail(["1", "a", "b", "c"], "Expected a finite number\n  at [3]")

    encoding = asserts.encoding()
    encoding.succeed((1, "a", "b", 2), ("1", "a", "b", "2"))
    encoding.succeed((1, "a", True, "b", 2), ("1", "a", True, "b", "2"))


def test_tuple_with_rest_validates_every_post_rest_index():
    """TupleWithRest / [String] + [Boolean, String, Number, Number] validates every post-rest index"""  # noqa: E501
    schema = S.TupleWithRest(
        S.Tuple(S.String), S.Boolean, S.String, S.FiniteFromString, S.FiniteFromString
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.fail(["a", True, "b", "1", "x"], "Expected a finite number\n  at [4]")
    decoding.succeed(["a", True, "b", "1", "2"], ("a", True, "b", 1, 2))


# ----------------------------------------------------------------- suspend


class _Category(TypedDict):
    a: float
    categories: tuple["_Category", ...]


def test_suspend_should_work():
    """suspend / should work"""
    category: S.Bottom[_Category, object] = S.Struct(
        _Category,
        a=S.FiniteFromString.check(S.is_greater_than(0)),
        categories=S.Array(S.suspend(lambda: category)),
    )
    asserts = SchemaAsserts(category)

    decoding = asserts.decoding()
    decoding.succeed({"a": "1", "categories": []}, {"a": 1, "categories": ()})
    empty: list[object] = []
    decoding.succeed(
        {"a": "1", "categories": [{"a": "2", "categories": empty}]},
        {"a": 1, "categories": ({"a": 2, "categories": ()},)},
    )
    decoding.fail(
        {"a": "1", "categories": [{"a": "a", "categories": empty}]},
        'Expected a finite number\n  at ["categories"][0]["a"]',
    )

    encoding = asserts.encoding()
    encoding.succeed({"a": 1, "categories": ()}, {"a": "1", "categories": ()})
    encoding.succeed(
        {"a": 1, "categories": ({"a": 2, "categories": ()},)},
        {"a": "1", "categories": ({"a": "2", "categories": ()},)},
    )
    encoding.fail(
        {"a": 1, "categories": ({"a": -1, "categories": ()},)},
        'Expected a value greater than 0\n  at ["categories"][0]["a"]',
    )


# ---------------------------------------------------------------- Redacted


def test_redacted_should_expose_the_value():
    """Redacted / should expose the value"""
    schema = S.Redacted(S.String)
    assert schema.value is S.String
    assert schema.annotate().value is S.String


def test_redacted_does_not_expose_unwrapped_inputs():
    """Redacted / does not expose unwrapped inputs"""
    asserts = SchemaAsserts(S.Redacted(S.String))
    asserts.decoding().fail("secret", "Expected Redacted")
    asserts.encoding().fail("secret", "Expected Redacted")


def test_redacted_finite():
    """Redacted / Redacted(Finite)"""
    asserts = SchemaAsserts(S.Redacted(S.Int))
    for direction in (asserts.decoding(), asserts.encoding()):
        direction.succeed(Redacted(123))
        direction.fail(None, "Expected Redacted")
        direction.fail(Redacted("a"), 'Expected a valid value\n  at ["value"]')
        direction.fail(Redacted(1.2), 'Expected a valid value\n  at ["value"]')


def test_redacted_finite_from_string():
    """Redacted / Redacted(FiniteFromString)"""
    schema = S.Redacted(S.FiniteFromString.check(S.is_int()))
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed(Redacted("123"), Redacted(123))
    decoded = S.decode_unknown_sync(schema)(Redacted("123", label="secret"))
    assert redacted.value(decoded) == 123
    assert decoded.label == "secret"
    decoding.fail(None, "Expected Redacted")
    for input in (Redacted(None), Redacted("a"), Redacted("1.2")):
        decoding.fail(input, 'Expected a valid value\n  at ["value"]')

    encoding = asserts.encoding()
    encoding.succeed(Redacted(123), Redacted("123"))
    encoded = S.encode_sync(schema)(Redacted(123, label="secret"))
    assert redacted.value(encoded) == "123"
    assert encoded.label == "secret"
    encoding.fail(None, "Expected Redacted")
    for input in (Redacted(None), Redacted("a"), Redacted(1.2)):
        encoding.fail(input, 'Expected a valid value\n  at ["value"]')


def test_redacted_with_label():
    """Redacted / with label"""
    asserts = SchemaAsserts(S.Redacted(S.NonEmptyString, label="password"))

    decoding = asserts.decoding()
    decoding.succeed(Redacted("a", label="password"))
    decoding.fail(Redacted("a", label="API key"), 'Expected "password"\n  at ["label"]')
    decoding.fail(Redacted(1, label="API key"), 'Expected "password"\n  at ["label"]')
    decoding.fail(Redacted(1, label="password"), 'Expected a valid value\n  at ["value"]')

    encoding = asserts.encoding()
    encoding.succeed(Redacted("a", label="password"))
    encoding.fail(Redacted("a", label="API key"), 'Expected "password"\n  at ["label"]')
    encoding.fail(Redacted("", label="password"), 'Expected a valid value\n  at ["value"]')


# ------------------------------------------------------------------ Option


def test_option_should_expose_the_value():
    """Option / should expose the value"""
    schema = S.Option(S.String)
    assert schema.value is S.String
    assert schema.annotate().value is S.String


def test_option_finite_from_string():
    """Option / Option(FiniteFromString)"""
    asserts = SchemaAsserts(S.Option(S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed(None)
    decoding.succeed(Some("123"), Some(123))
    decoding.fail(1, "Expected Option")
    decoding.fail(Some(None), 'Expected string\n  at ["value"]')
    encoding = asserts.encoding()
    encoding.succeed(None)
    encoding.succeed(Some(123), Some("123"))
    encoding.fail(1, "Expected Option")
    encoding.fail(Some(None), 'Expected number\n  at ["value"]')


# ------------------------------------------------------------------ Result


def test_result_should_expose_the_values():
    """Result / should expose the values"""
    schema = S.Result(S.String, S.Number)
    assert schema.success is S.String
    assert schema.annotate().success is S.String
    assert schema.failure is S.Number
    assert schema.annotate().failure is S.Number


def test_result_finite_from_string_finite_from_string():
    """Result / Result(FiniteFromString, FiniteFromString)"""
    asserts = SchemaAsserts(S.Result(S.FiniteFromString, S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed(Ok("1"), Ok(1))
    decoding.succeed(Err("2"), Err(2))
    decoding.fail(None, "Expected Result")
    decoding.fail(Ok("a"), 'Expected a finite number\n  at ["success"]')
    decoding.fail(Err("b"), 'Expected a finite number\n  at ["failure"]')
    encoding = asserts.encoding()
    encoding.succeed(Ok(1), Ok("1"))
    encoding.succeed(Err(2), Err("2"))


# ------------------------------------------------------------ CauseReason


def test_cause_reason_should_expose_the_values():
    """CauseReason / should expose the values"""
    defects = S.instance_of(ValueError)
    schema = S.CauseReason(S.String, defects)
    assert schema.error is S.String
    assert schema.annotate().error is S.String
    assert schema.defect is defects
    assert schema.annotate().defect is defects


# ------------------------------------------------------------------- Cause


def test_cause_should_expose_the_values():
    """Cause / should expose the values"""
    defects = S.instance_of(ValueError)
    schema = S.Cause(S.String, defects)
    assert schema.error is S.String
    assert schema.annotate().error is S.String
    assert schema.defect is defects
    assert schema.annotate().defect is defects


def test_cause_finite_from_string_finite_from_string():
    """Cause / Cause(FiniteFromString, FiniteFromString)"""
    boom = ValueError("boom")
    asserts = SchemaAsserts(S.Cause(S.FiniteFromString, S.instance_of(ValueError)))
    decoding = asserts.decoding()
    decoding.succeed(cause.fail("1"), cause.fail(1))
    decoding.succeed(cause.die(boom))
    decoding.succeed(cause.interrupt(3))
    decoding.fail(cause.fail("a"), 'Expected a finite number\n  at ["reasons"][0]["error"]')
    decoding.fail(cause.die(TypeError("a")), 'Expected ValueError\n  at ["reasons"][0]["defect"]')
    encoding = asserts.encoding()
    encoding.succeed(cause.fail(1), cause.fail("1"))
    encoding.succeed(cause.die(boom))
    encoding.succeed(cause.interrupt(3))
    encoding.fail(cause.fail("a"), 'Expected number\n  at ["reasons"][0]["error"]')


# -------------------------------------------------------------------- Exit


def test_exit_should_expose_the_values():
    """Exit / should expose the values"""
    defects = S.instance_of(ValueError)
    schema = S.Exit(S.String, S.Number, defects)
    assert schema.value is S.String
    assert schema.annotate().value is S.String
    assert schema.error is S.Number
    assert schema.annotate().error is S.Number
    assert schema.defect is defects
    assert schema.annotate().defect is defects


def test_exit_finite_from_string_string_unknown():
    """Exit / Exit(FiniteFromString, String, Unknown)"""
    schema = S.Exit(S.FiniteFromString, S.String, S.instance_of(Exception))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(exit.succeed("123"), exit.succeed(123))
    decoding.succeed(exit.fail("boom"))
    decoding.fail(None, "Expected Exit")
    decoding.fail(exit.succeed(123), 'Expected string\n  at ["value"]')
    decoding.fail(exit.fail(None), 'Expected string\n  at ["cause"]["reasons"][0]["error"]')


# ----------------------------------------------------- sets, maps, chunks


def test_readonly_set():
    """ReadonlySet"""
    schema = S.FrozenSet(S.FiniteFromString)
    assert schema.value is S.FiniteFromString
    assert schema.annotate().value is S.FiniteFromString
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(frozenset({"1", "2", "3"}), frozenset({1, 2, 3}))
    decoding.fail(None, "Expected frozenset")
    decoding.fail(frozenset({None}), 'Expected string\n  at ["values"][0]')


def test_hash_set():
    """HashSet"""
    asserts = SchemaAsserts(S.FrozenSet(S.FiniteFromString))
    asserts.decoding().succeed(frozenset({"1", "2", "3"}), frozenset({1, 2, 3}))
    asserts.decoding().fail(frozenset({None}), 'Expected string\n  at ["values"][0]')
    asserts.encoding().succeed(frozenset({1, 2, 3}), frozenset({"1", "2", "3"}))


def test_chunk():
    """Chunk"""
    schema = S.Array(S.FiniteFromString)
    assert schema.value is S.FiniteFromString
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed(("1", "2", "3"), (1, 2, 3))
    asserts.decoding().fail(None, "Expected array")
    asserts.decoding().fail((None,), "Expected string\n  at [0]")
    asserts.encoding().succeed((1, 2, 3), ("1", "2", "3"))


def test_readonly_map():
    """ReadonlyMap"""
    schema = S.Map(S.String, S.FiniteFromString)
    assert schema.key is S.String
    assert schema.annotate().key is S.String
    assert schema.value is S.FiniteFromString
    assert schema.annotate().value is S.FiniteFromString
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    decoding.succeed({"a": "1"}, {"a": 1})
    decoding.fail(None, "Expected Mapping")
    decoding.fail({"a": None}, 'Expected string\n  at ["entries"][0][1]')
    asserts.encoding().succeed({"a": 1}, {"a": "1"})


def test_hash_map():
    """HashMap"""
    asserts = SchemaAsserts(S.Map(S.String, S.FiniteFromString))
    asserts.decoding().succeed({"a": "1"}, {"a": 1})
    asserts.decoding().fail({"a": None}, 'Expected string\n  at ["entries"][0][1]')
    asserts.encoding().succeed({"a": 1}, {"a": "1"})


# --------------------------------------------------- date-times and zones


_UTC = datetime(2021, 1, 1, tzinfo=UTC)


def test_date_time_utc():
    """DateTimeUtc"""
    asserts = SchemaAsserts(S.DateTimeUtc)
    asserts.decoding().succeed(_UTC)
    asserts.encoding().succeed(_UTC)


def test_time_zone_offset():
    """TimeZoneOffset"""
    zone = timezone(timedelta(hours=3))
    asserts = SchemaAsserts(S.TimeZoneOffset)
    asserts.decoding().succeed(zone)
    asserts.encoding().succeed(zone)


def test_time_zone_named():
    """TimeZoneNamed"""
    zone = ZoneInfo("Europe/London")
    asserts = SchemaAsserts(S.TimeZoneNamed)
    asserts.decoding().succeed(zone)
    asserts.encoding().succeed(zone)


def test_time_zone():
    """TimeZone"""
    asserts = SchemaAsserts(S.TimeZone)
    for zone in (timezone(timedelta(hours=3)), ZoneInfo("Europe/London")):
        asserts.decoding().succeed(zone)
        asserts.encoding().succeed(zone)


def test_date_time_zoned():
    """DateTimeZoned"""
    zoned = _UTC.astimezone(ZoneInfo("Europe/London"))
    asserts = SchemaAsserts(S.DateTimeZoned)
    asserts.decoding().succeed(zoned)
    asserts.encoding().succeed(zoned)


# -------------------------------------------------------------- instanceOf


class _MyError(Exception):
    pass


def test_instance_of_arg_message_string():
    """instanceOf / arg: message: string"""
    asserts = SchemaAsserts(S.instance_of(_MyError, expected="MyError"))
    for direction in (asserts.decoding(), asserts.encoding()):
        direction.succeed(_MyError("a"))
        direction.fail(None, "Expected MyError")


# -------------------------------------------------------- Tuple.mapElements


def test_tuple_map_elements_append_element():
    """Tuple.mapElements / appendElement"""
    schema = S.Tuple(S.String).map_elements(lambda es: (*es, S.Number))
    assert schema.elements == (S.String, S.Number)


def test_tuple_map_elements_append_elements():
    """Tuple.mapElements / appendElements"""
    schema = S.Tuple(S.String).map_elements(lambda es: (*es, S.Number, S.Boolean))
    assert schema.elements == (S.String, S.Number, S.Boolean)


def test_tuple_map_elements_pick():
    """Tuple.mapElements / pick"""
    schema = S.Tuple(S.String, S.Number, S.Boolean).map_elements(lambda es: (es[0], es[2]))
    assert schema.elements == (S.String, S.Boolean)


def test_tuple_map_elements_omit():
    """Tuple.mapElements / omit"""
    schema = S.Tuple(S.String, S.Number, S.Boolean).map_elements(
        lambda es: tuple(e for i, e in enumerate(es) if i != 1)
    )
    assert schema.elements == (S.String, S.Boolean)


def test_tuple_map_elements_evolve_string_to_optional_string():
    """Tuple.mapElements / evolve / readonly [string] -> readonly [string?]"""
    schema = S.Tuple(S.String).map_elements(lambda es: (S.optional_key(es[0]),))
    assert schema.elements == (S.optional_key(S.String),)
    SchemaAsserts(schema).decoding().succeed([], ())


def test_tuple_map_elements_evolve_string_number_to_string_optional_number():
    """Tuple.mapElements / evolve / readonly [string, number] -> readonly [string, number?]"""
    schema = S.Tuple(S.String, S.Number).map_elements(lambda es: (es[0], S.optional_key(es[1])))
    assert schema.elements == (S.String, S.optional_key(S.Number))
    SchemaAsserts(schema).decoding().succeed(["a"], ("a",))


def test_tuple_map_elements_rename_indices_partial_index_mapping():
    """Tuple.mapElements / renameIndices / partial index mapping"""
    schema = S.Tuple(S.String, S.Number, S.Boolean).map_elements(lambda es: (es[1], es[0], es[2]))
    assert schema.elements == (S.Number, S.String, S.Boolean)


def test_tuple_map_elements_rename_indices_full_index_mapping():
    """Tuple.mapElements / renameIndices / full index mapping"""
    schema = S.Tuple(S.String, S.Number, S.Boolean).map_elements(lambda es: es[::-1])
    assert schema.elements == (S.Boolean, S.Number, S.String)


def test_tuple_map_elements_null_or():
    """Tuple.mapElements / NullOr"""
    schema = S.Tuple(S.String, S.Number).map_elements(
        lambda es: tuple(S.Union(e, S.Null) for e in es if not isinstance(e, S.OptionalKey))
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed([None, None], (None, None))
    decoding.succeed(["a", 1], ("a", 1))
    decoding.fail([1, None], "Expected string | null\n  at [0]")


# ------------------------------------------------------- annotateKey: Tuple


def test_annotate_key_the_message_missing_key_annotation_tuple():
    """annotateKey / the messageMissingKey annotation should be used as a error message / Tuple"""
    schema = S.Tuple(S.String.annotate_key(message_missing_key="this element is required"))
    SchemaAsserts(schema).decoding().fail([], "this element is required\n  at [0]")


# --------------------------------------------- unions of tuples, UniqueArray


def test_union_should_exclude_members_based_on_failed_sentinels_string_or_tuple():
    """Union / should exclude members based on failed sentinels / string | tuple"""
    schema = S.Union(S.String, S.Tuple(S.Literal("a"), S.String))
    SchemaAsserts(schema).decoding().fail([], 'Expected string | readonly [ "a", ... ]')


def test_union_should_exclude_members_based_on_failed_sentinels_tagged_tuple_union():
    """Union / should exclude members based on failed sentinels / tagged tuple union"""
    schema = S.Union(S.Tuple(S.Literal("a"), S.String), S.Tuple(S.Literal("b"), S.Number))
    decoding = SchemaAsserts(schema).decoding()
    decoding.fail(["a"], "Missing key\n  at [1]")
    decoding.fail(["b"], "Missing key\n  at [1]")
    decoding.fail(["c"], 'Expected readonly [ "a", ... ] | readonly [ "b", ... ]')


class _AB(TypedDict):
    a: str
    b: str


def test_checks_array_checks_unique_array():
    """Checks / Array checks / UniqueArray"""
    decoding = SchemaAsserts(S.UniqueArray(S.Struct(_AB))).decoding()
    decoding.succeed(
        [{"a": "a", "b": "b"}, {"a": "c", "b": "d"}], ({"a": "a", "b": "b"}, {"a": "c", "b": "d"})
    )
    decoding.fail(
        [{"a": "a", "b": "b"}, {"a": "a", "b": "b"}], "Expected an array with unique items"
    )


def test_union_map_members_evolve():
    """Union.mapMembers / evolve"""
    schema = S.Union(S.String, S.Number, S.Boolean).map_members(
        lambda ms: (S.Array(ms[0]), ms[1], S.Array(ms[2]))
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(["a"], ("a",))
    decoding.succeed(1)
    decoding.succeed([True], (True,))
    decoding.fail("a", "Expected array | number")


def test_union_map_members_array():
    """Union.mapMembers / Array"""
    schema = S.Union(S.String, S.Number).map_members(lambda ms: tuple(map(S.Array, ms)))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(["a"], ("a",))
    decoding.succeed([1], (1,))


def test_checks_refine():
    """Checks / refine"""

    def is_some(o: Option[str]) -> TypeIs[Some[str]]:
        return o is not None

    schema = (
        S.Option(S.String)
        .pipe(S.refine(is_some, expected="isSome"))
        .check(S.make_filter(lambda some: len(some.value) > 0, expected="length > 0"))
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(Some("a"))
    decoding.fail(Some(""), "Expected length > 0")
    decoding.fail(None, "Expected isSome")


# --------------------------------------------------------------- ArrayEnsure


def test_array_ensure():
    """ArrayEnsure"""
    asserts = SchemaAsserts(S.ArrayEnsure(S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed("1", (1,))
    decoding.succeed(["1", "2"], (1, 2))
    decoding.succeed([], ())
    decoding.fail(None, "Expected string | array")
    decoding.fail("a", "Expected a finite number")
    decoding.fail(["a"], "Expected a finite number\n  at [0]")

    encoding = asserts.encoding()
    encoding.succeed((), ())
    encoding.succeed((1,), "1")
    encoding.succeed((1, 2), ("1", "2"))


def test_array_ensure_roundtrips_array_valued_elements():
    """ArrayEnsure roundtrips array-valued elements"""
    schema = S.ArrayEnsure(S.Tuple(S.Number, S.Number))
    encoded = S.encode_sync(schema)(((1, 2),))
    assert encoded == (1, 2)
    assert S.decode_sync(schema)(encoded) == ((1, 2),)


def test_array_ensure_preserves_outer_array_encoding():
    """ArrayEnsure preserves outer-array encoding"""
    schema = S.ArrayEnsure(S.from_json_string(S.Unknown))
    assert S.encode_sync(schema)((1, 2)) == ("1", "2")


# ------------------------------------------------------------------- mutable


def test_mutable_supports_encodings_on_array_elements():
    """mutable / supports encodings on array elements"""
    asserts = SchemaAsserts(S.List(S.FiniteFromString))
    asserts.decoding().succeed(["1"], [1])
    asserts.encoding().succeed([1], ["1"])


class _Values(TypedDict):
    value: list[str]


def test_mutable_supports_with_decoding_default_type_after_mutable():
    """mutable / supports withDecodingDefaultType after mutable"""
    value = S.List(S.String).pipe(S.with_decoding_default_type_key(fx.succeed(["default"])))
    asserts = SchemaAsserts(S.Struct(_Values, value=value))
    asserts.decoding().succeed({}, {"value": ["default"]})
    asserts.decoding().succeed({"value": ["a"]})
    asserts.encoding().succeed({"value": ["a"]})


# ---------------------------------------------------------------------- flip


def _head_longer_than_one(pair: tuple[str]) -> bool:
    return len(pair[0]) > 1


def test_flip_tuple_and_flip_and_check_and_flip_should_apply_the_check_to_the_encoded_side():
    """flip / Tuple & flip & check & flip should apply the check to the encoded side"""
    check = S.make_filter(_head_longer_than_one, expected="head length > 1")
    schema = S.flip(S.flip(S.Tuple(S.String)).check(check))
    node = schema.__codec__().ast
    assert isinstance(node, S.ast.Arrays)
    assert node.checks is None
    assert node.encoding_checks is not None
    assert len(node.encoding_checks) == 1
    asserts = SchemaAsserts(schema)
    asserts.decoding().fail(["a"], "Expected head length > 1")
    asserts.decoding().succeed(["aa"], ("aa",))
    asserts.encoding().fail(("a",), "Expected head length > 1")
    asserts.encoding().succeed(("aa",))


# ------------------------------------------------- arbitraries and JSON codecs


def _draws_valid_values(schema: S.Bottom[object]) -> None:
    pytest.importorskip("hypothesis")
    from hypothesis import given, settings

    is_valid = S.is_(schema)

    @settings(max_examples=50, deadline=None)
    @given(S.to_strategy(schema))
    def check(value: object) -> None:
        assert is_valid(value)

    check()


def test_duration():
    """Duration"""
    _draws_valid_values(S.Duration)


def test_byte_size():
    """ByteSize"""
    _draws_valid_values(S.ByteSize)
    json = SchemaAsserts(S.to_codec_json(S.ByteSize))
    json.decoding().succeed("9007199254740993", byte_size.bytes(9_007_199_254_740_993))
    json.encoding().succeed(byte_size.bytes(9_007_199_254_740_993), "9007199254740993")


def test_char():
    """Char"""
    asserts = SchemaAsserts(S.Char)
    decoding = asserts.decoding()
    decoding.succeed("a")
    decoding.fail("ab", "Expected a value with a length of 1")
    encoding = asserts.encoding()
    encoding.succeed("a")
    encoding.fail("ab", "Expected a value with a length of 1")


def _after_a_sleep(os: Option[str], _options: ParseOptions) -> Effect[Option[str]]:
    return sleep("10 millis").as_(os)


def test_should_throw_on_async_decoding():
    """should throw on async decoding"""
    transformation: T.Transformation[Any, Any] = T.Transformation(
        G.transform_optional_effect(_after_a_sleep), G.passthrough()
    )
    schema: Any = S.String.pipe(S.decode(transformation))
    with pytest.raises(RuntimeError, match="Result adapter can only return schema issues"):
        S.decode_unknown_result(schema)("1")
