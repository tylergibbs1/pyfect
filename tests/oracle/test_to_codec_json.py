"""Ports of Effect's ``toCodec.test.ts``: the ``toCodecJson`` titles. Each
test's docstring is the Effect test title, prefixed by its ``describe``
blocks. ``TestSchema.Asserts`` is ``testing.SchemaAsserts``.

Python mappings: a ``Date`` is an aware ``datetime`` (``S.DateTimeUtc``),
``optionalKey`` a ``NotRequired`` key, ``ReadonlySet`` / ``ReadonlyMap``
are ``FrozenSet`` / ``Map``, a ``Uint8Array`` is ``bytes``.

Omitted:
- Symbols, ``undefined``, ``void``, bigint literals and ``ObjectKeyword``
  (no Python counterpart): "Unsupported schemas / Struct with Symbol
  property name", "ObjectKeyword", "Undefined", "Void", "Symbol",
  "UniqueSymbol", "Symbol with a multiline registry key", "local
  UniqueSymbol", "PropertyKey", "Literal / bigint", the "UndefinedOr(Date)"
  and "optional(Date)" titles, "Record(String, UndefinedOr(Number))",
  "Record(Symbol, Date)", "Struct with an explicitly encoded Symbol property
  name", "ReadonlyMap(Option(Symbol), Date)".
- "exposes the source schema": the derived codec is a plain ``Bottom``.
- Ported in ``test_schema_errors.py``: the ``Error`` / ``Defect`` titles.
- Not yet ported schemas: ``URLSearchParams``, ``RegExp``, ``HashMap``,
  ``brand``, ``MutableJson``, ``withDecodingDefaultKey`` and every title
  naming them, "StandardSchemaV1FailureResult".
- Context-level details with no Python counterpart (a key's context is its
  ``TypedDict`` entry): "Number / reuses the Finite AST in the canonical
  encoding", "Number / does not propagate constructor defaults to the
  canonical encoding".
- "Duration": ``timedelta`` cannot be infinite, so the ``Infinity`` /
  ``NegativeInfinity`` forms are left out (the finite forms are ported).
- "Redacted(Option(String)) disallowJsonEncode": ``S.Redacted`` has no
  ``disallow_json_encode`` option yet.
- toCodecGoJson (and its toJsonSchemaDocument titles): a separate
  derivation, not ported yet.
- toCodecIso / toCodecStringTree: separate derivations, not JSON.
"""

import enum
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Never, NotRequired, TypedDict
from urllib.parse import urlsplit

from pyfect import option as O
from pyfect import schema as S
from pyfect.http.url import Url
from pyfect.redacted import Redacted
from pyfect.schema import transformation as T
from pyfect.testing import SchemaAsserts

_DATE = datetime(2021, 1, 1, tzinfo=UTC)
_DATE_TEXT = "2021-01-01T00:00:00.000Z"


def _asserts(schema: S.Codec[Any, Any, Never, Never]) -> SchemaAsserts[Never, Never]:
    return SchemaAsserts(S.to_codec_json(schema))


def test_treats_json_as_canonical():
    """toCodecJson / treats Json as canonical"""
    assert S.to_codec_json(S.Json).ast is S.Json.ast


def test_is_idempotent():
    """toCodecJson / is idempotent"""
    once = S.to_codec_json(S.suspend(lambda: S.Number))
    assert S.to_codec_json(once).ast is once.ast


def test_reorders_union_by_encoded_side():
    """toCodecJson / should reorder the types in the Union based on the encoded side"""
    from_big_int = S.String.pipe(
        S.encode_to(S.BigInt, T.transform(decode=lambda n: f"{n}a", encode=lambda _: 0))
    )
    schema = S.Union(S.String, from_big_int)
    SchemaAsserts(S.to_codec_json(S.to_codec_json(schema))).decoding().succeed("1", "1a")


class _AB(TypedDict):
    a: str
    b: bool


