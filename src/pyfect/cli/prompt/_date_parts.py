"""The fields of a ``date`` prompt's mask (``YYYY``, ``MM``, ``Do``, ``hh``,
``A``, ...) and the JavaScript-``Date``-like clock they edit."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pyfect.cli.prompt._number import parse_int


@dataclass(frozen=True, slots=True)
class Locales:
    """Month and weekday names for the ``MMM`` / ``MMMM`` / ``ddd`` /
    ``dddd`` mask tokens."""

    months: Sequence[str] = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    months_short: Sequence[str] = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    weekdays: Sequence[str] = (
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    )
    weekdays_short: Sequence[str] = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


class WallClock:
    """A local wall-clock time with JavaScript ``Date``'s setters: setting a
    field out of range carries into the larger ones (day 32 is the next
    month's first)."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def _set(
        self,
        *,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
        hours: int | None = None,
        minutes: int | None = None,
        seconds: int | None = None,
        milliseconds: int | None = None,
    ) -> None:
        v = self.value
        y = v.year if year is None else year
        m = v.month - 1 if month is None else month
        y, m = y + m // 12, m % 12
        base = datetime(y, m + 1, 1)
        self.value = base + timedelta(
            days=(v.day if day is None else day) - 1,
            hours=v.hour if hours is None else hours,
            minutes=v.minute if minutes is None else minutes,
            seconds=v.second if seconds is None else seconds,
            milliseconds=v.microsecond // 1000 if milliseconds is None else milliseconds,
        )

    @property
    def year(self) -> int:
        return self.value.year

    @property
    def month(self) -> int:
        return self.value.month - 1

    @property
    def day(self) -> int:
        return self.value.day

    @property
    def weekday(self) -> int:
        return (self.value.weekday() + 1) % 7

    @property
    def hours(self) -> int:
        return self.value.hour

    @property
    def minutes(self) -> int:
        return self.value.minute

    @property
    def seconds(self) -> int:
        return self.value.second

    @property
    def milliseconds(self) -> int:
        return self.value.microsecond // 1000

    def set_year(self, value: int) -> None:
        self._set(year=value)

    def set_month(self, value: int) -> None:
        self._set(month=value)

    def set_day(self, value: int) -> None:
        self._set(day=value)

    def set_hours(self, value: int) -> None:
        self._set(hours=value)

    def set_minutes(self, value: int) -> None:
        self._set(minutes=value)

    def set_seconds(self, value: int) -> None:
        self._set(seconds=value)

    def set_milliseconds(self, value: int) -> None:
        self._set(milliseconds=value)


def _typed(value: str, digits: int) -> int | None:
    return parse_int(value[-digits:])


class Part(ABC):
    token: str

    def __init__(self, token: str, clock: WallClock, locales: Locales) -> None:
        self.token = token
        self.clock = clock
        self.locales = locales

    def is_token(self) -> bool:
        return False

    @abstractmethod
    def increment(self) -> None: ...
    @abstractmethod
    def decrement(self) -> None: ...
    @abstractmethod
    def set_value(self, value: str) -> None: ...
    @abstractmethod
    def render(self) -> str: ...


class _Token(Part):
    def is_token(self) -> bool:
        return True

    def increment(self) -> None:
        pass

    def decrement(self) -> None:
        pass

    def set_value(self, value: str) -> None:
        self.token += value

    def render(self) -> str:
        return self.token


class _Milliseconds(Part):
    def increment(self) -> None:
        self.clock.set_milliseconds(self.clock.milliseconds + 1)

    def decrement(self) -> None:
        self.clock.set_milliseconds(self.clock.milliseconds - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, len(self.token))
        if typed is not None:
            self.clock.set_milliseconds(typed)

    def render(self) -> str:
        return str(self.clock.milliseconds).rjust(4, "0")[: len(self.token)]


class _Seconds(Part):
    def increment(self) -> None:
        self.clock.set_seconds(self.clock.seconds + 1)

    def decrement(self) -> None:
        self.clock.set_seconds(self.clock.seconds - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 2)
        if typed is not None:
            self.clock.set_seconds(typed)

    def render(self) -> str:
        text = str(self.clock.seconds)
        return text.rjust(2, "0") if len(self.token) > 1 else text


class _Minutes(Part):
    def increment(self) -> None:
        self.clock.set_minutes(self.clock.minutes + 1)

    def decrement(self) -> None:
        self.clock.set_minutes(self.clock.minutes - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 2)
        if typed is not None:
            self.clock.set_minutes(typed)

    def render(self) -> str:
        text = str(self.clock.minutes)
        return text.rjust(2, "0") if len(self.token) > 1 else text


