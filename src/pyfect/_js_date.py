"""JavaScript's ``Date.parse`` (``new Date(text)``) as V8 implements it
(``src/date/dateparser*``): every Effect API that parses a date string
with ``Date`` parses here, never with ``datetime.fromisoformat`` or
``email.utils``, which take and reject different text
(``tests/test_js_date_guard.py``).

V8 first reads the ECMAScript date-time format (``2024-01-15T10:00Z``; a
date alone is UTC, a date-time without an offset local time); what it
cannot finish there goes on to its legacy grammar (``Jan 15 2024 10:00
PM EST``, ``1/15/2024``, ``Mon, 15 Jan 2024 10:00:00 GMT``): words before
the first number and parenthesised text are ignored, years below 50 are
20xx and below 100 19xx, and a time without a zone is local.
``tests/oracle/fixtures/js_date_parse.json`` holds what Node returns for
a corpus of strings in two zones; ``tests/oracle/test_js_date_node.py``
matches it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pyfect.date_time._zones import zone_local

_MS_PER_DAY = 86_400_000
_MAX_TIME = 8_640_000_000_000_000
_MAX_TIME_BEFORE_UTC = _MAX_TIME + 30 * _MS_PER_DAY
_MAX_YEAR = 1_000_000
_SMI_MAX = 2**31 - 1
_MAX_SIGNIFICANT_DIGITS = 9

# ECMAScript's WhiteSpace (Zs plus TAB, VT, FF, NBSP and ZWNBSP); a line
# terminator also separates tokens, but only these end a word.
_WHITE_SPACE = frozenset(
    "\t\v\f \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u202f\u205f\u3000\ufeff"
)
_LINE_TERMINATORS = frozenset("\n\r\u2028\u2029")

# Token tags; a word is a keyword token whose tag is its kind (``_WORD``
# when it names nothing).
_INVALID, _UNKNOWN, _SPACE, _NUMBER, _SYMBOL, _END = range(-6, 0)
_WORD, _MONTH, _ZONE, _TIME_SEPARATOR, _AM_PM = range(5)

_KEYWORDS: dict[str, tuple[int, int]] = {
    **{
        name: (_MONTH, i + 1)
        for i, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
        )
    },
    "am": (_AM_PM, 0),
    "pm": (_AM_PM, 12),
    "ut": (_ZONE, 0),
    "utc": (_ZONE, 0),
    "z": (_ZONE, 0),
    "gmt": (_ZONE, 0),
    "cdt": (_ZONE, -5),
    "cst": (_ZONE, -6),
    "edt": (_ZONE, -4),
    "est": (_ZONE, -5),
    "mdt": (_ZONE, -6),
    "mst": (_ZONE, -7),
    "pdt": (_ZONE, -7),
    "pst": (_ZONE, -8),
    "t": (_TIME_SEPARATOR, 0),
}


@dataclass(frozen=True, slots=True)
class _Token:
    tag: int
    length: int
    value: int

    def is_symbol(self, symbol: str) -> bool:
        return self.tag == _SYMBOL and self.value == ord(symbol)

    def is_sign(self) -> bool:
        return self.is_symbol("+") or self.is_symbol("-")

    def is_number(self, length: int | None = None) -> bool:
        return self.tag == _NUMBER and (length is None or self.length == length)

    def is_keyword_z(self) -> bool:
        return self.tag == _ZONE and self.length == 1 and self.value == 0


def _keyword(word: str) -> tuple[int, int]:
    prefix = "".join(chr(ord(c) | 0x20) for c in word[:3])
    kind, value = _KEYWORDS.get(prefix, (_WORD, 0))
    return (kind, value) if len(word) <= 3 or kind == _MONTH else (_WORD, 0)


class _Scanner:
    """V8's ``DateStringTokenizer`` over its ``InputReader``: a NUL ends
    the input, as it does there."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0
        self._next = self._scan()

    def _ch(self) -> str:
        return self._text[self._index] if self._index < len(self._text) else "\0"

    def _scan(self) -> _Token:
        ch = self._ch()
        if ch == "\0":
            return _Token(_END, 0, -1)
        start = self._index
        if "0" <= ch <= "9":
            while self._ch() == "0":
                self._index += 1
            significant = self._index
            while "0" <= self._ch() <= "9":
                self._index += 1
            value = int(self._text[significant : self._index][:_MAX_SIGNIFICANT_DIGITS] or "0")
            return _Token(_NUMBER, self._index - start, value)
        self._index += 1
        if ch in ":-+.)":
            return _Token(_SYMBOL, 1, ord(ch))
        if ch >= "A" and ch not in _WHITE_SPACE:
            while self._ch() >= "A" and self._ch() not in _WHITE_SPACE:
                self._index += 1
            word = self._text[start : self._index]
            kind, value = _keyword(word)
            return _Token(kind, len(word), value)
        if ch in _WHITE_SPACE or ch in _LINE_TERMINATORS:
            return _Token(_SPACE, 1, -1)
        if ch == "(":
            depth = 1
            while depth > 0 and self._ch() != "\0":
                depth += {"(": 1, ")": -1}.get(self._ch(), 0)
                self._index += 1
        return _Token(_UNKNOWN, 1, -1)

    def peek(self) -> _Token:
        return self._next

    def next(self) -> _Token:
        token, self._next = self._next, self._scan()
        return token

    def skip(self, symbol: str) -> bool:
        if self._next.is_symbol(symbol):
            self._next = self._scan()
            return True
        return False


