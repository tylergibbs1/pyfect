"""Matching a datetime against a ``Cron`` and searching for the next or
previous matching instant, following Effect's ``Cron.next`` / ``prev``
field by field (and its DST handling) on a wall-clock time in the cron's
zone."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from pyfect.cron._model import Cron
from pyfect.cron._wall import days_in_month, weekday, with_fields
from pyfect.date_time._zones import make_zoned, zone_of

_SEARCH_BUDGET = 10_000


def match(cron: Cron, date: datetime) -> bool:
    """Whether ``date`` (an aware datetime), read in the cron's zone, is one
    of the cron's times."""
    zone_of(date, "date")
    wall = (date if cron.tz is None else date.astimezone(cron.tz)).replace(tzinfo=None)
    fields = (
        (cron.seconds, wall.second),
        (cron.minutes, wall.minute),
        (cron.hours, wall.hour),
        (cron.months, wall.month),
    )
    return all(not allowed or value in allowed for allowed, value in fields) and _day_matches(
        cron, wall
    )


def _day_matches(cron: Cron, wall: datetime) -> bool:
    """Days and weekdays both restricted match either, unless ``and_``."""
    in_days = wall.day in cron.days
    in_weekdays = weekday(wall) in cron.weekdays
    if cron.and_ or not cron.days or not cron.weekdays:
        return (not cron.days or in_days) and (not cron.weekdays or in_weekdays)
    return in_days or in_weekdays


def next(cron: Cron, now: datetime | None = None) -> datetime:
    """The first of the cron's times strictly after ``now`` (default: the
    current time), in the cron's zone. A wall time a DST fold repeats runs
    at the occurrence ``cron.on_dst_overlap`` picks (both with ``"both"``);
    one a DST change skips runs at the matching time after the gap. Raises
    ``ValueError`` when no time matches (such as February 30)."""
    return _step(cron, now, reverse=False)


def prev(cron: Cron, now: datetime | None = None) -> datetime:
    """The last of the cron's times strictly before ``now`` (default: the
    current time), in the cron's zone. Raises ``ValueError`` when no time
    matches."""
    return _step(cron, now, reverse=True)


def _step(cron: Cron, now: datetime | None, *, reverse: bool) -> datetime:
    start = _start(cron, now)
    if cron.on_dst_overlap != "both":
        return _Walk(cron, start, reverse=reverse, policy=cron.on_dst_overlap).run()
    # Both occurrences are eligible, so the result is the nearer of the two
    # single-occurrence searches in the search direction.
    earlier = _Walk(cron, start, reverse=reverse, policy="earlier").run()
    later = _Walk(cron, start, reverse=reverse, policy="later").run()
    # Compared as instants: aware datetimes sharing a zone compare by wall time.
    if reverse:
        return earlier if _utc(earlier) >= _utc(later) else later
    return earlier if _utc(earlier) <= _utc(later) else later


def sequence(cron: Cron, now: datetime | None = None) -> Iterator[datetime]:
    """The cron's times after ``now`` (default: the current time), forever."""
    current = now
    while True:
        current = next(cron, current)
        yield current


def _start(cron: Cron, now: datetime | None) -> datetime:
    """``now`` in the zone the search runs in: the cron's, else ``now``'s
    own, else the local offset at the current time."""
    if now is None:
        now = datetime.now(UTC).astimezone()
    zone_of(now, "now")
    return now if cron.tz is None else now.astimezone(cron.tz)


class _NoMatch(ValueError):
    def __init__(self) -> None:
        super().__init__("Unable to find cron date")


type _Step = Callable[[datetime], datetime | None]


