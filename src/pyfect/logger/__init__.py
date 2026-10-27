"""Logging (Effect's ``Logger``, ``LogLevel`` and the log references).

``fx.log(...)`` and ``fx.log_info(...)`` / ``log_debug`` / ... write an
entry to every logger in ``CurrentLoggers``, unless ``MinimumLogLevel`` is
above its level::

    yield from fx.log_info("user signed in", user_id)

    program.pipe(fx.provide(logger.layer([logger.console_json])))
    program.pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.DEBUG))

``eff.annotate_logs("request", rid)``, ``eff.with_log_span("db")`` and
``fx.annotate_logs_scoped(...)`` add context to the entries;
``logger.to_logging("app")`` hands them to the standard library's
``logging``.
"""

from pyfect.logger._console import console_pretty, default_date_format, default_logger
from pyfect.logger._formats import (
    StructuredLog,
    console_json,
    console_logfmt,
    console_structured,
    format_json,
    format_logfmt,
    format_simple,
    format_structured,
)
from pyfect.logger._layer import layer
from pyfect.logger._level import LogLevel, Severity
from pyfect.logger._log import (
    annotate_logs_scoped,
    log,
    log_debug,
    log_error,
    log_fatal,
    log_info,
    log_trace,
    log_warning,
    log_with_level,
)
from pyfect.logger._model import Logger, LogSpan, Options
from pyfect.logger._refs import (
    CurrentLogAnnotations,
    CurrentLoggers,
    CurrentLogLevel,
    CurrentLogSpans,
    LogToStderr,
    MinimumLogLevel,
    UnhandledLogLevel,
)
from pyfect.logger._stdlib import to_logging
from pyfect.logger._tracer import tracer_logger

__all__ = [
    "CurrentLogAnnotations",
    "CurrentLogLevel",
    "CurrentLogSpans",
    "CurrentLoggers",
    "LogLevel",
    "LogSpan",
    "LogToStderr",
    "Logger",
    "MinimumLogLevel",
    "Options",
    "Severity",
    "StructuredLog",
    "UnhandledLogLevel",
    "annotate_logs_scoped",
    "console_json",
    "console_logfmt",
    "console_pretty",
    "console_structured",
    "default_date_format",
    "default_logger",
    "format_json",
    "format_logfmt",
    "format_simple",
    "format_structured",
    "layer",
    "log",
    "log_debug",
    "log_error",
    "log_fatal",
    "log_info",
    "log_trace",
    "log_warning",
    "log_with_level",
    "to_logging",
    "tracer_logger",
]
