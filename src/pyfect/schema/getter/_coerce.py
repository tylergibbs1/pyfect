"""Getters converting between kinds (Effect's ``SchemaGetter.String``,
``Number``, ``Boolean``, ``BigInt``, ``parseJson``, ``stringifyJson``,
``dateTimeUtcFromInput``), with JavaScript's conversion rules."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, overload

from pyfect import _js_date as js_date
from pyfect import _json_text as _json
from pyfect._digits import parse_signed_digits
from pyfect._js import js_string
from pyfect._js import trim as js_trim
from pyfect.date_time._epoch import from_epoch_millis
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter._getter import Getter, Transform, TransformEffect
from pyfect.schema.getter._json_options import JsonReplacer, JsonReviver, replace_json, revive
from pyfect.schema.issue import InvalidValue, Issue, reported

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_RADIX = re.compile(r"0([xXoObB])([0-9a-fA-F]+)")
_BASES = {"x": 16, "o": 8, "b": 2}


def _radix(text: str) -> int | None:
    match = _RADIX.fullmatch(text)
    if match is None:
        return None
    try:
        return int(match[2], _BASES[match[1].lower()])
    except ValueError:
        return None


_INFINITIES = {"Infinity": math.inf, "+Infinity": math.inf, "-Infinity": -math.inf}


def to_number(value: object) -> float:
    """JavaScript's ``Number(value)``: ``NaN`` for what is not a number."""
    if isinstance(value, bool | int | float):
        return float(value)
    if value is None:
        return 0.0
    return _text_number(js_trim(value)) if isinstance(value, str) else math.nan


def _text_number(text: str) -> float:
    if text == "":
        return 0.0
    if text in _INFINITIES:
        return _INFINITIES[text]
    if _DECIMAL.fullmatch(text):
        return float(text)
    radix = _radix(text)
    return math.nan if radix is None else float(radix)


def to_string(value: object) -> str:
    """JavaScript's ``String(value)`` for the values schemas hold."""
    return js_string(value)


def to_boolean(value: object) -> bool:
    """JavaScript's ``Boolean(value)``: ``NaN`` is false too."""
    if isinstance(value, float) and math.isnan(value):
        return False
    return bool(value)


def to_big_int(value: object) -> int | None:
    """JavaScript's ``BigInt(value)``, or ``None`` where it throws."""
    if isinstance(value, bool | int):
        return int(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str):
        return None
    text = js_trim(value)
    if text == "":
        return 0
    # Unlike JavaScript, a BigInt of more than MAX_DIGITS digits is invalid.
    signed = parse_signed_digits(text)
    return signed if signed is not None else _radix(text)


def string() -> Getter[str, object]:
    """``String(value)`` (Effect's ``SchemaGetter.String``)."""
    return Transform(to_string)


def number() -> Getter[float, object]:
    """``Number(value)`` (Effect's ``SchemaGetter.Number``)."""
    return Transform(to_number)


def boolean() -> Getter[bool, object]:
    """``Boolean(value)`` (Effect's ``SchemaGetter.Boolean``)."""
    return Transform(to_boolean)


def big_int() -> Getter[int, str | int | float | bool]:
    """``BigInt(value)``; what it rejects is an ``InvalidValue`` (Effect's
    ``SchemaGetter.BigInt``)."""

    def run(value: object, options: ParseOptions) -> Exit[int, Issue]:
        out = to_big_int(value)
        if out is None:
            expected = {"expected": "a value that can be converted to a bigint"}
            return fail_exit(InvalidValue(expected, reported(value, options)))
        return Success(out)

    return TransformEffect(run)


@overload
def parse_json() -> Getter[_json.Json, str]: ...
@overload
def parse_json(*, reviver: JsonReviver) -> Getter[object, str]: ...
def parse_json(*, reviver: JsonReviver | None = None) -> Getter[object, str]:
    """The JSON value of a string (``JSON.parse``), walked by ``reviver``
    when given; an ``InvalidValue`` when it is not JSON or ``reviver``
    raises (Effect's ``parseJson``)."""

    def run(text: str, options: ParseOptions) -> Exit[object, Issue]:
        try:
            value = _json.parse(text)
            return Success(value if reviver is None else revive(value, reviver))
        except Exception:
            # Effect's ``Effect.try`` turns whatever ``JSON.parse`` throws, a reviver's error
            # included, into this issue.
            expected = {"expected": "a valid JSON string"}
            return fail_exit(InvalidValue(expected, reported(text, options)))

    return TransformEffect(run)


def stringify_json(
    *, replacer: JsonReplacer | None = None, space: int | str | None = None
) -> Getter[str, object]:
    """The JSON text of a value (``JSON.stringify``, through ``replacer``
    and indented by ``space``); an ``InvalidValue`` when it has none or
    ``replacer`` raises (Effect's ``stringifyJson``; ``NaN`` and infinities
    have none, where JavaScript writes ``null``)."""

    def run(value: object, options: ParseOptions) -> Exit[str, Issue]:
        try:
            replaced = value if replacer is None else replace_json(value, replacer)
            return Success(_json.stringify(replaced, indent=space))
        except Exception:
            expected = {"expected": "a JSON-serializable value"}
            return fail_exit(InvalidValue(expected, reported(value, options)))

    return TransformEffect(run)


def to_utc(value: object) -> datetime | None:
    """A UTC ``datetime`` from a ``DateTime.Input``: a ``datetime`` (a naive
    one is UTC), epoch milliseconds, or an ISO 8601 / RFC 2822 string
    (without a zone, UTC); ``None`` when it is none of these."""
    match value:
        case bool():
            return None
        case datetime():
            return _as_utc(value)
        case int() | float():
            try:
                return from_epoch_millis(value)
            except (OverflowError, OSError, ValueError):
                return None
        case str():
            return _parse_date(value)
        case _:
            return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_date(text: str) -> datetime | None:
    parsed = js_date.parse_input(text)
    if parsed is not None:
        return parsed.astimezone(UTC)
    try:
        return _as_utc(parsedate_to_datetime(text))
    except (TypeError, ValueError, IndexError):
        return None


def date_time_utc_from_input() -> Getter[datetime, object]:
    """A UTC ``datetime`` from a ``DateTime.Input`` (see ``to_utc``); an
    ``InvalidValue`` otherwise (Effect's ``dateTimeUtcFromInput``)."""

    def run(value: object, options: ParseOptions) -> Exit[datetime, Issue]:
        out = to_utc(value)
        if out is None:
            message: dict[str, Any] = {"message": "Invalid DateTime input"}
            return fail_exit(InvalidValue(message, reported(value, options)))
        return Success(out)

    return TransformEffect(run)