def _between(x: int | None, lo: int, hi: int) -> bool:
    return x is not None and lo <= x <= hi


@dataclass(slots=True)
class _Zone:
    sign: int | None = None
    hour: int | None = None
    minute: int | None = None

    def set(self, hours: int) -> None:
        self.sign = -1 if hours < 0 else 1
        self.hour, self.minute = abs(hours), 0

    def expecting(self, n: int) -> bool:
        return self.hour is not None and self.minute is None and _between(n, 0, 59)

    def is_utc(self) -> bool:
        return self.hour == 0 and self.minute == 0

    def offset_seconds(self) -> int | None:
        """The offset; ``None`` when none was given. Raises ``ValueError``
        past V8's limit (its unsigned 32-bit sum, then a Smi)."""
        if self.sign is None:
            return None
        total = ((self.hour or 0) * 3600 + (self.minute or 0) * 60) & 0xFFFFFFFF
        if total > _SMI_MAX:
            raise ValueError
        return self.sign * total


@dataclass(slots=True)
class _Time:
    parts: list[int] = field(default_factory=list[int])
    hour_offset: int | None = None

    def expecting(self, n: int) -> bool:
        index = len(self.parts)
        return (index in (1, 2) and _between(n, 0, 59)) or (index == 3 and _between(n, 0, 999))

    def add(self, n: int) -> bool:
        if len(self.parts) >= 4:
            return False
        self.parts.append(n)
        return True

    def add_final(self, n: int) -> bool:
        if not self.add(n):
            return False
        self.parts += [0] * (4 - len(self.parts))
        return True

    def millis(self) -> int:
        hour, minute, second, ms = [*self.parts, 0, 0, 0, 0][:4]
        if self.hour_offset is not None:
            if not 0 <= hour <= 12:
                raise ValueError
            hour = hour % 12 + self.hour_offset
        in_range = hour <= 23 and minute <= 59 and second <= 59 and ms <= 999
        if not in_range and (hour, minute, second, ms) != (24, 0, 0, 0):
            raise ValueError
        return ((hour * 60 + minute) * 60 + second) * 1000 + ms


@dataclass(slots=True)
class _Day:
    parts: list[int] = field(default_factory=list[int])
    named_month: int | None = None
    iso: bool = False

    def add(self, n: int) -> bool:
        if len(self.parts) >= 3:
            return False
        self.parts.append(n)
        return True

    def ymd(self) -> tuple[int, int, int]:
        """V8 pads the parts with 1s before it looks at how many there
        are, so a missing year is 1 (2001): ``Jan 15`` is 2001-01-15."""
        if not self.parts:
            raise ValueError
        a, b, c = [*self.parts, 1, 1][:3]
        if self.named_month is None:
            year, month, day = (a, b, c) if self.iso or not _between(a, 1, 31) else (c, a, b)
        else:
            month = self.named_month
            year, day = (a, b) if not _between(a, 1, 31) else (b, a)
        if not self.iso:
            year += 2000 if 0 <= year <= 49 else 1900 if 50 <= year <= 99 else 0
        if not (_between(month, 1, 12) and _between(day, 1, 31)):
            raise ValueError
        return year, month, day


def _read_millis(token: _Token) -> int:
    length = min(token.length, _MAX_SIGNIFICANT_DIGITS)
    return token.value * 10 ** (3 - length) if length < 3 else token.value // 10 ** (length - 3)


def _two_digits(token: _Token, lo: int, hi: int) -> bool:
    return token.is_number(2) and lo <= token.value <= hi