def test_same_reference_struct():
    """schemas without encoding / should return the same reference if nothing changed / Struct"""
    schema = S.Struct(_AB)
    assert S.to_codec_json(schema).ast is schema.ast


def test_same_reference_record():
    """schemas without encoding / should return the same reference if nothing changed / Record"""
    schema = S.Record(S.String, S.Boolean)
    assert S.to_codec_json(schema).ast is schema.ast


def test_same_reference_tuple():
    """schemas without encoding / should return the same reference if nothing changed / Tuple"""
    schema = S.Tuple(S.String, S.Boolean)
    assert S.to_codec_json(schema).ast is schema.ast


def test_same_reference_array():
    """schemas without encoding / should return the same reference if nothing changed / Array"""
    schema = S.Array(S.String)
    assert S.to_codec_json(schema).ast is schema.ast


def test_same_reference_union():
    """schemas without encoding / should return the same reference if nothing changed / Union"""
    schema = S.Union(S.String, S.Boolean)
    assert S.to_codec_json(schema).ast is schema.ast


def test_never():
    """schemas without encoding / Never"""
    _asserts(S.Never).encoding().fail({}, "Expected never")


def test_any():
    """schemas without encoding / Any"""
    asserts = _asserts(S.Any)
    asserts.encoding().succeed(print)
    asserts.decoding().succeed(print)


def test_unknown():
    """schemas without encoding / Unknown"""
    asserts = _asserts(S.Unknown)
    for direction in (asserts.encoding(), asserts.decoding()):
        direction.succeed("a")
        direction.succeed(1)
        direction.succeed(True)
        direction.succeed(None)
        direction.succeed({"a": "a", "b": 1, "c": True})
        direction.succeed(["a", 1, True])
        direction.fail({"a": 1j}, "Expected JSON value")


def test_null():
    """schemas without encoding / Null"""
    _asserts(S.Null).encoding().succeed(None)


def test_string():
    """schemas without encoding / String"""
    asserts = _asserts(S.String)
    asserts.encoding().succeed("a")
    asserts.decoding().succeed("a", "a")


def test_number():
    """schemas without encoding / Number / Number"""
    asserts = _asserts(S.Number)
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.succeed(-1)
    encoding.succeed(1.2)
    encoding.succeed(math.inf, "Infinity")
    encoding.succeed(-math.inf, "-Infinity")
    encoding.succeed(math.nan, "NaN")
    decoding = asserts.decoding()
    decoding.succeed(1)
    decoding.succeed(-1)
    decoding.succeed(1.2)
    decoding.succeed("Infinity", math.inf)
    decoding.succeed("-Infinity", -math.inf)
    decoding.fail(math.inf, "Expected a finite number")
    decoding.fail(-math.inf, "Expected a finite number")
    decoding.fail(math.nan, "Expected a finite number")
    decoding.fail(None, 'Expected number | "Infinity" | "-Infinity" | "NaN"')
    decoding.fail("a", 'Expected "Infinity" | "-Infinity" | "NaN"')
    result = S.decode_unknown_sync(S.to_codec_json(S.Number))("NaN")
    assert math.isnan(result)


def test_runs_source_checks_once_per_direction():
    """schemas without encoding / Number / checks / runs source checks once per direction"""
    executions = 0

    def count(_: float) -> None:
        nonlocal executions
        executions += 1

    codec = S.to_codec_json(S.Number.check(S.make_filter(count)))
    S.decode_unknown_sync(codec)(1)
    assert executions == 1
    executions = 0
    S.encode_unknown_sync(codec)(1)
    assert executions == 1


def test_finite():
    """schemas without encoding / Number / checks / Finite"""
    asserts = _asserts(S.Finite)
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.succeed(-1)
    encoding.succeed(1.2)
    encoding.fail(math.inf, "Expected a finite number")
    encoding.fail(-math.inf, "Expected a finite number")
    encoding.fail(math.nan, "Expected a finite number")
    decoding = asserts.decoding()
    decoding.succeed(1)
    decoding.succeed(1.2)
    decoding.fail("Infinity", "Expected number")
    decoding.fail("NaN", "Expected number")
    decoding.fail(math.inf, "Expected a finite number")
    decoding.fail(None, "Expected number")
    decoding.fail("a", "Expected number")


