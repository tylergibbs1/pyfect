"""The effectful parts of DateTime: the current time from ``Clock`` and
the ``CurrentTimeZone`` service."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from typing import Never

from pyfect._context_effects import _ProvideServiceEffect, provide_service_effect
from pyfect._core import Effect
from pyfect.clock import Clock
from pyfect.context import Tag
from pyfect.date_time._zones import zone_local, zone_named, zone_of, zone_offset
from pyfect.duration import Duration, to_seconds
from pyfect.effect import _ProvideService, fail, provide_service, succeed, suspend, sync
from pyfect.errors import IllegalArgumentError
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import succeed as layer_succeed
from pyfect.layer import sync as layer_sync

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class CurrentTimeZone(Tag[tzinfo], key="effect/DateTime/CurrentTimeZone"):
    """The zone ``now_in_current_zone`` and ``set_zone_current`` use."""


def now() -> Effect[datetime]:
    """The ``Clock``'s wall time as an aware UTC datetime (to the
    microsecond)."""
    return Clock().map(lambda c: _EPOCH + timedelta(microseconds=c.unsafe_now_nanos() // 1_000))


def now_in_current_zone() -> Effect[datetime, Never, CurrentTimeZone]:
    """``now()`` in the ``CurrentTimeZone``."""
    return now().flat_map(set_zone_current)


def set_zone_current(dt: datetime) -> Effect[datetime, Never, CurrentTimeZone]:
    """The same instant as ``dt``, in the ``CurrentTimeZone``."""
    zone_of(dt, "dt")
    return CurrentTimeZone().map(dt.astimezone)


def is_future(dt: datetime) -> Effect[bool]:
    """Whether ``dt`` is after the ``Clock``'s current time."""
    zone_of(dt, "dt")
    return now().map(lambda current: current < dt)


def is_past(dt: datetime) -> Effect[bool]:
    """Whether ``dt`` is before the ``Clock``'s current time."""
    zone_of(dt, "dt")
    return now().map(lambda current: current > dt)


def zone_named_effect(zone_id: str) -> Effect[tzinfo, IllegalArgumentError]:
    """The IANA zone ``zone_id``; fails with ``IllegalArgumentError`` if
    there is none."""

    def check() -> Effect[tzinfo, IllegalArgumentError]:
        zone = zone_named(zone_id)
        if zone is None:
            return fail(IllegalArgumentError(f"Invalid time zone: {zone_id}"))
        return succeed(zone)

    return suspend(check)


def _offset_zone(offset: Duration) -> tzinfo:
    zone = zone_offset(timedelta(seconds=to_seconds(offset)))
    if zone is None:
        raise ValueError(f"a zone offset must be strictly within a day, got {offset!r}")
    return zone


def with_current_zone(zone: tzinfo) -> _ProvideService[tzinfo, CurrentTimeZone]:
    """Provide ``zone`` as the ``CurrentTimeZone``. Use with ``.pipe``."""
    return provide_service(CurrentTimeZone, zone)


def with_current_zone_offset(offset: Duration) -> _ProvideService[tzinfo, CurrentTimeZone]:
    """Provide the fixed offset ``offset`` from UTC as the
    ``CurrentTimeZone``. Use with ``.pipe``."""
    return with_current_zone(_offset_zone(offset))


def with_current_zone_named(
    zone_id: str,
) -> _ProvideServiceEffect[CurrentTimeZone, IllegalArgumentError, Never]:
    """Provide the IANA zone ``zone_id`` as the ``CurrentTimeZone``; the
    effect fails with ``IllegalArgumentError`` if there is no such zone.
    Use with ``.pipe``."""
    return provide_service_effect(CurrentTimeZone, zone_named_effect(zone_id))


def with_current_zone_local() -> _ProvideServiceEffect[CurrentTimeZone, Never, Never]:
    """Provide the system's zone (read when the effect runs) as the
    ``CurrentTimeZone``. Use with ``.pipe``."""
    return provide_service_effect(CurrentTimeZone, sync(zone_local))


def layer_current_zone(zone: tzinfo) -> Layer[CurrentTimeZone]:
    return layer_succeed(CurrentTimeZone, zone)


def layer_current_zone_offset(offset: Duration) -> Layer[CurrentTimeZone]:
    return layer_succeed(CurrentTimeZone, _offset_zone(offset))


def layer_current_zone_named(zone_id: str) -> Layer[CurrentTimeZone, IllegalArgumentError]:
    return layer_effect(CurrentTimeZone, zone_named_effect(zone_id))


def layer_current_zone_local() -> Layer[CurrentTimeZone]:
    return layer_sync(CurrentTimeZone, zone_local)