def _es5(scanner: _Scanner, day: _Day, time: _Time, zone: _Zone) -> _Token:  # noqa: PLR0911, PLR0912
    """V8's ``ParseES5DateTime``: the token the legacy grammar goes on
    with, ``_END`` when the text was all read, ``_INVALID`` when it can no
    longer be a date."""
    if scanner.peek().is_sign():
        sign_token = scanner.next()
        if not scanner.peek().is_number(6):
            return sign_token
        year = scanner.peek().value
        if sign_token.is_symbol("-") and year == 0:
            return sign_token
        scanner.next()
        day.add(-year if sign_token.is_symbol("-") else year)
    elif scanner.peek().is_number(4):
        day.add(scanner.next().value)
    else:
        return scanner.next()
    if scanner.skip("-"):
        if not _two_digits(scanner.peek(), 1, 12):
            return scanner.next()
        day.add(scanner.next().value)
        if scanner.skip("-"):
            if not _two_digits(scanner.peek(), 1, 31):
                return scanner.next()
            day.add(scanner.next().value)
    if scanner.peek().tag != _TIME_SEPARATOR:
        if scanner.peek().tag != _END:
            return scanner.next()
    else:
        scanner.next()
        if not _two_digits(scanner.peek(), 0, 24):
            return _Token(_INVALID, 0, -1)
        top = 0 if scanner.peek().value == 24 else 59
        time.add(scanner.next().value)
        if not scanner.skip(":") or not _two_digits(scanner.peek(), 0, top):
            return _Token(_INVALID, 0, -1)
        time.add(scanner.next().value)
        if scanner.skip(":"):
            if not _two_digits(scanner.peek(), 0, top):
                return _Token(_INVALID, 0, -1)
            time.add(scanner.next().value)
            if scanner.skip("."):
                if not scanner.peek().is_number() or (top == 0 and scanner.peek().value > 0):
                    return _Token(_INVALID, 0, -1)
                time.add(_read_millis(scanner.next()))
        if scanner.peek().is_keyword_z():
            scanner.next()
            zone.set(0)
        elif scanner.peek().is_sign():
            zone.sign = 1 if scanner.next().is_symbol("+") else -1
            if scanner.peek().is_number(4):
                hour, minute = divmod(scanner.next().value, 100)
                if hour > 23 or minute > 59:
                    return _Token(_INVALID, 0, -1)
                zone.hour, zone.minute = hour, minute
            else:
                if not _two_digits(scanner.peek(), 0, 23):
                    return _Token(_INVALID, 0, -1)
                zone.hour = scanner.next().value
                if not scanner.skip(":") or not _two_digits(scanner.peek(), 0, 59):
                    return _Token(_INVALID, 0, -1)
                zone.minute = scanner.next().value
        if scanner.peek().tag != _END:
            return _Token(_INVALID, 0, -1)
    if zone.hour is None and not time.parts:
        zone.set(0)
    day.iso = True
    return _Token(_END, 0, -1)


class _Legacy:
    """V8's ``DateParser::Parse``: the ES5 format, then its legacy grammar
    over the tokens left; each ``_number`` / ``_word`` / ``_sign`` returns
    whether the text can still be a date."""

    def __init__(self, text: str) -> None:
        self.scanner = _Scanner(text)
        self.day, self.time, self.zone = _Day(), _Time(), _Zone()
        self.has_read_number = False

    def fields(self) -> tuple[_Day, _Time, _Zone] | None:
        token = _es5(self.scanner, self.day, self.time, self.zone)
        if token.tag == _INVALID:
            return None
        self.has_read_number = bool(self.day.parts)
        while token.tag != _END:
            if token.tag == _NUMBER:
                ok = self._number(token.value)
            elif token.tag >= _WORD:
                ok = self._word(token)
            elif token.is_sign() and (self.zone.is_utc() or self.time.parts):
                ok = self._sign(token)
            else:
                ok = not ((token.is_sign() or token.is_symbol(")")) and self.has_read_number)
            if not ok:
                return None
            token = self.scanner.next()
        return self.day, self.time, self.zone

    def _number(self, n: int) -> bool:
        scanner, time = self.scanner, self.time
        self.has_read_number = True
        if scanner.skip(":"):
            if scanner.skip(":"):
                return not time.parts and time.add(n) and time.add(0)
            if not time.add(n):
                return False
            if scanner.peek().is_symbol("."):
                scanner.next()
        elif scanner.skip(".") and time.expecting(n):
            time.add(n)
            if not scanner.peek().is_number():
                return False
            time.add_final(_read_millis(scanner.next()))
        elif self.zone.expecting(n):
            self.zone.minute = n
        elif time.expecting(n):
            time.add_final(n)
            peek = scanner.peek()
            return peek.tag in (_END, _SPACE) or peek.is_keyword_z() or peek.is_sign()
        else:
            if not self.day.add(n):
                return False
            scanner.skip("-")
        return True

    def _word(self, token: _Token) -> bool:
        if token.tag == _AM_PM and self.time.parts:
            self.time.hour_offset = token.value
        elif token.tag == _MONTH:
            self.day.named_month = token.value
            self.scanner.skip("-")
        elif token.tag == _ZONE and self.has_read_number:
            self.zone.set(token.value)
        else:
            return not self.has_read_number and self.scanner.peek().tag != _NUMBER
        return True

    def _sign(self, token: _Token) -> bool:
        zone = self.zone
        zone.sign = 1 if token.is_symbol("+") else -1
        n = length = 0
        if self.scanner.peek().tag == _NUMBER:
            number = self.scanner.next()
            n, length = number.value, number.length
        self.has_read_number = True
        if self.scanner.peek().is_symbol(":"):
            zone.hour, zone.minute = n, None
        elif length in (1, 2):
            zone.hour, zone.minute = n, 0
        elif length in (3, 4):
            zone.hour, zone.minute = divmod(n, 100)
        else:
            return False
        return True