def test_int():
    """schemas without encoding / Number / checks / Int"""
    asserts = _asserts(S.Int)
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.succeed(-1)
    encoding.fail(1.2, "Expected an integer")
    decoding = asserts.decoding()
    decoding.succeed(1)
    decoding.succeed(-1)
    decoding.fail(1.2, "Expected an integer")
    decoding.fail("Infinity", "Expected number")
    decoding.fail(None, "Expected number")


def test_is_greater_than_or_equal_to():
    """schemas without encoding / Number / checks / isGreaterThanOrEqualTo"""
    asserts = _asserts(S.Number.check(S.is_greater_than_or_equal_to(1)))
    encoding = asserts.encoding()
    encoding.succeed(1)
    encoding.fail(-1, "Expected a value greater than or equal to 1")
    encoding.succeed(1.2)
    encoding.succeed(math.inf, "Infinity")
    encoding.fail(-math.inf, "Expected a value greater than or equal to 1")
    encoding.fail(math.nan, "Expected a value greater than or equal to 1")
    decoding = asserts.decoding()
    decoding.succeed(1)
    decoding.succeed(1.2)
    decoding.succeed("Infinity", math.inf)
    decoding.fail("-Infinity", "Expected a value greater than or equal to 1")
    decoding.fail("NaN", "Expected a value greater than or equal to 1")
    decoding.fail(math.inf, "Expected a finite number")
    decoding.fail(None, 'Expected number | "Infinity" | "-Infinity" | "NaN"')
    decoding.fail("a", 'Expected "Infinity" | "-Infinity" | "NaN"')


def test_boolean():
    """schemas without encoding / Boolean"""
    asserts = _asserts(S.Boolean)
    asserts.encoding().succeed(True)
    asserts.decoding().succeed(True, True)


def test_big_int():
    """schemas without encoding / BigInt"""
    asserts = _asserts(S.BigInt)
    asserts.encoding().succeed(1, "1")
    asserts.decoding().succeed("1", 1)


def test_literal_string():
    """schemas without encoding / Literal / string"""
    asserts = _asserts(S.Literal("a"))
    asserts.encoding().succeed("a")
    asserts.decoding().succeed("a")


def test_literal_number():
    """schemas without encoding / Literal / number"""
    asserts = _asserts(S.Literal(1))
    asserts.encoding().succeed(1)
    asserts.decoding().succeed(1)


def test_literal_boolean():
    """schemas without encoding / Literal / boolean"""
    asserts = _asserts(S.Literal(True))
    asserts.encoding().succeed(True)
    asserts.decoding().succeed(True)


def test_literals():
    """schemas without encoding / Literals"""
    # Python: no bigint literal (Effect's 2n is written "2").
    _asserts(S.Literals("a", 1, True)).decoding().fail("-", 'Expected "a" | 1 | true')


class _Fruits(enum.Enum):
    Apple = 0
    Banana = 1


def test_enum():
    """schemas without encoding / Enum"""
    asserts = _asserts(S.Enum(_Fruits))
    encoding = asserts.encoding()
    encoding.succeed(_Fruits.Apple, 0)
    encoding.succeed(_Fruits.Banana, 1)
    decoding = asserts.decoding()
    decoding.succeed(0, _Fruits.Apple)
    decoding.succeed(1, _Fruits.Banana)


class _DateField(TypedDict):
    a: datetime


class _NullableDate(TypedDict):
    a: datetime | None


class _OptionalDate(TypedDict):
    a: NotRequired[datetime]


def test_struct_date():
    """schemas without encoding / Struct / Date"""
    _asserts(S.Struct(_DateField, a=S.DateTimeUtc)).encoding().succeed(
        {"a": _DATE}, {"a": _DATE_TEXT}
    )


