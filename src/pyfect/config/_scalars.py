"""The string decoders behind the scalar constructors, with Effect's
messages (Effect's StringTree encodings of its schemas)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from datetime import datetime

from pyfect import _js_date as js_date
from pyfect import _json_text
from pyfect._js import js_number
from pyfect._url import Url, parse_url
from pyfect.byte_size import ByteSize
from pyfect.byte_size import from_string as byte_size_from_string
from pyfect.config._leaf import EXPECTED_STRING, Scalar, composite, expected
from pyfect.duration import Seconds, parse_duration_text
from pyfect.logger import LogLevel
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result
from pyfect.schema.issue import InvalidValue, Issue

type LiteralValue = str | int | float | bool | None

_STRING = EXPECTED_STRING
_FINITE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
_NOT_FINITE_STRING = InvalidValue({"message": "Expected a string representing a finite number"})
_NON_FINITE = {"Infinity": math.inf, "-Infinity": -math.inf, "NaN": math.nan}
_NON_FINITE_EXPECTED = " | ".join(_json_text.stringify(k) for k in _NON_FINITE)
_INTEGER = InvalidValue({"message": "Expected an integer"})


def _ok[A](value: A) -> Result[A, Issue]:
    return Ok(value)


string = Scalar[str](_STRING, _ok)


def _non_empty(text: str) -> Result[str, Issue]:
    return (
        Ok(text)
        if text
        else Err(InvalidValue({"message": "Expected a value with a length of at least 1"}))
    )


non_empty_string = Scalar(_STRING, _non_empty)


def _finite(text: str) -> Result[float, Issue]:
    if not _FINITE.fullmatch(text):
        return Err(_NOT_FINITE_STRING)
    value = float(text)
    return (
        Ok(value)
        if math.isfinite(value)
        else Err(InvalidValue({"message": "Expected a finite number"}))
    )


finite = Scalar(_STRING, _finite)


def _number(text: str) -> Result[float, Issue]:
    if text in _NON_FINITE:
        return Ok(_NON_FINITE[text])
    if _FINITE.fullmatch(text):
        return Ok(float(text))
    return Err(composite(_NOT_FINITE_STRING, expected(_NON_FINITE_EXPECTED)))


number = Scalar(expected(f"string | {_NON_FINITE_EXPECTED}"), _number)


_MAX_SAFE_INTEGER = 2**53 - 1


def _integer(text: str) -> Result[int, Issue]:
    if not _FINITE.fullmatch(text):
        return Err(_NOT_FINITE_STRING)
    number = float(text)
    # As Effect's ``Number`` then ``isSafeInteger``, read through a float.
    if not math.isfinite(number) or number != int(number) or abs(number) > _MAX_SAFE_INTEGER:
        return Err(_INTEGER)
    return Ok(int(number))


integer = Scalar(_STRING, _integer)


def _port(text: str) -> Result[int, Issue]:
    match _integer(text):
        case Ok(value) if not 1 <= value <= 65535:
            return Err(InvalidValue({"message": "Expected a value between 1 and 65535"}))
        case decoded:
            return decoded


port = Scalar(_STRING, _port)


def _choices[A](pairs: Sequence[tuple[str, A]]) -> Scalar[A]:
    """A decoder accepting exactly the given spellings, the first match
    winning; missing and invalid input both list them."""
    expected_choice = expected(" | ".join(_json_text.stringify(text) for text, _ in pairs))
    table: dict[str, A] = {}
    for text, value in pairs:
        table.setdefault(text, value)

    def decode(text: str) -> Result[A, Issue]:
        return Ok(table[text]) if text in table else Err(expected_choice)

    return Scalar(expected_choice, decode)


boolean = _choices(
    [(t, True) for t in ("true", "yes", "on", "1", "y")]
    + [(f, False) for f in ("false", "no", "off", "0", "n")]
)

log_level = _choices([(str(level), level) for level in LogLevel])


def literal[L: LiteralValue](values: Sequence[L]) -> Scalar[L]:
    return _choices([(_encode_literal(v), v) for v in values])


def _encode_literal(value: LiteralValue) -> str:
    """The literal as Effect writes it in a string: ``True`` is ``"true"``,
    ``None`` is ``"null"``, numbers as JavaScript prints them."""
    match value:
        case bool():
            return "true" if value else "false"
        case None:
            return "null"
        case str():
            return value
        case int() | float():
            return js_number(value)


def _duration(text: str) -> Result[Seconds, Issue]:
    parsed = parse_duration_text(text)
    return (
        Err(InvalidValue({"message": "Expected a valid Duration string"}))
        if parsed is None
        else Ok(parsed)
    )


duration = Scalar(_STRING, _duration)


def _byte_size(text: str) -> Result[ByteSize, Issue]:
    size = byte_size_from_string(text)
    return (
        Err(InvalidValue({"message": "Expected a valid ByteSize string"}))
        if size is None
        else Ok(size)
    )


byte_size = Scalar(_STRING, _byte_size)


def _date_time(text: str) -> Result[datetime, Issue]:
    parsed = js_date.to_datetime(js_date.parse(text))
    if parsed is None:
        return Err(InvalidValue({"message": "Expected a valid Date"}))
    return Ok(parsed)


date_time = Scalar(_STRING, _date_time)

_INVALID_URL = InvalidValue({"message": "Expected a valid URL string"})


def _url(text: str) -> Result[Url, Issue]:
    url = parse_url(text)
    return Err(_INVALID_URL) if url is None else Ok(url)


url = Scalar(_STRING, _url)


def _mapped[A, B](scalar: Scalar[A], f: Callable[[A], B]) -> Scalar[B]:
    decode = scalar.decode
    return Scalar(scalar.missing, lambda text: decode(text).map(f))


redacted = _mapped(string, Redacted)
