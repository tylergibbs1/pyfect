"""HTTP headers (Effect's ``Headers``): an immutable mapping from lowercased
header names to values, plus the header value formats the client reads
(HTTP dates and ``Retry-After``).

Lookups are case-insensitive (``headers["Content-Type"]``), and every
update gives a new ``Headers``::

    headers = from_input({"Content-Type": "text/plain"}).set("X-Id", "1")
    headers["x-id"]   # "1"
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import ClassVar, Literal, cast, final

from pyfect import _json_text
from pyfect._digits import is_digits, parse_digits
from pyfect.context import Reference
from pyfect.duration import Duration, from_input_unsafe, nanos, seconds, zero
from pyfect.duration import Input as DurationInput
from pyfect.duration import millis as millis_duration
from pyfect.errors import TaggedError
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok, Result

type Pattern = str | re.Pattern[str]
"""A header (or URL parameter) name to redact: a name compared without case,
or a regular expression searched in the name."""

type Input = Mapping[str, str | Sequence[str] | None] | Iterable[tuple[str, str]] | Headers
"""What ``from_input`` takes: a mapping (a sequence value is joined with
``", "``, a ``None`` value is skipped) or ``(name, value)`` pairs."""


@final
class Headers(Mapping[str, str]):
    """Header names (lowercased) to values. Equal to another ``Headers`` with
    the same entries; ``repr`` hides the values of ``CurrentRedactedNames``."""

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[str, str] | None = None) -> None:
        self._entries: dict[str, str] = {k.lower(): v for k, v in (entries or {}).items()}

    @classmethod
    def _unsafe(cls, entries: dict[str, str]) -> Headers:
        self = cls.__new__(cls)
        self._entries = entries
        return self

    def __getitem__(self, key: str) -> str:
        return self._entries[key.lower()]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._entries

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Headers):
            return NotImplemented
        return self._entries == other._entries

    def __hash__(self) -> int:
        return hash(frozenset(self._entries.items()))

    def __repr__(self) -> str:
        return f"Headers({self.redact(current_redacted_names())!r})"

    def has(self, key: str) -> bool:
        return key.lower() in self._entries

    def set(self, key: str, value: str) -> Headers:
        return Headers._unsafe({**self._entries, key.lower(): value})

    def set_all(self, headers: Input) -> Headers:
        return Headers._unsafe({**self._entries, **from_input(headers)._entries})

    def merge(self, headers: Headers) -> Headers:
        return Headers._unsafe({**self._entries, **headers._entries})

    def remove(self, key: str) -> Headers:
        return self.remove_many((key,))

    def remove_many(self, keys: Iterable[str]) -> Headers:
        drop = {k.lower() for k in keys}
        return Headers._unsafe({k: v for k, v in self._entries.items() if k not in drop})

    def redact(self, key: Pattern | Sequence[Pattern]) -> dict[str, str | Redacted[str]]:
        """The entries, with the values of the names matching ``key``
        hidden in ``Redacted``."""
        patterns: Sequence[Pattern] = (key,) if isinstance(key, (str, re.Pattern)) else key
        return {
            name: Redacted(value) if is_redacted_name(name, patterns) else value
            for name, value in self._entries.items()
        }

    def to_json(self) -> dict[str, str]:
        """The entries, with ``"<redacted>"`` for the redacted names."""
        return {k: str(v) for k, v in self.redact(current_redacted_names()).items()}


EMPTY: Headers = Headers()


def from_input(input: Input | None = None) -> Headers:
    if input is None:
        return EMPTY
    if isinstance(input, Headers):
        return input
    if isinstance(input, Mapping):
        out: dict[str, str] = {}
        record = cast("Mapping[str, str | Sequence[str] | None]", input)
        for key, value in record.items():
            if isinstance(value, str):
                out[key.lower()] = value
            elif value is not None:
                out[key.lower()] = ", ".join(value)
        return Headers._unsafe(out)  # pyright: ignore[reportPrivateUsage]
    return Headers._unsafe({k.lower(): v for k, v in input})  # pyright: ignore[reportPrivateUsage]


def is_redacted_name(name: str, patterns: Sequence[Pattern]) -> bool:
    lower = name.lower()
    for pattern in patterns:
        if isinstance(pattern, str):
            if pattern.lower() == lower:
                return True
        elif pattern.search(name) is not None:
            return True
    return False


class CurrentRedactedNames(Reference[tuple[Pattern, ...]]):
    """The header names whose values logs and spans hide (Effect's
    default, plus ``proxy-authorization``)."""

    @classmethod
    def default(cls) -> tuple[Pattern, ...]:
        return ("authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key")


def current_redacted_names() -> tuple[Pattern, ...]:
    """``CurrentRedactedNames`` of the running fiber, or the default."""
    from pyfect._fiber import current_fiber

    fiber = current_fiber()
    return CurrentRedactedNames.default() if fiber is None else fiber.get_ref(CurrentRedactedNames)


# --- header values -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeaderParseErrorReason:
    tag: Literal["InvalidHttpDate", "InvalidRetryAfter"]
    input: str


@dataclass(eq=False)
class HeaderParseError(TaggedError):
    """A header value that is not in the expected format."""

    reason: HeaderParseErrorReason

    @staticmethod
    def from_reason(
        tag: Literal["InvalidHttpDate", "InvalidRetryAfter"], input: str
    ) -> HeaderParseError:
        return HeaderParseError(HeaderParseErrorReason(tag, input))

    @property
    def message(self) -> str:
        return f"{self.reason.tag}: {_json_text.stringify(self.reason.input)}"


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_TIME = r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
_HTTP_DATE_FORMATS = (
    # Sun, 06 Nov 1994 08:49:37 GMT
    re.compile(
        rf"(?:mon|tue|wed|thu|fri|sat|sun), (?P<day>\d{{2}}) (?P<month>[a-z]{{3}}) "
        rf"(?P<year>\d{{4}}) {_TIME} gmt",
        re.IGNORECASE | re.ASCII,
    ),
    # Sunday, 06-Nov-94 08:49:37 GMT
    re.compile(
        r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday), "
        rf"(?P<day>\d{{2}})-(?P<month>[a-z]{{3}})-(?P<year>\d{{2}}) {_TIME} gmt",
        re.IGNORECASE | re.ASCII,
    ),
    # Sun Nov  6 08:49:37 1994
    re.compile(
        r"(?:mon|tue|wed|thu|fri|sat|sun) (?P<month>[a-z]{3}) (?P<day> \d|\d{2}) "
        rf"{_TIME} (?P<year>\d{{4}})",
        re.IGNORECASE | re.ASCII,
    ),
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _http_date(text: str) -> datetime | None:
    """RFC 9110 §5.6.7: IMF-fixdate, then the obsolete RFC 850 and asctime
    forms. Two-digit years pivot at 70; a leap second reads as the next."""
    for pattern in _HTTP_DATE_FORMATS:
        match = pattern.fullmatch(text)
        if match is None:
            continue
        month_name = match["month"].lower()
        hour, minute, second = int(match["hour"]), int(match["minute"]), int(match["second"])
        if month_name not in _MONTHS or hour > 23 or minute > 59 or second > 60:
            return None
        year = int(match["year"])
        if len(match["year"]) == 2:
            year += 2000 if year < 70 else 1900
        try:
            day = datetime(year, _MONTHS.index(month_name) + 1, int(match["day"]), tzinfo=UTC)
        except ValueError:
            return None
        return day + timedelta(hours=hour, minutes=minute, seconds=second)
    return None


def parse_http_date(input: str) -> Result[datetime, HeaderParseError]:
    """An HTTP date as an aware UTC ``datetime``."""
    parsed = _http_date(input.strip())
    if parsed is None:
        return Err(HeaderParseError.from_reason("InvalidHttpDate", input))
    return Ok(parsed)


def format_http_date(value: datetime) -> str:
    """``value`` as an IMF-fixdate (``Sun, 06 Nov 1994 08:49:37 GMT``)."""
    return format_datetime(value.astimezone(UTC).replace(microsecond=0), usegmt=True)


# --- Retry-After (RFC 9110 §10.2.3) ------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RetryAfterDuration:
    """A ``Retry-After`` of a delay."""

    duration: Duration
    tag: ClassVar[Literal["Duration"]] = "Duration"


@final
@dataclass(frozen=True, slots=True)
class RetryAfterDateTime:
    """A ``Retry-After`` of a date (an aware UTC ``datetime``)."""

    date_time: datetime
    tag: ClassVar[Literal["DateTime"]] = "DateTime"


type RetryAfter = RetryAfterDuration | RetryAfterDateTime


def retry_after_duration(duration: DurationInput) -> RetryAfterDuration:
    """A ``Retry-After`` of ``duration``; negative is zero, infinite raises
    ``ValueError``."""
    parsed = from_input_unsafe(duration)
    if not parsed.is_finite():
        raise ValueError("Cannot create a Retry-After value from an infinite duration")
    return RetryAfterDuration(zero if parsed.is_negative() else parsed)


def retry_after_date_time(date_time: datetime) -> RetryAfterDateTime:
    return RetryAfterDateTime(date_time)


_NANOS_PER_SECOND = 1_000_000_000
_MAX_SAFE = 2**53 - 1


def parse_retry_after(input: str) -> Result[RetryAfter, HeaderParseError]:
    """Whole seconds or an HTTP date; anything else (negative, fractional,
    exponent forms) is an ``InvalidRetryAfter``."""
    trimmed = input.strip()
    if is_digits(trimmed):
        whole = parse_digits(trimmed)
        if whole is None:  # more digits than int() reads
            return Err(HeaderParseError.from_reason("InvalidRetryAfter", input))
        # The millisecond form while it is exact; beyond that, whole nanoseconds.
        safe = whole * 1000 <= _MAX_SAFE
        return Ok(RetryAfterDuration(seconds(whole) if safe else nanos(whole * _NANOS_PER_SECOND)))
    parsed = _http_date(trimmed)
    if parsed is None:
        return Err(HeaderParseError.from_reason("InvalidRetryAfter", input))
    return Ok(RetryAfterDateTime(parsed))


def format_retry_after(value: RetryAfter) -> str:
    """Whole seconds rounded up, or an IMF-fixdate."""
    match value:
        case RetryAfterDuration(duration):
            whole = (duration.to_nanos_unsafe() + _NANOS_PER_SECOND - 1) // _NANOS_PER_SECOND
            return str(whole)
        case RetryAfterDateTime(date_time):
            return format_http_date(date_time)


def retry_after_delay(value: RetryAfter, now_millis: float) -> Duration:
    """How long to wait from ``now_millis`` (epoch milliseconds); never
    negative."""
    match value:
        case RetryAfterDuration(duration):
            return duration
        case RetryAfterDateTime(date_time):
            millis = (date_time - _EPOCH) // timedelta(milliseconds=1)
            return millis_duration(max(0.0, millis - now_millis))


__all__ = [
    "EMPTY",
    "CurrentRedactedNames",
    "HeaderParseError",
    "HeaderParseErrorReason",
    "Headers",
    "Input",
    "Pattern",
    "RetryAfter",
    "RetryAfterDateTime",
    "RetryAfterDuration",
    "current_redacted_names",
    "format_http_date",
    "format_retry_after",
    "from_input",
    "is_redacted_name",
    "parse_http_date",
    "parse_retry_after",
    "retry_after_date_time",
    "retry_after_delay",
    "retry_after_duration",
]