def test_struct_null_or_date():
    """schemas without encoding / Struct / NullOr(Date)"""
    asserts = _asserts(S.Struct(_NullableDate, a=S.NullOr(S.DateTimeUtc)))
    encoding = asserts.encoding()
    encoding.succeed({"a": _DATE}, {"a": _DATE_TEXT})
    encoding.succeed({"a": None}, {"a": None})
    decoding = asserts.decoding()
    decoding.succeed({"a": _DATE_TEXT}, {"a": _DATE})
    decoding.succeed({"a": None}, {"a": None})


def test_struct_optional_key_date():
    """schemas without encoding / Struct / optionalKey(Date)"""
    asserts = _asserts(S.Struct(_OptionalDate, a=S.DateTimeUtc))
    encoding = asserts.encoding()
    encoding.succeed({"a": _DATE}, {"a": _DATE_TEXT})
    encoding.succeed({}, {})
    decoding = asserts.decoding()
    decoding.succeed({"a": _DATE_TEXT}, {"a": _DATE})
    decoding.succeed({}, {})


def test_tuple_date():
    """schemas without encoding / Tuple / Date"""
    asserts = _asserts(S.Tuple(S.DateTimeUtc))
    asserts.encoding().succeed((_DATE,), (_DATE_TEXT,))
    asserts.decoding().succeed((_DATE_TEXT,), (_DATE,))


def test_tuple_null_or_date():
    """schemas without encoding / Tuple / NullOr(Date)"""
    asserts = _asserts(S.Tuple(S.NullOr(S.DateTimeUtc)))
    encoding = asserts.encoding()
    encoding.succeed((_DATE,), (_DATE_TEXT,))
    encoding.succeed((None,), (None,))
    decoding = asserts.decoding()
    decoding.succeed((_DATE_TEXT,), (_DATE,))
    decoding.succeed((None,), (None,))


def test_tuple_optional_key_date():
    """schemas without encoding / Tuple / optionalKey(Date)"""
    asserts = _asserts(S.Tuple(S.optional_key(S.DateTimeUtc)))
    encoding = asserts.encoding()
    encoding.succeed((_DATE,), (_DATE_TEXT,))
    encoding.succeed((), ())
    decoding = asserts.decoding()
    decoding.succeed((_DATE_TEXT,), (_DATE,))
    decoding.succeed((), ())


def test_array_date():
    """schemas without encoding / Array(Date)"""
    later = datetime(2021, 1, 2, tzinfo=UTC)
    _asserts(S.Array(S.DateTimeUtc)).encoding().succeed(
        (_DATE, later), (_DATE_TEXT, "2021-01-02T00:00:00.000Z")
    )


def test_null_or_string():
    """schemas without encoding / Union / NullOr(String)"""
    asserts = _asserts(S.NullOr(S.String))
    asserts.encoding().succeed("a")
    asserts.encoding().succeed(None)
    asserts.decoding().succeed(None)
    asserts.decoding().succeed("a")


def test_null_or_number():
    """schemas without encoding / Union / NullOr(Number)"""
    asserts = _asserts(S.NullOr(S.Number))
    asserts.encoding().succeed(1)
    asserts.encoding().succeed(None)
    asserts.decoding().succeed(None)
    asserts.decoding().succeed(1)


def test_array_null_or_number():
    """schemas without encoding / Union / Array(NullOr(Number))"""
    asserts = _asserts(S.Array(S.NullOr(S.Number)))
    asserts.encoding().succeed((1, None))
    asserts.decoding().succeed((1, None))


def test_union_date_finite():
    """schemas without encoding / Union / Union(Schema.Date, Finite)"""
    encoding = _asserts(S.Union(S.DateTimeUtc, S.Finite)).encoding()
    encoding.succeed(_DATE, _DATE_TEXT)
    encoding.succeed(0)


class _Category(TypedDict):
    a: float
    categories: tuple["_Category", ...]


def _category() -> S.Bottom[_Category, object, Never, Never]:
    return _CATEGORY


