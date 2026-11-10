"""The ``Cron`` value: the allowed values of each field, plus the lookup
tables ``next`` and ``prev`` search with."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import tzinfo
from typing import Literal, final

type DstOverlapPolicy = Literal["earlier", "later", "both"]
"""Which occurrence of a wall time a DST fold repeats a cron runs at: the
first (``"earlier"``, the default), the second (``"later"``) or both."""


@dataclass(frozen=True, slots=True)
class _Bounds:
    """The first or last allowed value of each field (months 1-based)."""

    second: int
    minute: int
    hour: int
    day: int
    month: int
    weekday: int


type _Table = tuple[int | None, ...]


@dataclass(frozen=True, slots=True)
class _Tables:
    """For each value of a field, the nearest allowed value in one direction
    (itself included), or ``None`` when there is none before the field wraps."""

    second: _Table
    minute: _Table
    hour: _Table
    day: _Table
    month: _Table
    weekday: _Table


@dataclass(frozen=True, slots=True)
class _Plan:
    first: _Bounds
    last: _Bounds
    next: _Tables
    prev: _Tables


@final
@dataclass(frozen=True, slots=True, init=False)
class Cron:
    """A recurring calendar schedule: the allowed seconds, minutes, hours,
    days of the month, months (1-12) and weekdays (0-6, Sunday is 0) and an
    optional zone. An empty field allows every value.

    Days and weekdays both restricted match either one, as in classic cron,
    unless ``and_`` is set. Without a zone, a cron runs in the zone of the
    datetime it is given. A wall time a DST fold repeats runs at the
    occurrence ``on_dst_overlap`` picks. Build one with ``cron.parse`` or
    ``cron.make``."""

    tz: tzinfo | None
    seconds: frozenset[int]
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    and_: bool
    on_dst_overlap: DstOverlapPolicy
    _plan: _Plan = field(compare=False, repr=False)

    def __init__(
        self,
        *,
        minutes: Iterable[int],
        hours: Iterable[int],
        days: Iterable[int],
        months: Iterable[int],
        weekdays: Iterable[int],
        seconds: Iterable[int] = (0,),
        and_: bool = False,
        tz: tzinfo | None = None,
        on_dst_overlap: DstOverlapPolicy = "earlier",
    ) -> None:
        """Raises ``ValueError`` for a value outside its field's range.
        Weekday 7 is Sunday, as 0."""
        fields = {
            "seconds": _restrict("seconds", seconds, 0, 59),
            "minutes": _restrict("minutes", minutes, 0, 59),
            "hours": _restrict("hours", hours, 0, 23),
            "days": _restrict("days", days, 1, 31),
            "months": _restrict("months", months, 1, 12),
            "weekdays": _restrict("weekdays", weekdays, 0, 7, lambda v: 0 if v == 7 else v),
        }
        for name, values in fields.items():
            object.__setattr__(self, name, frozenset(values))
        object.__setattr__(self, "and_", and_)
        object.__setattr__(self, "tz", tz)
        object.__setattr__(self, "on_dst_overlap", on_dst_overlap)
        object.__setattr__(self, "_plan", _plan(**fields))


def make(
    *,
    minutes: Iterable[int],
    hours: Iterable[int],
    days: Iterable[int],
    months: Iterable[int],
    weekdays: Iterable[int],
    seconds: Iterable[int] = (0,),
    and_: bool = False,
    tz: tzinfo | None = None,
    on_dst_overlap: DstOverlapPolicy = "earlier",
) -> Cron:
    """A ``Cron`` from explicit field values (see ``Cron``)."""
    return Cron(
        minutes=minutes,
        hours=hours,
        days=days,
        months=months,
        weekdays=weekdays,
        seconds=seconds,
        and_=and_,
        tz=tz,
        on_dst_overlap=on_dst_overlap,
    )


def _restrict(
    name: str,
    values: Iterable[int],
    low: int,
    high: int,
    normalize: Callable[[int], int] = lambda v: v,
) -> tuple[int, ...]:
    out: set[int] = set()
    for value in values:
        if not isinstance(value, int) or not low <= value <= high:  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(f"{name} must contain only integers between {low} and {high}")
        out.add(normalize(value))
    return tuple(sorted(out))


def _plan(
    *,
    seconds: tuple[int, ...],
    minutes: tuple[int, ...],
    hours: tuple[int, ...],
    days: tuple[int, ...],
    months: tuple[int, ...],
    weekdays: tuple[int, ...],
) -> _Plan:
    def tables(direction: Callable[[tuple[int, ...], int], _Table]) -> _Tables:
        return _Tables(
            second=direction(seconds, 60),
            minute=direction(minutes, 60),
            hour=direction(hours, 24),
            day=direction(days, 32),
            month=direction(months, 13),
            weekday=direction(weekdays, 7),
        )

    return _Plan(
        first=_Bounds(
            second=seconds[0] if seconds else 0,
            minute=minutes[0] if minutes else 0,
            hour=hours[0] if hours else 0,
            day=days[0] if days else 1,
            month=months[0] if months else 1,
            weekday=weekdays[0] if weekdays else 0,
        ),
        last=_Bounds(
            second=seconds[-1] if seconds else 59,
            minute=minutes[-1] if minutes else 59,
            hour=hours[-1] if hours else 23,
            day=days[-1] if days else 31,
            month=months[-1] if months else 12,
            weekday=weekdays[-1] if weekdays else 6,
        ),
        next=tables(_next_table),
        prev=tables(_prev_table),
    )


def _next_table(values: tuple[int, ...], size: int) -> _Table:
    return tuple(next((v for v in values if v >= i), None) for i in range(size))


def _prev_table(values: tuple[int, ...], size: int) -> _Table:
    return tuple(next((v for v in reversed(values) if v <= i), None) for i in range(size))
