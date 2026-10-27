"""``FiberRuntimeMetrics``, apart from ``pyfect.metric`` so the fiber
runtime can read it without importing the metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from pyfect.context import Reference

if TYPE_CHECKING:
    from pyfect.context import Context
    from pyfect.exit import Exit


class FiberRuntimeMetricsService(Protocol):
    """Told when each fiber starts and ends, with the fiber's context."""

    def record_fiber_start(self, context: Context) -> None: ...

    def record_fiber_end(self, context: Context, exit: Exit[Any, Any]) -> None: ...


class FiberRuntimeMetrics(Reference[FiberRuntimeMetricsService | None]):
    """What records fiber starts and ends; ``None`` (nothing) by default.
    ``metric.enable_runtime_metrics`` provides ``metric.fiber_runtime_metrics``."""

    @classmethod
    def default(cls) -> FiberRuntimeMetricsService | None:
        return None
