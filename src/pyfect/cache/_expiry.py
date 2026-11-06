"""What ``Cache`` and ``ScopedCache`` share: time to live and capacity.

Times are wall-clock nanoseconds read from the ``Clock`` of the fiber that
made the entry, as Effect reads ``currentTimeMillis``. An entry expires
once the clock reaches its deadline; an infinite time to live (either
sign) never expires.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from typing import Any, Final, Literal

from pyfect._fiber import Fiber
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration, Seconds, to_nanos, to_seconds
from pyfect.exit import Exit

type TimeToLive[K, A, E] = Duration | Callable[[Exit[A, E], K], Duration]
"""One duration for every entry, or one per lookup outcome and key."""

type RequireServicesAt = Literal["construction", "lookup"]
"""Where the lookup's services come from: the context ``make`` runs in
(``"construction"``, the default), or each caller of ``get``
(``"lookup"``)."""

_FOREVER: Final = Seconds(math.inf)


def time_to_live_of[K, A, E](
    time_to_live: TimeToLive[K, A, E] | None,
) -> Callable[[Exit[A, E], K], Seconds]:
    if time_to_live is None:
        return _forever
    if callable(time_to_live):
        pick = time_to_live
        return lambda ex, key: to_seconds(pick(ex, key))
    fixed = to_seconds(time_to_live)
    return lambda _ex, _key: fixed


def _forever(_ex: object, _key: object) -> Seconds:
    return _FOREVER


def clock_of(fiber: Fiber[Any, Any]) -> ClockService:
    return fiber._context.lookup(Clock)[1]


def deadline(clock: ClockService, time_to_live: Seconds) -> int | None:
    """When an entry made now with ``time_to_live`` expires; ``None`` for
    never."""
    if math.isinf(time_to_live):
        return None
    return clock.now_nanos_unsafe() + to_nanos(time_to_live)


def is_expired(expires_at: int | None, now: int) -> bool:
    return expires_at is not None and now >= expires_at


def overflow[K](entries: dict[K, Any], capacity: int | None) -> list[K]:
    """The least recently used keys beyond ``capacity``, oldest first."""
    if capacity is None or len(entries) <= capacity:
        return []
    return list(itertools.islice(entries, len(entries) - capacity))