class _Walk:
    """One search. Each field step either moves the wall time (to the
    field's nearest allowed value, resetting the smaller fields to their
    boundary) or accepts it; the search ends when every field accepts."""

    def __init__(
        self, cron: Cron, start: datetime, *, reverse: bool, policy: Literal["earlier", "later"]
    ) -> None:
        plan = cron._plan
        self.cron = cron
        self.start = start
        self.zone = zone = zone_of(start, "now")
        self.reverse = reverse
        self.tick = -1 if reverse else 1
        self.table = plan.prev if reverse else plan.next
        self.bound = plan.last if reverse else plan.first
        self.dst = not isinstance(zone, timezone) and not (
            isinstance(zone, ZoneInfo) and zone.key == "UTC"
        )
        # Repeated wall times resolve to the occurrence the policy picks; gaps
        # resolve to the instant after the gap either way.
        self.disambiguation: Literal["compatible", "later"] = (
            "later" if policy == "later" else "compatible"
        )
        self.fold_seconds: int | None = None
        self.start_utc = _utc(start)

    def run(self) -> datetime:
        try:
            return self._run()
        except (OverflowError, ValueError):
            # Running off ``datetime``'s years 1-9999 means nothing matched.
            raise _NoMatch() from None

    def _run(self) -> datetime:
        steps: tuple[_Step, ...] = (self._second, self._minute, self._hour, self._day, self._month)
        first = self.start.replace(tzinfo=None)
        if self.dst:
            # When the input is in the occurrence the policy excludes, eligible
            # instants of the same fold can lie behind its wall time in the
            # search direction. Start from the wall time of the input under the
            # policy's offset so they are visited; candidates that resolve on
            # the wrong side of the input are skipped below.
            shift = self.start_utc - _utc(self._resolve(first))
            if shift > timedelta(0) if self.reverse else shift < timedelta(0):
                first += shift
        # Start from the nearest whole second strictly past the input in the
        # search direction. Going backward, a fractional input already has one.
        offset = 0 if self.reverse and first.microsecond > 0 else self.tick
        wall = with_fields(first, second=first.second + offset)
        attempts = 0
        while attempts < _SEARCH_BUDGET:
            attempts += 1
            moved = _first_move(steps, wall)
            if moved is not None:
                wall = self._adjust(moved)
            elif self._out_of_range(wall):
                wall = self._skip_out_of_range(wall)
                attempts = 0  # skipped fold candidates do not count against the budget
            else:
                return make_zoned(wall, self.zone, disambiguation=self.disambiguation)
        raise _NoMatch()

    def _needs_step(self, target: int, current: int) -> bool:
        return target < current if self.reverse else target > current

    def _resolve(self, wall: datetime) -> datetime:
        return make_zoned(wall, self.zone, disambiguation=self.disambiguation)

    def _adjust(self, wall: datetime) -> datetime:
        """Move a wall time that a DST change skips out of the gap. Going
        backward, a candidate inside a gap is left in place: it resolves to
        the instant after the gap, which the range check rejects when that
        instant is not before the input."""
        if not self.dst or self.reverse:
            return wall
        resolved = make_zoned(wall, self.zone)
        drift = wall - resolved.replace(tzinfo=None)
        return wall + drift if drift > timedelta(0) else wall

    def _out_of_range(self, wall: datetime) -> bool:
        """Inside a fold, wall-clock order differs from instant order, so a
        candidate can resolve to an instant on the wrong side of the input."""
        if not self.dst:
            return False
        resolved = _utc(self._resolve(wall))
        return resolved >= self.start_utc if self.reverse else resolved <= self.start_utc

    def _skip_out_of_range(self, wall: datetime) -> datetime:
        """The next candidate second past ``wall``. Inside a fold the rejected
        candidates form one interval no longer than the fold, so when the wall
        time one fold length ahead is in range, binary search for the first
        second in range instead of stepping through the interval. Gaps break
        that ordering, so they keep stepping one second at a time."""
        if self.fold_seconds is None:
            # A fold near the input shows as a larger offset a day before it
            # than a day after it.
            day = timedelta(days=1)
            before = _utc_offset(self.start - day, self.zone)
            after = _utc_offset(self.start + day, self.zone)
            self.fold_seconds = math.floor((before - after).total_seconds())
        fold = self.fold_seconds

        def ahead(seconds: int) -> datetime:
            return wall + timedelta(seconds=self.tick * seconds)

        out_of_range, in_range = 0, 1
        if fold > 0 and not self._out_of_range(ahead(fold)):
            in_range = fold
            while in_range - out_of_range > 1:
                mid = out_of_range + (in_range - out_of_range) // 2
                if self._out_of_range(ahead(mid)):
                    out_of_range = mid
                else:
                    in_range = mid
        return ahead(in_range)

    def _day_start(self, wall: datetime, *, day: int) -> datetime:
        b = self.bound
        return with_fields(wall, day=day, hour=b.hour, minute=b.minute, second=b.second)

    def _second(self, wall: datetime) -> datetime | None:
        if not self.cron.seconds:
            return None
        target = self.table.second[wall.second]
        if target is None:
            return with_fields(wall, minute=wall.minute + self.tick, second=self.bound.second)
        return with_fields(wall, second=target) if self._needs_step(target, wall.second) else None

    def _minute(self, wall: datetime) -> datetime | None:
        if not self.cron.minutes:
            return None
        b = self.bound
        target = self.table.minute[wall.minute]
        if target is None:
            return with_fields(wall, hour=wall.hour + self.tick, minute=b.minute, second=b.second)
        if self._needs_step(target, wall.minute):
            return with_fields(wall, minute=target, second=b.second)
        return None

    def _hour(self, wall: datetime) -> datetime | None:
        if not self.cron.hours:
            return None
        b = self.bound
        target = self.table.hour[wall.hour]
        if target is None:
            return self._day_start(wall, day=wall.day + self.tick)
        if self._needs_step(target, wall.hour):
            return with_fields(wall, hour=target, minute=b.minute, second=b.second)
        return None

    def _day(self, wall: datetime) -> datetime | None:
        cron = self.cron
        if not cron.weekdays and not cron.days:
            return None
        if cron.and_:
            day_ok = not cron.days or wall.day in cron.days
            weekday_ok = not cron.weekdays or weekday(wall) in cron.weekdays
            return (
                None if day_ok and weekday_ok else self._day_start(wall, day=wall.day + self.tick)
            )
        add_days = self._days_to_candidate(wall)
        return None if add_days == 0 else self._day_start(wall, day=wall.day + add_days)

    def _days_to_candidate(self, wall: datetime) -> int:
        """Days to the nearest day matching the day-of-month or the weekday
        restriction (whichever comes first), 0 if ``wall``'s day does."""
        by_weekday = by_day = -math.inf if self.reverse else math.inf
        if self.cron.weekdays:
            by_weekday = self._days_by_weekday(wall)
        if self.cron.days and by_weekday != 0:
            by_day = self._days_by_day(wall)
        return int(max(by_weekday, by_day) if self.reverse else min(by_weekday, by_day))

    def _days_by_weekday(self, wall: datetime) -> int:
        current = weekday(wall)
        target = self.table.weekday[current]
        if target is not None:
            return target - current
        if self.reverse:
            return self.bound.weekday - 7 - current
        return 7 - current + self.bound.weekday

    def _days_by_day(self, wall: datetime) -> int:
        current = wall.day
        target = self.table.day[current]
        month_days = days_in_month(wall.year, wall.month)
        if target is None and self.reverse:
            # Day zero is the previous month's last day. These two probes
            # cover every valid day of the month.
            previous = with_fields(wall, day=0)
            found = self.table.day[previous.day]
            if found is None:
                previous = with_fields(previous, day=0)
                found = self.table.day[previous.day]
            if found is None:
                raise _NoMatch()
            return (with_fields(previous, day=found) - wall).days
        if target is None or (not self.reverse and target > month_days):
            # A next matching day missing from this month must not overflow
            # past the earlier matching days of the next one.
            return month_days - current + self.bound.day
        return target - current

    def _month(self, wall: datetime) -> datetime | None:
        if not self.cron.months:
            return None
        b = self.bound
        target = self.table.month[wall.month]
        if target is None:
            wall = with_fields(wall, year=wall.year + self.tick)
            target = b.month
        elif not self._needs_step(target, wall.month):
            return None
        wall = with_fields(wall, month=target, day=self._month_start_day(wall.year, target))
        return with_fields(wall, hour=b.hour, minute=b.minute, second=b.second)

    def _month_start_day(self, year: int, month: int) -> int:
        last_day = days_in_month(year, month)
        if self.cron.days and not self.cron.weekdays:
            if not self.reverse:
                return self.bound.day
            found = self.table.day[last_day]
            return last_day if found is None else found
        return last_day if self.reverse else 1


def _utc(instant: datetime) -> datetime:
    """The instant in UTC: aware datetimes sharing a ``tzinfo`` compare and
    subtract by wall time, ignoring a fold."""
    return instant.astimezone(UTC)


def _utc_offset(instant: datetime, zone: tzinfo) -> timedelta:
    offset = instant.astimezone(zone).utcoffset()
    assert offset is not None
    return offset


def _first_move(steps: tuple[_Step, ...], wall: datetime) -> datetime | None:
    for step in steps:
        moved = step(wall)
        if moved is not None:
            return moved
    return None
