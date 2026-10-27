"""Schemas of single values: durations, date-times and zones, byte sizes
and JSON (Effect's declarations of them), over the Python types pyfect
uses for them.

``Duration`` is a ``timedelta``. ``DateTimeUtc`` is an aware ``datetime``
whose zone is ``timezone.utc``; ``DateTimeZoned`` any aware ``datetime``
(pyfect's UTC and zero-offset date-times are the same value). A
``TimeZoneNamed`` is a ``ZoneInfo``, a ``TimeZoneOffset`` a
``datetime.timezone``. Each is taken unchanged, on both sides.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Never, TypeIs
from zoneinfo import ZoneInfo

from pyfect.byte_size import ByteSize as _ByteSize
from pyfect.byte_size import is_byte_size
from pyfect.schema import ast
from pyfect.schema._declare import declare, instance_of
from pyfect.schema._primitives import String
from pyfect.schema._record import Record, RecordSchema
from pyfect.schema._schema import Bottom

Duration: Bottom[timedelta] = instance_of(timedelta, expected="Duration")
"""A ``timedelta`` (Effect's ``Duration``)."""


def _is_utc(value: object) -> TypeIs[datetime]:
    return isinstance(value, datetime) and value.tzinfo is UTC


def _is_zoned(value: object) -> TypeIs[datetime]:
    return isinstance(value, datetime) and value.utcoffset() is not None


DateTimeUtc: Bottom[datetime] = declare(_is_utc, expected="DateTime.Utc")
"""An aware ``datetime`` in ``timezone.utc`` (Effect's ``DateTimeUtc``)."""
DateTimeZoned: Bottom[datetime] = declare(_is_zoned, expected="DateTime.Zoned")
"""An aware ``datetime`` (Effect's ``DateTimeZoned``); a naive one is
rejected."""
TimeZoneNamed: Bottom[ZoneInfo] = instance_of(ZoneInfo, expected="DateTime.TimeZone.Named")
"""A ``ZoneInfo`` (Effect's ``TimeZoneNamed``)."""
TimeZoneOffset: Bottom[timezone] = instance_of(timezone, expected="DateTime.TimeZone.Offset")
"""A fixed-offset ``datetime.timezone`` (Effect's ``TimeZoneOffset``)."""


def _is_zone(value: object) -> TypeIs[tzinfo]:
    return isinstance(value, ZoneInfo | timezone)


TimeZone: Bottom[tzinfo] = declare(_is_zone, expected="DateTime.TimeZone")
"""A ``ZoneInfo`` or a ``datetime.timezone`` (Effect's ``TimeZone``)."""
ByteSize: Bottom[_ByteSize] = declare(is_byte_size, expected="ByteSize")
"""A ``byte_size.ByteSize``: a non-negative ``int`` (Effect's ``ByteSize``)."""

type JsonValue = bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None
"""A JSON value (Effect's ``Json`` type): a list or tuple for an array, a
string-keyed mapping for an object. ``pyfect.encoding.Json`` (what
``json.loads`` returns) is one."""

Json: Bottom[JsonValue] = Bottom(ast.json)
"""Any JSON value (``ast.is_json``), unchanged: ``Expected JSON value``
otherwise (Effect's ``Json``)."""
JsonObject: RecordSchema[str, JsonValue, str, JsonValue, Never, Never] = Record(String, Json)
"""A string-keyed mapping of JSON values (Effect's ``JsonObject``)."""
