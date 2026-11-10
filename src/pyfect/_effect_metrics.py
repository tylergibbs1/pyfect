"""``Effect`` methods for metrics: update a metric with how an effect
ended, what it succeeded or failed with, or how long it took."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, overload

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._fiber import Fiber
    from pyfect.duration import Duration
    from pyfect.exit import Exit
    from pyfect.metric import Metric


class MetricMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    @overload
    def track(self, metric: Metric[Exit[A_co, E_co], object], /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def track[I](
        self, metric: Metric[I, object], f: Callable[[Exit[A_co, E_co]], I], /
    ) -> Effect[A_co, E_co, R_co]: ...
    def track(
        self, metric: Metric[Any, object], f: Callable[[Any], Any] | None = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Update ``metric`` with this effect's exit (or ``f(exit)``)
        however it ends."""
        return as_effect(self).on_exit(lambda ex: metric.update(ex if f is None else f(ex)))

    @overload
    def track_successes(self, metric: Metric[A_co, object], /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def track_successes[I](
        self, metric: Metric[I, object], f: Callable[[A_co], I], /
    ) -> Effect[A_co, E_co, R_co]: ...
    def track_successes(
        self, metric: Metric[Any, object], f: Callable[[Any], Any] | None = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Update ``metric`` with each value (or ``f(value)``)."""
        return as_effect(self).tap(lambda a: metric.update(a if f is None else f(a)))

    @overload
    def track_errors(self, metric: Metric[E_co, object], /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def track_errors[I](
        self, metric: Metric[I, object], f: Callable[[E_co], I], /
    ) -> Effect[A_co, E_co, R_co]: ...
    def track_errors(
        self, metric: Metric[Any, object], f: Callable[[Any], Any] | None = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Update ``metric`` with each typed error (or ``f(error)``)."""
        return as_effect(self).tap_error(lambda e: metric.update(e if f is None else f(e)))

    @overload
    def track_defects(
        self, metric: Metric[BaseException, object], /
    ) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def track_defects[I](
        self, metric: Metric[I, object], f: Callable[[object], I], /
    ) -> Effect[A_co, E_co, R_co]: ...
    def track_defects(
        self, metric: Metric[Any, object], f: Callable[[Any], Any] | None = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Update ``metric`` with each defect (or ``f(defect)``)."""
        return as_effect(self).tap_defect(lambda d: metric.update(d if f is None else f(d)))

    @overload
    def track_duration(self, metric: Metric[Duration, object], /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def track_duration[I](
        self, metric: Metric[I, object], f: Callable[[Duration], I], /
    ) -> Effect[A_co, E_co, R_co]: ...
    def track_duration(
        self, metric: Metric[Any, object], f: Callable[[Any], Any] | None = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Update ``metric`` with how long this effect took (or
        ``f(duration)``), measured on the ``Clock``'s monotonic time
        however it ends."""
        from pyfect.clock import Clock
        from pyfect.duration import nanos

        inner = as_effect(self)

        def body(fiber: Fiber[Any, Any]) -> Effect[A_co, E_co, R_co]:
            clock = fiber.get_ref(Clock)
            start = clock.monotonic_nanos_unsafe()

            def record(_: object) -> Effect[None]:
                elapsed = nanos(clock.monotonic_nanos_unsafe() - start)

                return metric.update(elapsed if f is None else f(elapsed))

            return inner.on_exit(record)

        return _core._WithFiber(body)