def _civil_from_days(days: int) -> tuple[int, int, int]:
    """Year, month (1-based) and day of ``days`` after 1970-01-01."""
    z = days + 719_468
    era = z // 146_097
    doe = z - era * 146_097
    yoe = (doe - doe // 1460 + doe // 36_524 - doe // 146_096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    month = mp + 3 if mp < 10 else mp - 9
    return yoe + era * 400 + (month <= 2), month, doy - (153 * mp + 2) // 5 + 1


def _days_from_civil(year: int, month: int) -> int:
    """Days from 1970-01-01 to the first of ``month`` (1-based) of ``year``."""
    y = year - (month <= 2)
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5
    return era * 146_097 + yoe * 365 + yoe // 4 - yoe // 100 + doy - 719_468


def _local_offset_ms(local_ms: int) -> int:
    """The local zone's offset at the wall-clock time ``local_ms``; in a
    gap or an overlap the offset before the transition (ICU's
    ``UCAL_TZ_LOCAL_FORMER``, which V8 asks for: Python's ``fold=0``).
    Years outside ``datetime``'s range use the same year of the 400-year
    cycle (the same calendar) inside it."""
    days, ms = divmod(local_ms, _MS_PER_DAY)
    year, month, day = _civil_from_days(days)
    if not 1 <= year <= 9999:
        year = year % 400 + (400 if year < 1 else 9200)
    wall = datetime(year, month, day) + timedelta(milliseconds=ms)
    offset = wall.replace(tzinfo=zone_local()).utcoffset() or timedelta(0)
    return offset // timedelta(milliseconds=1)


def parse(text: str) -> int | None:
    """``Date.parse(text)``: epoch milliseconds, ``None`` for an Invalid Date."""
    fields = _Legacy(text).fields()
    if fields is None:
        return None
    day, time, zone = fields
    try:
        year, month, day_of_month = day.ymd()
        millis_of_day = time.millis()
        offset = zone.offset_seconds()
    except ValueError:
        return None
    if abs(year) > _MAX_YEAR:
        return None
    date = (_days_from_civil(year, month) + day_of_month - 1) * _MS_PER_DAY + millis_of_day
    if offset is not None:
        date -= offset * 1000
    elif abs(date) <= _MAX_TIME_BEFORE_UTC:
        date -= _local_offset_ms(date)
    else:
        return None
    return date if abs(date) <= _MAX_TIME else None


_HAS_ZONE = re.compile(r"Z|GMT|[+-][0-9]{2}$|[+-][0-9]{2}:?[0-9]{2}$|\]$")
_ENDS_IN_ZONE = re.compile(r"(?:z|gmt)$", re.IGNORECASE)


def parse_input(text: str) -> int | None:
    """A ``DateTime.Input`` string, as Effect's ``DateTime.makeUnsafe``
    reads it: ``parse``, with a ``Z`` added when ``text`` names no zone,
    so a date-time without an offset is UTC rather than local time."""
    has_zone = _HAS_ZONE.search(text) is not None or _ENDS_IN_ZONE.search(text) is not None
    return parse(text if has_zone else text + "Z")


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def to_datetime(millis: int | None) -> datetime | None:
    """``millis`` as a UTC ``datetime``; ``None`` for ``None`` or an
    instant outside years 1 to 9999, which ``datetime`` cannot hold."""
    if millis is None:
        return None
    try:
        return _EPOCH + timedelta(milliseconds=millis)
    except OverflowError:
        return None
