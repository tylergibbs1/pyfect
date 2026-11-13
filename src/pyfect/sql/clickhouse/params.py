"""Values as ClickHouse's HTTP interface reads them: query parameters
(``param_<name>`` URL entries, as ``@clickhouse/client``'s
``formatQueryParams`` writes them), settings, and the type a value is
bound as when no type is given.

A parameter is text the server parses as its placeholder's type
(``{p1: Int64}``):

- ``None`` is ``\\N`` (``NULL`` inside an array, tuple or map)
- ``bool`` is ``1`` / ``0`` (``TRUE`` / ``FALSE`` inside a container)
- ``int``, ``float`` (``nan``, ``+inf``, ``-inf``), ``Decimal`` as numbers
- ``str`` and ``UUID`` with tabs, newlines, quotes and backslashes escaped
  (quoted inside a container)
- an aware ``datetime`` as Unix seconds, with microseconds when it has
  them (inside a container, its UTC date ``'YYYY-MM-DD'``, which every date
  and time type accepts); a ``date`` as ``YYYY-MM-DD``
- a ``list`` or ``tuple`` as an array, ``TupleParam`` as a tuple, a
  ``Mapping`` as a map

Any other value, and a naive ``datetime``, is a ``TypeError``.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

from pyfect._js import js_number

type Setting = bool | int | float | str | Mapping[str, str]
"""A ClickHouse setting's value; a mapping is a map setting
(``{'system.numbers':'number != 3'}``)."""

type Settings = Mapping[str, Setting]
"""ClickHouse settings by name (``{"max_threads": 4}``)."""

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
_ESCAPES = str.maketrans({"\t": "\\t", "\n": "\\n", "\r": "\\r", "'": "\\'", "\\": "\\\\"})
_INT64 = 1 << 63
_UINT64 = 1 << 64


@dataclass(frozen=True, slots=True)
class TupleParam:
    """A ``Tuple(...)`` parameter: ``TupleParam((42, "foo", None))`` is
    ``(42,'foo',NULL)`` (``@clickhouse/client``'s ``TupleParam``)."""

    values: Sequence[object]


def _unix_seconds(value: datetime) -> str:
    if value.tzinfo is None:
        raise TypeError(f"A naive datetime cannot be a query parameter: [{value!r}].")
    # The server reads ``-2.5`` as minus 2.5 seconds, so a time before the
    # epoch is its magnitude, signed (``@clickhouse/client`` floors the
    # seconds and adds the fraction: a second early).
    micros = (value - _EPOCH) // _MICROSECOND
    seconds, fraction = divmod(abs(micros), 1_000_000)
    text = f"-{seconds}" if micros < 0 else f"{seconds:010d}"
    return text if fraction == 0 else f"{text}.{fraction:06d}"


def _quote(text: str) -> str:
    """``text`` as a ClickHouse string literal, the one place quotes are written."""
    return "'" + text.translate(_ESCAPES) + "'"


def _in_container(value: object) -> str:
    match value:
        case None:
            return "NULL"
        case bool():
            return "TRUE" if value else "FALSE"
        case str() | uuid.UUID():
            return _quote(str(value))
        case datetime():
            _unix_seconds(value)  # rejects a naive datetime
            return _quote(value.astimezone(UTC).date().isoformat())
        case date():
            return _quote(value.isoformat())
        case _:
            return format_query_param(value)


def format_query_param(value: object) -> str:  # noqa: PLR0911, PLR0912
    """``value`` as the text of a query parameter (see the module)."""
    match value:
        case None:
            return "\\N"
        case bool():
            return "1" if value else "0"
        case int():
            return str(value)
        case float():
            if math.isnan(value):
                return "nan"
            if math.isinf(value):
                return "+inf" if value > 0 else "-inf"
            return js_number(value)
        case Decimal():
            return str(value)
        case str() | uuid.UUID():
            return str(value).translate(_ESCAPES)
        case datetime():
            return _unix_seconds(value)
        case date():
            return value.isoformat()
        case list() | tuple():
            items = cast("Sequence[object]", value)
            return "[" + ",".join(_in_container(item) for item in items) + "]"
        case TupleParam():
            return "(" + ",".join(_in_container(item) for item in value.values) + ")"
        case Mapping():
            entries = cast("Mapping[object, object]", value)
            return (
                "{"
                + ",".join(f"{_in_container(k)}:{_in_container(v)}" for k, v in entries.items())
                + "}"
            )
        case _:
            raise TypeError(f"Unsupported value in query parameters: [{value!r}].")


def format_setting(value: Setting) -> str:
    """``value`` as the text of a setting (``@clickhouse/client``'s
    ``formatQuerySettings``). A map's keys and values are string literals, with quotes and
    backslashes escaped (``@clickhouse/client`` writes them as they are)."""
    match value:
        case bool():
            return "1" if value else "0"
        case int() | float():
            return js_number(value)
        case str():
            return value
        case _:
            return "{" + ",".join(f"{_quote(k)}:{_quote(v)}" for k, v in value.items()) + "}"


def type_of(value: object) -> str:  # noqa: PLR0911
    """The ClickHouse type a value is bound as when no type is given (Effect's
    ``typeFromUnknown``): ``Bool``, ``Int64`` (``UInt64`` or ``Int256`` past it),
    ``Float64``, ``DateTime`` (``DateTime64(6)`` with microseconds),
    ``Date``, ``Array(<type of the first item>)``, else ``String``."""
    match value:
        case bool():
            return "Bool"
        case int():
            return (
                "Int64"
                if -_INT64 <= value < _INT64
                else "UInt64"
                if 0 <= value < _UINT64
                else "Int256"
            )
        case float():
            return "Float64"
        case datetime():
            return "DateTime" if value.microsecond == 0 else "DateTime64(6)"
        case date():
            return "Date"
        case list() | tuple():
            items = cast("Sequence[object]", value)
            return f"Array({type_of(items[0] if items else None)})"
        case _:
            return "String"


__all__ = ["Setting", "Settings", "TupleParam", "format_query_param", "format_setting", "type_of"]
