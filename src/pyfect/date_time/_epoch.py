"""Epoch milliseconds, exactly: integer arithmetic on ``timedelta``, never
``timestamp()`` or a division by 1000 (a float holds a far year's
milliseconds only to about a microsecond)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from fractions import Fraction

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


def from_epoch_millis(millis: float) -> datetime:
    """The UTC instant ``millis`` milliseconds after the epoch (to the
    nearest microsecond). Raises ``OverflowError`` outside years 1 to 9999."""
    return EPOCH + timedelta(milliseconds=millis)


def from_epoch_micros(micros: int) -> datetime:
    """The UTC instant ``micros`` microseconds after the epoch, exactly. Raises
    ``OverflowError`` outside years 1 to 9999."""
    return EPOCH + timedelta(microseconds=micros)


def to_epoch_micros(value: datetime) -> int:
    """``value``'s microseconds since the epoch, exactly."""
    return (value - EPOCH) // _MICROSECOND


def to_epoch_millis(value: datetime) -> int:
    """``value``'s milliseconds since the epoch, rounded half to even."""
    return round(Fraction((value - EPOCH) // _MICROSECOND, 1000))
