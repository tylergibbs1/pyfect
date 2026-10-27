"""``Effect`` methods over time: delaying, timing, caching and schedules.
The work lives in ``pyfect.clock``, ``pyfect._cached`` and
``pyfect.schedule``; these are the method spellings."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, TypeIs, overload

from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.duration import Duration

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.exit import Exit
    from pyfect.schedule import Metadata, Schedule, SetInputType


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

    @overload
    def retry[EE = Never, RR = Never](
        self, policy: Schedule[object, E_co, EE, RR], /
    ) -> Effect[A_co, E_co | EE, R_co | RR]: ...
    @overload
    def retry[A, E, R, EE = Never, RR = Never](
        self: TimingMethods[A, E, R],
        builder: Callable[[SetInputType[E]], Schedule[object, E, EE, RR]],
        /,
    ) -> Effect[A, E | EE, R | RR]: ...
    @overload
    def retry[E2, EE = Never, RR = Never](
        self,
        /,
        *,
        until: Callable[[E_co], TypeIs[E2]],
        while_: Callable[[E_co], bool | Effect[bool, EE, RR]] | None = None,
    ) -> Effect[A_co, E2 | EE, R_co | RR]: ...
    @overload
    def retry[EE = Never, RR = Never](
        self,
        /,
        *,
        schedule: Schedule[object, E_co, EE, RR] | None = None,
        times: int | None = None,
        while_: Callable[[E_co], bool | Effect[bool, EE, RR]] | None = None,
        until: Callable[[E_co], bool | Effect[bool, EE, RR]] | None = None,
    ) -> Effect[A_co, E_co | EE, R_co | RR]: ...
    def retry(
        self,
        policy: Schedule[Any, Any, Any, Any] | Callable[[Any], Any] | None = None,
        /,
        *,
        schedule: Schedule[Any, Any, Any, Any] | None = None,
        times: int | None = None,
        while_: Callable[[Any], Any] | None = None,
        until: Callable[[Any], Any] | None = None,
    ) -> Effect[Any, Any, Any]:
        """Retry on typed failure while ``policy`` recurs; then fail with the
        last error. Defects and interruptions are not retried.

        ``policy`` is a schedule, or a function from ``SetInputType`` to
        one, so the schedule's metadata sees this effect's error type::

            eff.retry(lambda typed: typed(schedule.recurs(3)).while_(lambda m: m.input.retryable))

        Instead of a policy, the keywords build one: retry at most
        ``times`` times, only while ``while_(error)`` holds, until
        ``until(error)`` holds, on ``schedule``'s delays. Predicates may
        return a bool or an effect of one; with a ``TypeIs`` predicate as
        ``until`` (and no ``schedule`` or ``times``), the error narrows."""
        from pyfect.schedule._drive import resolve_policy, retry

        policy = resolve_policy(policy, schedule, times, while_, until)
        return retry(as_effect(self), policy)

    def retry_or_else[B, A2, EE = Never, RR = Never](
        self,
        policy: Schedule[B, E_co, EE, RR],
        or_else: Callable[[E_co, B], Effect[A2, EE, RR]],
    ) -> Effect[A_co | A2, EE, R_co | RR]:
        """``retry``, handing the last error and the policy's final output
        to ``or_else`` once the policy stops."""
        from pyfect.schedule._drive import retry_or_else

        return retry_or_else(as_effect(self), policy, or_else)

    @overload
    def repeat[B, EE = Never, RR = Never](
        self, schedule: Schedule[B, A_co, EE, RR], /
    ) -> Effect[B, E_co | EE, R_co | RR]: ...
    @overload
    def repeat[A, E, R, B, EE = Never, RR = Never](
        self: TimingMethods[A, E, R],
        builder: Callable[[SetInputType[A]], Schedule[B, A, EE, RR]],
        /,
    ) -> Effect[B, E | EE, R | RR]: ...
    @overload
    def repeat[B, EE = Never, RR = Never](
        self,
        /,
        *,
        until: Callable[[A_co], TypeIs[B]],
        while_: Callable[[A_co], bool | Effect[bool, EE, RR]] | None = None,
    ) -> Effect[B, E_co | EE, R_co | RR]: ...
    @overload
    def repeat[EE = Never, RR = Never](
        self,
        /,
        *,
        schedule: Schedule[object, A_co, EE, RR] | None = None,
        times: int | None = None,
        while_: Callable[[A_co], bool | Effect[bool, EE, RR]] | None = None,
        until: Callable[[A_co], bool | Effect[bool, EE, RR]] | None = None,
    ) -> Effect[A_co, E_co | EE, R_co | RR]: ...
    def repeat(
        self,
        policy: Schedule[Any, Any, Any, Any] | Callable[[Any], Any] | None = None,
        /,
        *,
        schedule: Schedule[Any, Any, Any, Any] | None = None,
        times: int | None = None,
        while_: Callable[[Any], Any] | None = None,
        until: Callable[[Any], Any] | None = None,
    ) -> Effect[Any, Any, Any]:
        """Repeat after each success while the schedule recurs. Succeeds
        with the schedule's final output. The schedule may also be given
        as a function from ``SetInputType`` to one (see ``retry``).

        Instead of a schedule, the keywords build one: repeat at most
        ``times`` times, only while ``while_(value)`` holds, until
        ``until(value)`` holds, on ``schedule``'s delays. That form
        succeeds with the last value, narrowed by a ``TypeIs`` predicate
        as ``until`` (with no ``schedule`` or ``times``). Predicates may
        return a bool or an effect of one."""
        from pyfect.schedule._drive import repeat, resolve_policy

        policy = resolve_policy(policy, schedule, times, while_, until)
        return repeat(as_effect(self), policy)

    def repeat_or_else[B, B2, E2, EE = Never, RR = Never](
        self,
        schedule: Schedule[B, A_co, EE, RR],
        or_else: Callable[[E_co | EE, Metadata[B, A_co] | None], Effect[B2, E2, RR]],
    ) -> Effect[B | B2, E2, R_co | RR]:
        """``repeat``, handing a typed failure (of this effect or of the
        schedule) and the last step's metadata (``None`` before the first)
        to ``or_else``."""
        from pyfect.schedule._drive import repeat_or_else

        return repeat_or_else(as_effect(self), schedule, or_else)

    def schedule[B, EE = Never, RR = Never](
        self, schedule: Schedule[B, A_co | None, EE, RR]
    ) -> Effect[B, E_co | EE, R_co | RR]:
        """Run after each recurrence of ``schedule`` (first after its first
        delay), stepping it with ``None`` and then each result. Succeeds
        with the schedule's final output."""
        from pyfect.schedule._drive import scheduled

        return scheduled(as_effect(self), schedule)

    def schedule_from[A, B, EE = Never, RR = Never](
        self: TimingMethods[A, E_co, R_co], initial: A, schedule: Schedule[B, A, EE, RR]
    ) -> Effect[B, E_co | EE, R_co | RR]:
        """``schedule``, stepping first with ``initial``."""
        from pyfect.schedule._drive import schedule_from

        return schedule_from(as_effect(self), initial, schedule)
