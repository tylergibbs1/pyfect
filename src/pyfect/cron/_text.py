"""Cron expressions: ``parse`` text into a ``Cron`` and ``format`` one back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import tzinfo

from pyfect._digits import parse_digits
from pyfect.cron._model import Cron
from pyfect.date_time import zone_from_string
from pyfect.errors import TaggedError
from pyfect.result import Err, Ok, Result


@dataclass(eq=False)
class CronParseError(TaggedError, ValueError):
    """A cron expression (or its time zone) that ``parse`` rejects.
    ``input`` is the rejected text."""

    message: str
    input: str | None = None


@dataclass(frozen=True, slots=True)
class _Field:
    low: int
    high: int
    aliases: dict[str, int] | None = None
    sunday_is_7: bool = False


_SECOND = _Field(0, 59)
_MINUTE = _Field(0, 59)
_HOUR = _Field(0, 23)
_DAY = _Field(1, 31)
_MONTH = _Field(
    1,
    12,
    {
        name: i + 1
        for i, name in enumerate(
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
        )
    },
)
_WEEKDAY = _Field(
    0,
    7,
    {name: i for i, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))},
    sunday_is_7=True,
)


def parse(expression: str, tz: tzinfo | str | None = None) -> Result[Cron, CronParseError]:
    """Parse a cron expression of five fields (minute hour day month
    weekday) or six (with seconds first). Fields take ``*``, values, ranges
    ``a-b``, steps ``/n`` and lists ``a,b``; months and weekdays also take
    three-letter names. ``tz`` is a zone or a zone string
    (``"Europe/Berlin"``, ``"+02:00"``)."""
    segments = expression.split()
    if len(segments) not in (5, 6):
        return Err(CronParseError("Invalid number of segments in cron expression", expression))
    if len(segments) == 5:
        segments.insert(0, "0")
    zone = zone_from_string(tz) if isinstance(tz, str) else tz
    if isinstance(tz, str) and zone is None:
        return Err(CronParseError("Invalid time zone in cron expression", tz))
    parsed: list[tuple[set[int], bool]] = []
    for segment, spec in zip(
        segments, (_SECOND, _MINUTE, _HOUR, _DAY, _MONTH, _WEEKDAY), strict=True
    ):
        result = _parse_segment(segment, spec)
        if isinstance(result, CronParseError):
            return Err(result)
        parsed.append(result)
    seconds, minutes, hours, (days, days_wild), months, (weekdays, weekdays_wild) = parsed
    return Ok(
        Cron(
            tz=zone,
            seconds=seconds[0],
            minutes=minutes[0],
            hours=hours[0],
            days=days,
            months=months[0],
            weekdays=weekdays,
            and_=(days_wild or weekdays_wild) and bool(days) and bool(weekdays),
        )
    )


def parse_unsafe(expression: str, tz: tzinfo | str | None = None) -> Cron:
    """``parse``, raising ``CronParseError`` for a bad expression."""
    return parse(expression, tz).get_or_raise()


def _number(text: str) -> int | None:
    """A plain decimal integer, or ``None`` (Effect's ``NaN``)."""
    return parse_digits(text)


def _split_step(text: str) -> tuple[str, bool, int | None]:
    raw, slash, step = text.partition("/")
    return (raw, True, _number(step)) if slash else (raw, False, None)


def _value(text: str, spec: _Field) -> int | None:
    alias = spec.aliases.get(text.lower()) if spec.aliases else None
    return alias if alias is not None else _number(text)


def _parse_segment(text: str, spec: _Field) -> tuple[set[int], bool] | CronParseError:
    """The segment's values and whether it starts with ``*``. A leading
    ``*`` with no step leaves the field unrestricted."""
    values: set[int] = set()
    fields = text.split(",")
    first = _split_step(fields[0])
    wildcard = first[0] == "*"
    unrestricted = wildcard and (not first[1] or first[2] == 1)
    for index, part in enumerate(fields):
        raw, has_step, step = first if index == 0 else _split_step(part)
        error = _step_error(has_step, step, spec)
        if error is not None:
            return CronParseError(error, text)
        by = 1 if step is None else step
        if raw == "*" and index == 0 and by == 1:
            continue
        bounds = (spec.low, spec.high) if raw == "*" else _bounds(raw, has_step, spec)
        if isinstance(bounds, str):
            return CronParseError(bounds, text)
        if not unrestricted:
            start, stop = bounds
            values.update(
                0 if spec.sunday_is_7 and v == 7 else v for v in range(start, stop + 1, by)
            )
    return values, wildcard


def _step_error(has_step: bool, step: int | None, spec: _Field) -> str | None:
    if not has_step:
        return None
    if step is None:
        return "Expected step value to be a positive integer"
    if step < 1:
        return "Expected step value to be greater than 0"
    if step > spec.high:
        return f"Expected step value to be less than or equal to {spec.high}"
    return None


def _bounds(raw: str, has_step: bool, spec: _Field) -> tuple[int, int] | str:
    """The first and last value of ``a``, ``a/n`` (up to the field's
    maximum) or ``a-b``, or an error message."""
    left_text, dash, right_text = raw.partition("-")
    left = _checked_value(left_text, spec)
    if isinstance(left, str) or not dash:
        return left if isinstance(left, str) else (left, spec.high if has_step else left)
    right = _checked_value(right_text, spec)
    if isinstance(right, str):
        return right
    return "Invalid value range" if left > right else (left, right)


def _checked_value(text: str, spec: _Field) -> int | str:
    value = _value(text, spec)
    if value is None:
        return "Expected a positive integer"
    if not spec.low <= value <= spec.high:
        return f"Expected a value between {spec.low} and {spec.high}"
    return value


def format(cron: Cron, *, include_seconds: bool = False) -> str:
    """The cron expression for ``cron``, compacting runs into ranges and
    steps. The seconds field is left out when it is just 0, unless
    ``include_seconds``. The zone is not part of the expression."""
    fields = (cron.seconds, cron.minutes, cron.hours, cron.days, cron.months, cron.weekdays)
    segments = [_format_segment(values) for values in fields]
    if not include_seconds and cron.seconds == frozenset({0}):
        segments = segments[1:]
    return " ".join(segments)


def _format_segment(values: frozenset[int]) -> str:
    if not values:
        return "*"
    array = sorted(values)
    segments: list[str] = []
    index = 0
    while index < len(array):
        start = array[index]
        if index + 2 < len(array):
            step = array[index + 1] - start
            if array[index + 2] - array[index + 1] == step:
                end = index + 2
                while end + 1 < len(array) and array[end + 1] - array[end] == step:
                    end += 1
                segments.append(f"{start}-{array[end]}" + ("" if step == 1 else f"/{step}"))
                index = end + 1
                continue
        segments.append(str(start))
        index += 1
    return ",".join(segments)
