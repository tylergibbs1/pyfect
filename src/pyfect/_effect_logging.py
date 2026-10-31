"""``Effect`` methods for logging: annotations, spans and extra loggers."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, overload

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._fiber import Fiber
    from pyfect.logger import Logger


class LoggingMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    @overload
    def annotate_logs(self, key: str, value: object, /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def annotate_logs(self, values: Mapping[str, object], /) -> Effect[A_co, E_co, R_co]: ...
    def annotate_logs(
        self, key_or_values: str | Mapping[str, object], value: object = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Run with these annotations added to every log."""
        from pyfect.logger import CurrentLogAnnotations

        added = {key_or_values: value} if isinstance(key_or_values, str) else dict(key_or_values)
        return as_effect(self).update_service(
            CurrentLogAnnotations, lambda annotations: {**annotations, **added}
        )

    def with_log_span(self, label: str) -> Effect[A_co, E_co, R_co]:
        """Run inside a log span: logs show ``label=<elapsed>ms``, timed by
        the ``Clock`` from when this effect starts."""
        from pyfect.clock import Clock, now_millis_unsafe
        from pyfect.logger import CurrentLogSpans, LogSpan

        inner = as_effect(self)

        def body(fiber: Fiber[Any, Any]) -> Effect[A_co, E_co, R_co]:
            span = LogSpan(label, now_millis_unsafe(fiber.get_ref(Clock)))
            return inner.update_service(CurrentLogSpans, lambda spans: (span, *spans))

        return _core._WithFiber(body)

    def with_logger(self, logger: Logger[object]) -> Effect[A_co, E_co, R_co]:
        """Run with ``logger`` added to the current loggers."""
        from pyfect.logger import CurrentLoggers

        return as_effect(self).update_service(
            CurrentLoggers,
            lambda loggers: loggers if any(lg is logger for lg in loggers) else (*loggers, logger),
        )
