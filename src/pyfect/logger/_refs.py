"""The references logging reads (Effect's ``References`` and ``Logger``
references)."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pyfect.context import Reference
from pyfect.logger._level import LogLevel, Severity
from pyfect.logger._model import Logger, LogSpan


class MinimumLogLevel(Reference[LogLevel]):
    """Logs below this level are dropped. ``LogLevel.INFO`` by default;
    ``ALL`` keeps everything and ``NONE`` nothing."""

    @classmethod
    def default(cls) -> LogLevel:
        return LogLevel.INFO


class CurrentLogLevel(Reference[Severity]):
    """The level ``fx.log`` writes at. ``LogLevel.INFO`` by default."""

    @classmethod
    def default(cls) -> Severity:
        return LogLevel.INFO


class UnhandledLogLevel(Reference[Severity | None]):
    """The level failures nobody can handle (a pool or cache finalizer's)
    are logged at; ``None`` drops them. ``LogLevel.ERROR`` by default."""

    @classmethod
    def default(cls) -> Severity | None:
        return LogLevel.ERROR


_NO_ANNOTATIONS: Mapping[str, object] = MappingProxyType({})


class CurrentLogAnnotations(Reference[Mapping[str, object]]):
    """Key/value pairs added to every log (``annotate_logs``)."""

    @classmethod
    def default(cls) -> Mapping[str, object]:
        return _NO_ANNOTATIONS


class CurrentLogSpans(Reference[tuple[LogSpan, ...]]):
    """The open log spans, innermost first (``with_log_span``)."""

    @classmethod
    def default(cls) -> tuple[LogSpan, ...]:
        return ()


class CurrentLoggers(Reference[tuple[Logger[Any], ...]]):
    """The loggers each log goes to, in order; no logger appears twice.
    By default ``logger.default_logger`` and ``logger.tracer_logger``."""

    @classmethod
    def default(cls) -> tuple[Logger[Any], ...]:
        from pyfect.logger._console import default_logger
        from pyfect.logger._tracer import tracer_logger

        return (default_logger, tracer_logger)


class LogToStderr(Reference[bool]):
    """When true, the console loggers write with ``error`` instead of
    ``log``. ``False`` by default."""

    @classmethod
    def default(cls) -> bool:
        return False