_CATEGORY: S.Bottom[_Category, object, Never, Never] = S.Struct(
    _Category,
    a=S.Finite.check(S.is_greater_than(0)),
    categories=S.Array(S.suspend(_category)),
)


def test_suspend():
    """schemas without encoding / Suspend"""
    asserts = _asserts(_CATEGORY)
    nested = {"a": 1, "categories": ({"a": 2, "categories": ()},)}
    for direction in (asserts.encoding(), asserts.decoding()):
        direction.succeed({"a": 1, "categories": ()})
        direction.succeed(nested)


class _A(S.Class):
    a: float = S.field(S.Finite)


def test_class():
    """schemas without encoding / Class"""
    asserts = _asserts(S.to_type(_A))
    asserts.encoding().succeed(_A(a=0), {"a": 0})
    asserts.decoding().succeed({"a": 0}, _A(a=0))


def test_url():
    """schemas without encoding / URL"""
    asserts = _asserts(S.URL)
    url = Url._make(urlsplit("https://example.com"))
    asserts.encoding().succeed(url, "https://example.com")
    asserts.decoding().succeed("https://example.com", url)
    asserts.decoding().fail("not a url", "Expected a valid URL string")


def test_uint8_array():
    """schemas without encoding / Uint8Array"""
    asserts = _asserts(S.Bytes)
    asserts.encoding().succeed(b"\x01\x02\x03", "AQID")
    asserts.decoding().succeed("AQID", b"\x01\x02\x03")
    asserts.decoding().fail("not a base64 string", "Expected a valid Base64 string")


def test_duration():
    """schemas without encoding / Duration"""
    # Python: a timedelta is finite and counts microseconds.
    asserts = _asserts(S.Duration)
    encoding = asserts.encoding()
    encoding.succeed(timedelta(microseconds=1), {"_tag": "Nanos", "value": "1000"})
    encoding.succeed(timedelta(microseconds=-1), {"_tag": "Nanos", "value": "-1000"})
    encoding.succeed(timedelta(milliseconds=1), {"_tag": "Millis", "value": 1})
    encoding.succeed(timedelta(milliseconds=-1), {"_tag": "Millis", "value": -1})
    encoding.succeed(timedelta(0), {"_tag": "Millis", "value": 0})
    decoding = asserts.decoding()
    decoding.succeed({"_tag": "Millis", "value": 1}, timedelta(milliseconds=1))
    decoding.succeed({"_tag": "Millis", "value": -1}, timedelta(milliseconds=-1))
    decoding.succeed({"_tag": "Nanos", "value": "1000"}, timedelta(microseconds=1))
    decoding.succeed({"_tag": "Nanos", "value": "-1000"}, timedelta(microseconds=-1))


def test_date_time_utc():
    """schemas without encoding / DateTimeUtc"""
    asserts = _asserts(S.DateTimeUtc)
    asserts.encoding().succeed(_DATE, _DATE_TEXT)
    asserts.decoding().succeed(_DATE_TEXT, _DATE)


def test_option_date():
    """schemas without encoding / Option(Date)"""
    encoding = _asserts(S.Option(S.DateTimeUtc)).encoding()
    encoding.succeed(O.Some(_DATE), {"_tag": "Some", "value": _DATE_TEXT})
    encoding.succeed(None, {"_tag": "None"})


def test_redacted_option_string():
    """schemas without encoding / Redacted / Redacted(Option(String))"""
    asserts = _asserts(S.Redacted(S.Option(S.String)))
    encoding = asserts.encoding()
    encoding.succeed(Redacted(None), {"_tag": "None"})
    encoding.succeed(Redacted(O.Some("a")), {"_tag": "Some", "value": "a"})
    decoding = asserts.decoding()
    decoding.succeed({"_tag": "None"}, Redacted(None))
    decoding.succeed({"_tag": "Some", "value": "a"}, Redacted(O.Some("a")))


