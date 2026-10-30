"""Fiber runtime metrics: counts of fibers started, active, succeeded and
failed, kept while ``FiberRuntimeMetrics`` is provided."""

from __future__ import annotations

from typing import Any, Final, final

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._metric_ref import FiberRuntimeMetrics, FiberRuntimeMetricsService
from pyfect.context import Context
from pyfect.effect import provide_service
from pyfect.exit import Exit, Success
from pyfect.layer import Layer, succeed
from pyfect.metric._kinds import counter, gauge

_fibers_active = gauge(
    "child_fibers_active", description="The current count of active child fibers"
)
_fibers_started = counter(
    "child_fibers_started",
    description="The total number of child fibers that have been started",
    incremental=True,
)
_fiber_successes = counter(
    "child_fiber_successes",
    description="The total number of child fibers that have succeeded",
    incremental=True,
)
_fiber_failures = counter(
    "child_fiber_failures",
    description="The total number of child fibers that have failed",
    incremental=True,
)


@final
class _FiberRuntimeMetrics:
    __slots__ = ()

    def record_fiber_start(self, context: Context) -> None:
        _fibers_started.update_unsafe(1, context)
        _fibers_active.modify_unsafe(1, context)

    def record_fiber_end(self, context: Context, exit: Exit[Any, Any]) -> None:
        _fibers_active.modify_unsafe(-1, context)
        if isinstance(exit, Success):
            _fiber_successes.update_unsafe(1, context)
        else:
            _fiber_failures.update_unsafe(1, context)


fiber_runtime_metrics: Final[FiberRuntimeMetricsService] = _FiberRuntimeMetrics()
"""Records into the gauge ``child_fibers_active`` and the counters
``child_fibers_started``, ``child_fiber_successes`` and
``child_fiber_failures``."""

enable_runtime_metrics_layer: Final[Layer[FiberRuntimeMetrics]] = succeed(
    FiberRuntimeMetrics, fiber_runtime_metrics
)
disable_runtime_metrics_layer: Final[Layer[FiberRuntimeMetrics]] = succeed(
    FiberRuntimeMetrics, None
)


def enable_runtime_metrics[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    """Run ``eff`` recording the fibers it starts in the runtime metrics."""
    require_effect(eff, "eff")
    return eff.pipe(provide_service(FiberRuntimeMetrics, fiber_runtime_metrics))


def disable_runtime_metrics[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    """Run ``eff`` without recording fibers."""
    require_effect(eff, "eff")
    return eff.pipe(provide_service(FiberRuntimeMetrics, None))
