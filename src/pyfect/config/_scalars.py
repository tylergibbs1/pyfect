"""The string decoders behind the scalar constructors, with Effect's
messages (Effect's StringTree encodings of its schemas)."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import SplitResult, urlsplit

from pyfect._js import SPACE, js_number
from pyfect.byte_size import ByteSize
from pyfect.byte_size import from_string as byte_size_from_string
from pyfect.config._issue import Composite, InvalidType, InvalidValue, Issue
from pyfect.config._leaf import Scalar
from pyfect.duration import Seconds
from pyfect.logger import LogLevel
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result

type LiteralValue = str | int | float | bool | None

_STRING = InvalidType("string")
_FINITE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[Ee][+-]?[0-9]+)?")
_NOT_FINITE_STRING = InvalidValue("Expected a string representing a finite number")
_NON_FINITE = {"Infinity": math.inf, "-Infinity": -math.inf, "NaN": math.nan}
_NON_FINITE_EXPECTED = " | ".join(json.dumps(k) for k in _NON_FINITE)
_INTEGER = InvalidValue("Expected an integer")


def _ok[A](value: A) -> Result[A, Issue]:
    return Ok(value)


string = Scalar[str](_STRING, _ok)


def _non_empty(text: str) -> Result[str, Issue]:
    return Ok(text) if text else Err(InvalidValue("Expected a value with a length of at least 1"))


non_empty_string = Scalar(_STRING, _non_empty)


def _finite(text: str) -> Result[float, Issue]:
    if not _FINITE.fullmatch(text):
        return Err(_NOT_FINITE_STRING)
    value = float(text)
    return Ok(value) if math.isfinite(value) else Err(InvalidValue("Expected a finite number"))


finite = Scalar(_STRING, _finite)


def _number(text: str) -> Result[float, Issue]:
    if text in _NON_FINITE:
        return Ok(_NON_FINITE[text])
    if _FINITE.fullmatch(text):
        return Ok(float(text))
    return Err(Composite((_NOT_FINITE_STRING, InvalidType(_NON_FINITE_EXPECTED))))


number = Scalar(InvalidType(f"string | {_NON_FINITE_EXPECTED}"), _number)


def _integer(text: str) -> Result[int, Issue]:
    if not _FINITE.fullmatch(text):
        return Err(_NOT_FINITE_STRING)
    if not math.isfinite(float(text)):
        return Err(_INTEGER)
    exact = Decimal(text)
    return Ok(int(exact)) if exact == exact.to_integral_value() else Err(_INTEGER)


integer = Scalar(_STRING, _integer)


def _port(text: str) -> Result[int, Issue]:
    match _integer(text):
        case Ok(value) if not 1 <= value <= 65535:
            return Err(InvalidValue("Expected a value between 1 and 65535"))
        case decoded:
            return decoded


port = Scalar(_STRING, _port)


def _choices[A](pairs: Sequence[tuple[str, A]]) -> Scalar[A]:
    """A decoder accepting exactly the given spellings, the first match
    winning; missing and invalid input both list them."""
    expected = InvalidType(" | ".join(json.dumps(text, ensure_ascii=False) for text, _ in pairs))
    table: dict[str, A] = {}
    for text, value in pairs:
        table.setdefault(text, value)

    def decode(text: str) -> Result[A, Issue]:
        return Ok(table[text]) if text in table else Err(expected)

    return Scalar(expected, decode)


boolean = _choices(
    [(t, True) for t in ("true", "yes", "on", "1", "y")]
    + [(f, False) for f in ("false", "no", "off", "0", "n")]
)

log_level = _choices(
    [
        ("All", LogLevel.ALL),
        ("Fatal", LogLevel.FATAL),
        ("Error", LogLevel.ERROR),
        ("Warn", LogLevel.WARN),
        ("Info", LogLevel.INFO),
        ("Debug", LogLevel.DEBUG),
        ("Trace", LogLevel.TRACE),
        ("None", LogLevel.NONE),
    ]
)


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


_DURATION = re.compile(
    rf"(-?[0-9]+(?:\.[0-9]+)?)[{SPACE}]+"
    r"(nanos?|micros?|millis?|seconds?|minutes?|hours?|days?|weeks?)"
)
_UNIT_SECONDS = {
    "nano": Decimal("1e-9"),
    "micro": Decimal("1e-6"),
    "milli": Decimal("1e-3"),
    "second": Decimal(1),
    "minute": Decimal(60),
    "hour": Decimal(3600),
    "day": Decimal(86400),
    "week": Decimal(604800),
}


def _duration(text: str) -> Result[Seconds, Issue]:
    if text == "Infinity":
        return Ok(Seconds(math.inf))
    if text == "-Infinity":
        return Ok(Seconds(-math.inf))
    match = _DURATION.fullmatch(text)
    if match is None:
        return Err(InvalidValue("Expected a valid Duration string"))
    amount, unit = match.groups()
    return Ok(Seconds(float(Decimal(amount) * _UNIT_SECONDS[unit.removesuffix("s")])))


duration = Scalar(_STRING, _duration)


def _byte_size(text: str) -> Result[ByteSize, Issue]:
    size = byte_size_from_string(text)
    return Err(InvalidValue("Expected a valid ByteSize string")) if size is None else Ok(size)


byte_size = Scalar(_STRING, _byte_size)


def _date_time(text: str) -> Result[datetime, Issue]:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return Err(InvalidValue("Expected a valid Date"))
    return Ok(parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC))


date_time = Scalar(_STRING, _date_time)

_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*")
_SPECIAL_SCHEMES = frozenset({"http", "https", "ws", "wss", "ftp"})
_INVALID_URL = InvalidValue("Expected a valid URL string")


def _url(text: str) -> Result[SplitResult, Issue]:
    if any(ch <= " " or ch == "\x7f" for ch in text):
        return Err(_INVALID_URL)
    try:
        url = urlsplit(text)
        _ = url.port  # raises ValueError for a port that is not a number in range
    except ValueError:
        return Err(_INVALID_URL)
    if not _SCHEME.fullmatch(url.scheme):
        return Err(_INVALID_URL)
    if url.scheme.lower() in _SPECIAL_SCHEMES and not url.hostname:
        return Err(_INVALID_URL)
    return Ok(url)


url = Scalar(_STRING, _url)


def _mapped[A, B](scalar: Scalar[A], f: Callable[[A], B]) -> Scalar[B]:
    decode = scalar.decode
    return Scalar(scalar.missing, lambda text: decode(text).map(f))


redacted = _mapped(string, Redacted)
