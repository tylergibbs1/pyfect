"""Properties over ``S.to_strategy``: every value it draws is one the schema
accepts, and encoding then decoding it gives an equivalent value, through
the schema's own codec and its canonical JSON codec."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Never, NotRequired, TypedDict, cast

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings
from hypothesis import strategies as st

import pyfect as fx
from pyfect import big_decimal as bd
from pyfect import optic
from pyfect import schema as S


class _User(TypedDict):
    id: int
    name: str
    nick: NotRequired[str]
    tags: tuple[str, ...]


class _Tree(TypedDict):
    value: int
    children: tuple[_Tree, ...]


_TREE: S.StructSchema[_Tree, Never, Never] = S.Struct(
    _Tree, children=S.Array(S.suspend(lambda: _TREE)).check(S.is_max_length(3))
)


def _catalog() -> dict[str, S.Bottom[Any, Any]]:
    """Every exported schema constant, but those with no value to draw or
    to encode exactly: ``Never``; ``ByteSizeFromNumber``, whose large sizes
    have no safe-integer encoding; ``DurationFromMillis``, whose milliseconds
    are a float that drops nanoseconds past about 104 days, as Effect's do."""
    excluded = {"Never", "ByteSizeFromNumber", "DurationFromMillis"}
    found: dict[str, S.Bottom[Any, Any]] = {
        name: cast("S.Bottom[Any, Any]", value)
        for name, value in vars(S).items()
        if name[0].isupper() and isinstance(value, S.Bottom) and name not in excluded
    }
    return found | {
        "Struct": S.Struct(_User),
        "recursive Struct": _TREE,
        "Union": S.Union(S.NumberFromString, S.Boolean),
        "Option": S.Option(S.DateTimeUtcFromString),
        "Map": S.Map(S.String, S.FiniteFromString),
        "Tuple": S.TupleWithRest(S.Tuple(S.BooleanFromBit), S.BigIntFromString),
        "checked": S.String.check(S.is_min_length(2), S.is_pattern(r"^[a-z]")),
    }


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_LATER = datetime(2030, 1, 1, tzinfo=UTC)

_CHECKED: dict[str, S.Bottom[Any, Any]] = {
    "is_ecma_pattern": S.String.check(S.is_ecma_pattern("^[a-c]+$")),
    "is_ascii": S.String.check(S.is_ascii()),
    "is_base64": S.String.check(S.is_base64()),
    "is_base64_url": S.String.check(S.is_base64_url()),
    "is_between": S.Number.check(S.is_between(minimum=-1.5, maximum=10)),
    "is_between_big_int": S.BigInt.check(
        S.is_between_big_int(minimum=-3, maximum=3, exclusive_maximum=True)
    ),
    "is_between_big_decimal": S.BigDecimal.check(
        S.is_between_big_decimal(
            minimum=bd.make(-15, 1), maximum=bd.make(1_236, 3), exclusive_minimum=True
        )
    ),
    "is_greater_than_big_decimal": S.BigDecimal.check(S.is_greater_than_big_decimal(bd.make(5, 1))),
    "is_greater_than_or_equal_to_big_decimal": S.BigDecimal.check(
        S.is_greater_than_or_equal_to_big_decimal(bd.make(-5, 0))
    ),
    "is_less_than_big_decimal": S.BigDecimal.check(S.is_less_than_big_decimal(bd.make(1, 30))),
    "is_less_than_or_equal_to_big_decimal": S.BigDecimal.check(
        S.is_less_than_or_equal_to_big_decimal(bd.make(-7, -3))
    ),
    "is_between_code_points": S.String.check(S.is_between_code_points(1, 3)),
    "is_between_date": S.DateTimeUtc.check(
        S.is_between_date(minimum=_EPOCH, maximum=_LATER, exclusive_minimum=True)
    ),
    "is_between_length": S.Array(S.Int).check(S.is_between_length(1, 3)),
    "is_between_properties": S.Record(S.String, S.Int).check(S.is_between_properties(1, 3)),
    "is_between_size": S.FrozenSet(S.Int).check(S.is_between_size(1, 3)),
    "is_capitalized": S.String.check(S.is_capitalized()),
    "is_ending_with": S.String.check(S.is_ending_with("a.b")),
    "is_finite": S.Number.check(S.is_finite()),
    "is_greater_than": S.Number.check(S.is_greater_than(0.5)),
    "is_greater_than_big_int": S.BigInt.check(S.is_greater_than_big_int(2**70)),
    "is_greater_than_date": S.DateTimeUtc.check(S.is_greater_than_date(_LATER)),
    "is_greater_than_or_equal_to": S.Number.check(S.is_greater_than_or_equal_to(0)),
    "is_greater_than_or_equal_to_big_int": S.BigInt.check(S.is_greater_than_or_equal_to_big_int(0)),
    "is_greater_than_or_equal_to_date": S.DateTimeUtc.check(
        S.is_greater_than_or_equal_to_date(_EPOCH)
    ),
    "is_guid": S.String.check(S.is_guid()),
    "is_including": S.String.check(S.is_including("[")),
    "is_int": S.Number.check(S.is_int()),
    "is_int32": S.Number.check(S.is_int32()),
    "is_less_than": S.Number.check(S.is_less_than(-0.5)),
    "is_less_than_big_int": S.BigInt.check(S.is_less_than_big_int(0)),
    "is_less_than_date": S.DateTimeUtc.check(S.is_less_than_date(_EPOCH)),
    "is_less_than_or_equal_to": S.Number.check(S.is_less_than_or_equal_to(0)),
    "is_less_than_or_equal_to_big_int": S.BigInt.check(S.is_less_than_or_equal_to_big_int(0)),
    "is_less_than_or_equal_to_date": S.DateTimeUtc.check(S.is_less_than_or_equal_to_date(_EPOCH)),
    "is_lowercased": S.String.check(S.is_lowercased()),
    "is_max_code_points": S.String.check(S.is_max_code_points(2)),
    "is_max_length": S.String.check(S.is_max_length(2)),
    "is_max_properties": S.Record(S.String, S.Int).check(S.is_max_properties(2)),
    "is_max_size": S.Map(S.String, S.Int).check(S.is_max_size(2)),
    "is_min_code_points": S.String.check(S.is_min_code_points(2)),
    "is_min_length": S.Bytes.check(S.is_min_length(2)),
    "is_min_properties": S.Record(S.String, S.Int).check(S.is_min_properties(2)),
    "is_min_size": S.Map(S.String, S.Int).check(S.is_min_size(2)),
    "is_multiple_of": S.Int.check(S.is_multiple_of(3)),
    "is_non_empty": S.Array(S.String).check(S.is_non_empty()),
    "is_pattern": S.String.check(S.is_min_length(2), S.is_pattern(r"^[a-z]")),
    "is_property_names": S.Record(S.String, S.Int).check(S.is_property_names(S.NonEmptyString)),
    "is_starting_with": S.String.check(S.is_starting_with("a+b")),
    "is_string_big_int": S.String.check(S.is_string_big_int()),
    "is_string_finite": S.String.check(S.is_string_finite()),
    "is_trimmed": S.String.check(S.is_trimmed()),
    "is_uint32": S.Number.check(S.is_uint32()),
    "is_ulid": S.String.check(S.is_ulid()),
    "is_uncapitalized": S.String.check(S.is_uncapitalized()),
    "is_unique": S.Array(S.Int).check(S.is_unique()),
    "is_unique_key": S.Array(S.Tuple(S.String, S.Int)).check(S.is_unique_key()),
    "is_uppercased": S.String.check(S.is_uppercased()),
    "is_uuid": S.String.check(S.is_uuid()),
}
"""One schema per exported check, so ``to_strategy`` is tried within every
constraint a check carries."""

