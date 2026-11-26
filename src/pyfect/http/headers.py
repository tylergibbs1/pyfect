"""HTTP headers (Effect's ``Headers``): an immutable mapping from lowercased
header names to values, plus the header value formats the client reads
(HTTP dates, ``Retry-After`` and ``Link``).

Lookups are case-insensitive (``headers["Content-Type"]``), and every
update gives a new ``Headers``::

    headers = from_input({"Content-Type": "text/plain"}).set("X-Id", "1")
    headers["x-id"]   # "1"
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import ClassVar, Literal, cast, final
from urllib.parse import quote

from pyfect import _json_text
from pyfect._digits import is_digits, parse_digits
from pyfect._js import to_well_formed
from pyfect._js import trim as js_trim
from pyfect.context import Reference
from pyfect.duration import Duration, from_input_unsafe, nanos, seconds, zero
from pyfect.duration import Input as DurationInput
from pyfect.duration import millis as millis_duration
from pyfect.errors import TaggedError
from pyfect.http import _header_lines
from pyfect.http._ext_value import decode_ext_value
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

    def append(self, key: str, value: str) -> Headers:
        """``value`` added to ``key``'s value, joined with ``", "``; an empty value changes
        nothing. For list-valued headers such as ``Link`` or ``Vary``, not ``Set-Cookie``."""
        if value == "":
            return self
        name = key.lower()
        previous = self._entries.get(name)
        return self.set(name, value if previous is None else f"{previous}, {value}")

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

    def __redacted__(self) -> dict[str, str | Redacted[str]]:
        """The entries with the values of ``CurrentRedactedNames`` hidden,
        as logs and traces show them (Effect's ``Redactable``)."""
        return self.redact(current_redacted_names())

    def to_json(self) -> dict[str, str]:
        """The entries, with ``"<redacted>"`` for the redacted names."""
        return {k: str(v) for k, v in self.__redacted__().items()}


EMPTY: Headers = Headers()


def from_input(input: Input | None = None) -> Headers:
    """Headers from a mapping or ``(name, value)`` pairs. Names are lowercased; list values
    in a mapping and repeated names in pairs are joined with ``", "``, and ``None`` values
    are left out. A comma-joined ``set-cookie`` is not safe to forward as one header: read a
    client response's ``cookies`` instead."""
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
    return Headers._unsafe(_header_lines.joined((name.lower(), value) for name, value in input))  # pyright: ignore[reportPrivateUsage]


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
    """Why a header value failed to parse: an invalid HTTP date or ``Retry-After``."""

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
            # 9999-12-31 23:59:60 is past datetime.max: invalid, as RFC 9110 reads it.
            return day + timedelta(hours=hour, minutes=minute, seconds=second)
        except (ValueError, OverflowError):
            return None
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


# --- Link (RFC 8288) ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Link:
    """One link of a ``Link`` header: the URI reference ``target`` (between ``<`` and
    ``>``), its relation types ``rel``, and every other parameter by name (``anchor``,
    ``title``, ``hreflang``...). A parameter without a value, such as ``nopush``, is
    ``""``."""

    target: str
    rel: tuple[str, ...] = ()
    params: Mapping[str, str] = field(default_factory=dict[str, str], hash=False)


def _skip_space(input: str, i: int) -> int:
    while input[i : i + 1] in (" ", "\t"):
        i += 1
    return i


def _read_param_value(input: str, i: int) -> tuple[str, int]:
    """The value of a link parameter after its ``=``, and the index after it."""
    if input[i : i + 1] != '"':
        start = i
        while i < len(input) and input[i] not in ";,":
            i += 1
        return js_trim(input[start:i]), i
    i += 1
    chars: list[str] = []
    while i < len(input) and input[i] != '"':
        if input[i] == "\\":
            i += 1
        chars.append(input[i : i + 1])
        i += 1
    return "".join(chars), i + 1


def _read_link_params(input: str, i: int) -> tuple[str | None, dict[str, str], int]:
    """The ``rel`` and other parameters of a link after its target, and the index after them."""
    plain: dict[str, str] = {}
    extended: dict[str, str | None] = {}
    while True:
        i = _skip_space(input, i)
        if input[i : i + 1] != ";":
            break
        i = start = _skip_space(input, i + 1)
        while i < len(input) and input[i] not in "=;, \t":
            i += 1
        name = input[start:i].lower()
        i = _skip_space(input, i)
        value = ""
        if input[i : i + 1] == "=":
            value, i = _read_param_value(input, _skip_space(input, i + 1))
        if len(name) > 1 and name.endswith("*"):
            extended.setdefault(name[:-1], decode_ext_value(value))
        elif name and name not in plain:
            plain[name] = value
    # Read rel before the extended params, so rel* cannot set it; then drop it from params.
    rel = plain.pop("rel", None)
    plain.update({name: text for name, text in extended.items() if text is not None})
    plain.pop("rel", None)
    return rel, plain, i


def parse_link(input: str) -> list[Link]:
    """The links of a ``Link`` header value, read by the forgiving algorithm of RFC 8288
    Appendix B, so it never fails: at input that is no link, it stops and gives the links read
    so far. Parameter names and relation types are lowercased, and for every parameter the
    first occurrence wins. An extended parameter such as ``title*`` is decoded (RFC 8187) and
    stored as ``title``, replacing the plain one; an undecodable one is ignored, and ``rel*``
    never sets the relation types. Targets are as written and ``anchor`` is an ordinary
    parameter (``response.links`` resolves targets and skips anchored links)::

        parse_link('</items?page=2>; rel="next last"')
        # [Link("/items?page=2", ("next", "last"), {})]
    """
    links: list[Link] = []
    i = 0
    while True:
        while input[i : i + 1] in (" ", "\t", ","):
            i += 1
        if input[i : i + 1] != "<":
            return links
        end = input.find(">", i + 1)
        if end == -1:
            return links
        target = input[i + 1 : end]
        rel, params, i = _read_link_params(input, end + 1)
        types = () if rel is None else tuple(t for t in _LINK_SPACES.split(rel.lower()) if t)
        links.append(Link(target, types, params))


_LINK_SPACES = re.compile("[ \t]+")
_QUOTABLE = re.compile(r"[\t\x20-\x7e]*\Z")
_RELATION_TYPE_UNSAFE = re.compile(r"[^\x21\x23-\x5b\x5d-\x7e]")
_QUOTED_SPECIALS = re.compile(r'["\\]')


def _format_relation_type(type: str) -> str:
    # Percent-encoded outside visible ASCII, and `"` and `\`, so a type cannot end the quoted rel.
    return _RELATION_TYPE_UNSAFE.sub(lambda m: quote(m[0], safe=""), to_well_formed(type))


def _format_link_param(name: str, value: str) -> str:
    if value == "":
        return name
    if _QUOTABLE.match(value):
        return f'{name}="{_QUOTED_SPECIALS.sub(lambda m: "\\" + m[0], value)}"'
    return f"{name}*=UTF-8''{quote(to_well_formed(value), safe='-_.!~')}"


def format_link(links: Iterable[Link]) -> str:
    """``links`` as a ``Link`` header value: ``<target>``, then ``rel`` when it has relation
    types, then the other parameters, links joined with ``", "``. An empty value is a bare
    name, tabs, spaces and visible ASCII a quoted string, and anything else an RFC 8187
    extended parameter (``title*=UTF-8''Gr%C3%BC%C3%9Fe``). A ``rel`` key in ``params`` is
    ignored. Targets and parameter names are written as given, so they must be valid in a
    header. No links give ``""``, which ``append_header`` ignores::

        response.append_header("Link", format_link([Link("/en", ("canonical",))]))
    """
    out: list[str] = []
    for link in links:
        text = f"<{link.target}>"
        if link.rel:
            text += f'; rel="{" ".join(map(_format_relation_type, link.rel))}"'
        for name, value in link.params.items():
            if name.lower() != "rel":
                text += f"; {_format_link_param(name, value)}"
        out.append(text)
    return ", ".join(out)


__all__ = [
    "EMPTY",
    "CurrentRedactedNames",
    "HeaderParseError",
    "HeaderParseErrorReason",
    "Headers",
    "Input",
    "Link",
    "Pattern",
    "RetryAfter",
    "RetryAfterDateTime",
    "RetryAfterDuration",
    "current_redacted_names",
    "format_http_date",
    "format_link",
    "format_retry_after",
    "from_input",
    "is_redacted_name",
    "parse_http_date",
    "parse_link",
    "parse_retry_after",
    "retry_after_date_time",
    "retry_after_delay",
    "retry_after_duration",
]
