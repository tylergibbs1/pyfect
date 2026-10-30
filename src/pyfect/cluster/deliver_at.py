"""``DeliverAt``: a message payload that says when it is due (Effect's
``DeliverAt``). Message storage holds it back until then."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, TypeIs, runtime_checkable

from pyfect.date_time._epoch import to_epoch_millis


@runtime_checkable
class DeliverAt(Protocol):
    """Anything with a ``deliver_at()`` method giving an aware datetime."""

    def deliver_at(self) -> datetime: ...


def is_deliver_at(value: object) -> TypeIs[DeliverAt]:
    return isinstance(value, DeliverAt)


def to_millis(value: object) -> int | None:
    """The Unix milliseconds ``value`` is due at, or ``None`` when it is
    not a ``DeliverAt``."""
    if isinstance(value, DeliverAt):
        return to_epoch_millis(value.deliver_at())
    return None


__all__ = ["DeliverAt", "is_deliver_at", "to_millis"]