_CATALOG = _catalog() | _CHECKED


def test_every_exported_check_is_in_the_catalog():
    """A new check needs a case above: deriving within its constraint is
    otherwise never exercised."""
    checks = {
        name for name in vars(S) if name.startswith("is_") and name not in ("is_", "is_schema")
    }
    assert checks == set(_CHECKED)


def _as_js_numbers(value: object) -> object:
    """``value`` with every number a float: JSON text has JavaScript's
    numbers, so a float past ``2 ** 53`` is written as the digits
    ``JSON.stringify`` writes (``30077077691360010``) and read back as that
    int, the same double (PARITY §4)."""
    match value:
        case bool() | None | str():
            return value
        case int() | float():
            return float(value)
        case list() | tuple():
            return [_as_js_numbers(v) for v in cast("list[object]", value)]
        case dict():
            items = cast("dict[str, object]", value).items()
            return {k: _as_js_numbers(v) for k, v in items}
        case _:
            return value


_JSON_TEXT = {"UnknownFromJsonString"}


def _has_json_form(node: S.ast.AST) -> bool:
    """As in Effect, a declaration without a ``to_codec_json`` (the network
    addresses, ``HostPort``), or a union of one (``Host``), has no JSON
    form: encoding one is ``Expected JSON value``."""
    if node.encoding is not None:
        return True
    if isinstance(node, S.ast.Union):
        return all(map(_has_json_form, node.types))
    if not isinstance(node, S.ast.Declaration):
        return True
    annotations = node.annotations or {}
    representation = cast("dict[str, object]", annotations.get("representation") or {})
    return (
        "to_codec_json" in annotations
        or "to_codec" in annotations
        or representation.get("id") == "effect/schema/Json"
        or bool(node.type_parameters)
    )


@pytest.mark.parametrize("name", sorted(_CATALOG))
def test_decoding_an_encoded_value_gives_it_back(name: str):
    schema = _CATALOG[name]
    is_ = S.is_(schema)
    same = S.to_equivalence(schema)

    def equivalent(a: object, b: object) -> bool:
        if name in _JSON_TEXT:
            return same(_as_js_numbers(a), _as_js_numbers(b))
        return same(a, b)

    codecs = (
        (schema, S.to_codec_json(schema)) if _has_json_form(schema.__codec__().ast) else (schema,)
    )
    round_trips = [(S.encode_sync(c), S.decode_unknown_sync(c)) for c in codecs]

    @settings(max_examples=40, deadline=None)
    @given(S.to_strategy(schema))
    def round_trip(value: object) -> None:
        assert is_(value)
        # As in Effect, a zoned string has a whole-minute offset, and reading it keeps that.
        if isinstance(value, datetime) and (value.utcoffset() or timedelta()).seconds % 60:
            return
        for encode, decode in round_trips:
            assert equivalent(decode(encode(value)), value)

    round_trip()


@given(S.to_strategy(S.Struct(_User)), st.text())
@fx.testing.effect
def test_given_composes_with_effect_tests(user: _User, name: str):
    renamed = optic.Id[_User]().key("name").replace(name, user)
    decoded = yield from S.decode_effect(S.Struct(_User))(renamed)
    assert decoded == {**user, "name": name}


@given(S.to_strategy(S.Struct(_User)), st.text())
def test_a_lens_puts_back_what_it_gets(user: _User, name: str):
    lens = optic.Id[_User]().key("name")
    assert lens.replace(lens.get(user), user) == user
    assert lens.get(lens.replace(name, user)) == name