def test_redacted_with_a_label():
    """schemas without encoding / Redacted / encoding a Redacted with a label"""
    _asserts(S.Redacted(S.String, label="password")).encoding().fail(
        Redacted("a", label="API key"), 'Expected "password"\n  at ["label"]'
    )


def test_redacted_with_a_different_label():
    """schemas without encoding / Redacted / encoding a Redacted with a different label"""
    _asserts(S.Redacted(S.String)).encoding().succeed(Redacted("a", label="API key"), "a")


_SOME_DATE = {"_tag": "Some", "value": _DATE_TEXT}


def test_readonly_set():
    """schemas without encoding / ReadonlySet"""
    asserts = _asserts(S.FrozenSet(S.Option(S.DateTimeUtc)))
    asserts.encoding().succeed(frozenset([O.Some(_DATE)]), (_SOME_DATE,))
    asserts.decoding().succeed((_SOME_DATE,), frozenset([O.Some(_DATE)]))


def test_readonly_map():
    """schemas without encoding / ReadonlyMap"""
    asserts = _asserts(S.Map(S.Option(S.DateTimeUtc), S.Finite))
    asserts.encoding().succeed({O.Some(_DATE): 0}, ((_SOME_DATE, 0),))
    asserts.decoding().succeed(((_SOME_DATE, 0),), {O.Some(_DATE): 0})


_FINITE_FROM_DATE = S.DateTimeUtc.pipe(
    S.decode_to(
        S.Finite,
        T.transform(
            decode=lambda date: date.timestamp() * 1000,
            encode=lambda n: datetime.fromtimestamp(n / 1000, UTC),
        ),
    )
)
_EPOCH_TEXT = "1970-01-01T00:00:00.000Z"


def test_finite_from_date():
    """schemas with encoding / FiniteFromDate"""
    asserts = _asserts(_FINITE_FROM_DATE)
    asserts.encoding().succeed(0, _EPOCH_TEXT)
    asserts.decoding().succeed(_EPOCH_TEXT, 0)


class _DatePair(TypedDict):
    a: float


def test_struct_with_encoding():
    """schemas with encoding / Struct"""
    asserts = _asserts(S.Struct(_DatePair, a=_FINITE_FROM_DATE))
    asserts.encoding().succeed({"a": 0}, {"a": _EPOCH_TEXT})
    asserts.decoding().succeed({"a": _EPOCH_TEXT}, {"a": 0})


def test_tuple_of_dates():
    """schemas with encoding / Tuple(Schema.Date, Schema.Date)"""
    asserts = _asserts(S.Tuple(S.DateTimeUtc, S.DateTimeUtc))
    asserts.encoding().succeed((_DATE, _DATE), (_DATE_TEXT, _DATE_TEXT))
    asserts.decoding().succeed((_DATE_TEXT, _DATE_TEXT), (_DATE, _DATE))


class _B(S.Class):
    a: float = S.field(_FINITE_FROM_DATE)


def test_class_with_encoding():
    """schemas with encoding / Class"""
    asserts = _asserts(_B)
    asserts.encoding().succeed(_B(a=0), {"a": _EPOCH_TEXT})
    asserts.decoding().succeed({"a": _EPOCH_TEXT}, _B(a=0))


class _MixedFruits(enum.Enum):
    Apple = 0
    Banana = "banana"


def test_enum_with_encoding():
    """schemas with encoding / Enum"""
    asserts = _asserts(S.Enum(_MixedFruits))
    asserts.encoding().succeed(_MixedFruits.Apple, 0)
    asserts.encoding().succeed(_MixedFruits.Banana, "banana")
    asserts.decoding().succeed(0, _MixedFruits.Apple)


def test_option_option_finite_from_date():
    """schemas with encoding / Option(Option(FiniteFromDate))"""
    _asserts(S.Option(S.Option(_FINITE_FROM_DATE))).encoding().succeed(
        O.Some(O.Some(0)),
        {"_tag": "Some", "value": {"_tag": "Some", "value": _EPOCH_TEXT}},
    )