class _Hours(Part):
    def increment(self) -> None:
        self.clock.set_hours(self.clock.hours + 1)

    def decrement(self) -> None:
        self.clock.set_hours(self.clock.hours - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 2)
        if typed is not None:
            self.clock.set_hours(typed)

    def render(self) -> str:
        hours = (self.clock.hours % 12 or 12) if "h" in self.token else self.clock.hours
        return str(hours).rjust(2, "0") if len(self.token) > 1 else str(hours)


def _ordinal(day: int) -> str:
    if 11 <= day <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


class _Day(Part):
    def increment(self) -> None:
        self.clock.set_day(self.clock.day + 1)

    def decrement(self) -> None:
        self.clock.set_day(self.clock.day - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 2)
        if typed is not None:
            self.clock.set_day(typed)

    def render(self) -> str:
        date, day = self.clock.day, self.clock.weekday
        match self.token:
            case "DD":
                return str(date).rjust(2, "0")
            case "Do":
                return f"{date}{_ordinal(date)}"
            case "d":
                return str(day + 1)
            case "ddd":
                return self.locales.weekdays_short[day]
            case "dddd":
                return self.locales.weekdays[day]
            case _:
                return str(date)


class _Month(Part):
    def increment(self) -> None:
        self.clock.set_month(self.clock.month + 1)

    def decrement(self) -> None:
        self.clock.set_month(self.clock.month - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 2)
        if typed is not None:
            self.clock.set_month(max(typed - 1, 0))

    def render(self) -> str:
        month = self.clock.month
        match len(self.token):
            case 2:
                return str(month + 1).rjust(2, "0")
            case 3:
                return self.locales.months_short[month]
            case 4:
                return self.locales.months[month]
            case _:
                return str(month + 1)


class _Year(Part):
    def increment(self) -> None:
        self.clock.set_year(self.clock.year + 1)

    def decrement(self) -> None:
        self.clock.set_year(self.clock.year - 1)

    def set_value(self, value: str) -> None:
        typed = _typed(value, 4)
        if typed is not None:
            self.clock.set_year(typed)

    def render(self) -> str:
        year = str(self.clock.year).rjust(4, "0")
        return year[-2:] if len(self.token) == 2 else year


class _Meridiem(Part):
    def increment(self) -> None:
        self.clock.set_hours((self.clock.hours + 12) % 24)

    def decrement(self) -> None:
        self.increment()

    def set_value(self, value: str) -> None:
        pass

    def render(self) -> str:
        meridiem = "pm" if self.clock.hours >= 12 else "am"
        return meridiem.upper() if "A" in self.token else meridiem


_DATE_PART = re.compile(
    r'\\(.)|"((?:\\["\\]|[^"])+)"|(D[Do]?|d{3,4}|d)|(M{1,4})|(YY(?:YY)?)|([aA])|([Hh]{1,2})|(m{1,2})|(s{1,2})|(S{1,4})|.'
)
_GROUPS: dict[int, Callable[[str, WallClock, Locales], Part]] = {
    2: lambda token, clock, locales: _Token(re.sub(r"\\(.)", r"\1", token), clock, locales),
    3: _Day,
    4: _Month,
    5: _Year,
    6: _Meridiem,
    7: _Hours,
    8: _Minutes,
    9: _Seconds,
    10: _Milliseconds,
}


def make_parts(mask: str, clock: WallClock, locales: Locales) -> list[Part]:
    parts: list[Part] = []
    for match in _DATE_PART.finditer(mask):
        group = next((i for i in range(1, 11) if match.group(i) is not None), None)
        token = match.group(group) if group is not None else match.group(0)
        make = _GROUPS.get(group) if group is not None else None
        part = make(token, clock, locales) if make is not None else _Token(token, clock, locales)
        last = parts[-1] if parts else None
        if part.is_token() and last is not None and last.is_token():
            last.set_value(part.token)
        else:
            parts.append(part)
    return parts


def next_part(parts: Sequence[Part], index: int) -> int | None:
    return next((i for i in range(index + 1, len(parts)) if not parts[i].is_token()), None)


def previous_part(parts: Sequence[Part], index: int) -> int | None:
    return next((i for i in range(index - 1, -1, -1) if not parts[i].is_token()), None)


def first_part(parts: Sequence[Part]) -> int:
    return next((i for i, part in enumerate(parts) if not part.is_token()), -1)
