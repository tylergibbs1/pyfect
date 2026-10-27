"""``Effect`` methods over time: delaying, timing, caching and schedules.
The work lives in ``pyfect.clock``, ``pyfect._cached`` and
``pyfect.schedule``; these are the method spellings."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.duration import Duration

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.exit import Exit
    from pyfect.schedule import Schedule


class TimingMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def delay(self, duration: Duration) -> Effect[A_co, E_co, R_co]:
        from pyfect.clock import sleep

        return sleep(duration).and_then(as_effect(self))

    def timed(self) -> Effect[tuple[float, A_co], E_co, R_co]:
        """Pair the value with how long it took, in seconds."""
        from pyfect.clock import timed

        return timed(as_effect(self))

    def cached(self) -> Effect[Effect[A_co, E_co, R_co]]:
        """An effect that runs this one on first use and then replays its
        exit. Concurrent callers share one run; an interrupted run is not
        cached (see ``cached_invalidate_with_ttl``)."""
        from pyfect._cached import cached

        return cached(as_effect(self))

    def cached_with_ttl(
        self, time_to_live: Duration | Callable[[Exit[A_co, E_co]], Duration]
    ) -> Effect[Effect[A_co, E_co, R_co]]:
        """``cached``, but each exit is replayed only for ``time_to_live``
        (or ``time_to_live(exit)``) after it was produced."""
        from pyfect._cached import cached_invalidate_with_ttl

        return cached_invalidate_with_ttl(as_effect(self), time_to_live).map(lambda pair: pair[0])

    def cached_invalidate_with_ttl(
        self, time_to_live: Duration | Callable[[Exit[A_co, E_co]], Duration]
    ) -> Effect[tuple[Effect[A_co, E_co, R_co], Effect[None]]]:
        """``cached_with_ttl`` plus an effect that drops the cached exit.

        Callers already waiting on a run keep waiting on it; later callers
        start a fresh run. A run is interrupted once every caller waiting on
        it has gone, and an interrupted run is never cached."""
        from pyfect._cached import cached_invalidate_with_ttl

        return cached_invalidate_with_ttl(as_effect(self), time_to_live)

    def retry(self, schedule: Schedule[E_co, object]) -> Effect[A_co, E_co, R_co]:
        """Retry on typed failure, as long as ``schedule`` allows."""
        from pyfect.schedule import retry

        return retry(as_effect(self), schedule)

    def repeat[B](self, schedule: Schedule[A_co, B]) -> Effect[B, E_co, R_co]:
        """Repeat after each success, as long as ``schedule`` allows.
        Succeeds with the schedule's last output."""
        from pyfect.schedule import repeat

        return repeat(as_effect(self), schedule)
