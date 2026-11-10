"""Schemas of single values: durations, date-times and zones, byte sizes
and JSON (Effect's declarations of them), over the Python types pyfect
uses for them.

``Duration`` is a ``pyfect.duration.Duration``. ``DateTimeUtc`` is an aware ``datetime``
whose zone is ``timezone.utc``; ``DateTimeZoned`` any aware ``datetime``
(pyfect's UTC and zero-offset date-times are the same value). A
``TimeZoneNamed`` is a ``ZoneInfo``, a ``TimeZoneOffset`` a
``datetime.timezone``. Each is taken unchanged, on both sides.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone, tzinfo
from typing import Never, TypeIs
from zoneinfo import ZoneInfo

from pyfect._json_value import JsonValue
from pyfect.byte_size import ByteSize as _ByteSize
from pyfect.byte_size import is_byte_size
from pyfect.duration import Duration as DurationValue
from pyfect.schema import _arbitrary_links as _arb
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._declare import declare, instance_of
from pyfect.schema._instances import (
    DATE_TIME_UTC_FORMATTER,
    DATE_TIME_ZONED_FORMATTER,
    ZONE_FORMATTER,
)
from pyfect.schema._primitives import String
from pyfect.schema._record import Record, RecordSchema
from pyfect.schema._schema import Bottom
from pyfect.schema._value_codecs import (
    byte_size_codec,
    byte_size_string_tree_codec,
    duration_codec,
    string_codec,
    time_zone_offset_codec,
)

Duration: Bottom[DurationValue] = instance_of(
    DurationValue,
    expected="Duration",
    representation={"id": "effect/schema/Duration", "payload": None},
    to_codec_json=duration_codec,
)
"""A ``Duration`` (Effect's ``Schema.Duration``)."""


def _is_utc(value: object) -> TypeIs[datetime]:
    return isinstance(value, datetime) and value.tzinfo is UTC


def _is_zoned(value: object) -> TypeIs[datetime]:
    return isinstance(value, datetime) and value.utcoffset() is not None


DateTimeUtc: Bottom[datetime] = declare(
    _is_utc,
    expected="DateTime.Utc",
    representation={"id": "effect/schema/DateTimeUtc", "payload": None},
    to_codec_arbitrary=_arb.date_time_utc,
    to_codec_json=string_codec(T.date_time_utc_from_string),
    to_formatter=DATE_TIME_UTC_FORMATTER,
)
"""An aware ``datetime`` in ``timezone.utc`` (Effect's ``DateTimeUtc``)."""
DateTimeZoned: Bottom[datetime] = declare(
    _is_zoned,
    expected="DateTime.Zoned",
    representation={"id": "effect/schema/DateTimeZoned", "payload": None},
    to_codec_arbitrary=_arb.date_time_zoned,
    to_codec_json=string_codec(T.date_time_zoned_from_string),
    to_formatter=DATE_TIME_ZONED_FORMATTER,
)
"""An aware ``datetime`` (Effect's ``DateTimeZoned``); a naive one is
rejected."""
TimeZoneNamed: Bottom[ZoneInfo] = instance_of(
    ZoneInfo,
    expected="DateTime.TimeZone.Named",
    representation={"id": "effect/schema/TimeZoneNamed", "payload": None},
    to_codec_arbitrary=_arb.time_zone_named,
    to_codec_json=string_codec(T.time_zone_named_from_string),
    to_formatter=ZONE_FORMATTER,
)
"""A ``ZoneInfo`` (Effect's ``TimeZoneNamed``)."""
TimeZoneOffset: Bottom[timezone] = instance_of(
    timezone,
    expected="DateTime.TimeZone.Offset",
    representation={"id": "effect/schema/TimeZoneOffset", "payload": None},
    to_codec_arbitrary=_arb.time_zone_offset,
    to_codec_json=time_zone_offset_codec,
    to_formatter=ZONE_FORMATTER,
)
"""A fixed-offset ``datetime.timezone`` (Effect's ``TimeZoneOffset``)."""


def _is_zone(value: object) -> TypeIs[tzinfo]:
    return isinstance(value, ZoneInfo | timezone)


TimeZone: Bottom[tzinfo] = declare(
    _is_zone,
    expected="DateTime.TimeZone",
    representation={"id": "effect/schema/TimeZone", "payload": None},
    to_codec_arbitrary=_arb.time_zone,
    to_codec_json=string_codec(T.time_zone_from_string),
    to_formatter=ZONE_FORMATTER,
)
"""A ``ZoneInfo`` or a ``datetime.timezone`` (Effect's ``TimeZone``)."""
ByteSize: Bottom[_ByteSize] = declare(
    is_byte_size,
    expected="ByteSize",
    representation={"id": "effect/schema/ByteSize", "payload": None},
    to_codec_json=byte_size_codec,
    to_codec_string_tree=byte_size_string_tree_codec,
)
"""A ``byte_size.ByteSize``: a non-negative ``int`` (Effect's ``ByteSize``)."""

Json: Bottom[JsonValue] = Bottom(ast.json)
"""Any JSON value (``ast.is_json``), unchanged: ``Expected JSON value``
otherwise (Effect's ``Json``)."""
JsonObject: RecordSchema[str, JsonValue, str, JsonValue, Never, Never] = Record(String, Json)
"""A string-keyed mapping of JSON values (Effect's ``JsonObject``)."""
