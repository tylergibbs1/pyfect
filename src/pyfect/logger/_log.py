"""The logging effects: ``log`` and its levels, and
``annotate_logs_scoped``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Never, overload

from pyfect._context_effects import update_service_scoped
from pyfect._core import Effect, _Succeed, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cause import Cause, Reason
from pyfect.clock import Clock
from pyfect.logger._level import LogLevel, Severity
from pyfect.logger._model import Options
from pyfect.logger._refs import (
    CurrentLogAnnotations,
    CurrentLoggers,
    CurrentLogLevel,
    MinimumLogLevel,
    UnhandledLogLevel,
)
from pyfect.scope import Scope

_VOID: Effect[None] = _Succeed(None)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def log_with_level(level: Severity | None, *message: object) -> Effect[None]:
    """Log ``message`` at ``level`` (``None``: the ``CurrentLogLevel``) to
    every logger in ``CurrentLoggers``, unless ``MinimumLogLevel`` is above
    it. ``Cause`` items are taken out of the message and logged as its
    cause."""
    reasons: list[Reason[object]] = []
    items: list[object] = []
    for item in message:
        if isinstance(item, Cause):
            reasons.extend(item.reasons)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        else:
            items.append(item)
    cause: Cause[object] = Cause(tuple(reasons))
    logged = tuple(items)

    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        at = fiber.get_ref(CurrentLogLevel) if level is None else level
        if fiber.get_ref(MinimumLogLevel) > at:
            return _VOID
        loggers = fiber.get_ref(CurrentLoggers)
        if loggers:
            nanos = fiber.get_ref(Clock).now_nanos_unsafe()
            date = _EPOCH + timedelta(microseconds=nanos // 1000)
            options = Options(logged, at, cause, fiber, date)
            for logger in loggers:
                logger.log(options)
        return _VOID

    return _WithFiber(body)


def log(*message: object) -> Effect[None]:
    """Log at the ``CurrentLogLevel`` (``INFO`` unless provided)."""
    return log_with_level(None, *message)


def log_fatal(*message: object) -> Effect[None]:
    """Log ``message`` at ``FATAL``."""
    return log_with_level(LogLevel.FATAL, *message)


def log_error(*message: object) -> Effect[None]:
    """Log ``message`` at ``ERROR``."""
    return log_with_level(LogLevel.ERROR, *message)


def log_warning(*message: object) -> Effect[None]:
    """Log ``message`` at ``WARN``."""
    return log_with_level(LogLevel.WARN, *message)


def log_info(*message: object) -> Effect[None]:
    """Log ``message`` at ``INFO``."""
    return log_with_level(LogLevel.INFO, *message)


def log_debug(*message: object) -> Effect[None]:
    """Log ``message`` at ``DEBUG``."""
    return log_with_level(LogLevel.DEBUG, *message)


def log_trace(*message: object) -> Effect[None]:
    """Log ``message`` at ``TRACE``."""
    return log_with_level(LogLevel.TRACE, *message)


def log_unhandled(message: str, cause: Cause[object]) -> Effect[None]:
    """Log a failure nobody can handle at the ``UnhandledLogLevel``."""

    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        level = fiber.get_ref(UnhandledLogLevel)
        return _VOID if level is None else log_with_level(level, message, cause)

    return _WithFiber(body)


_MISSING = object()


def _same(a: object, b: object) -> bool:
    """JavaScript's ``===`` or ``Object.is``: the same object, or equal
    strings, numbers or bytes (NaN equals NaN)."""
    if a is b:
        return True
    if type(a) is not type(b) or not isinstance(a, (str, int, float, bytes)):
        return False
    return a == b or (isinstance(a, float) and a != a and b != b)  # noqa: PLR0124


@overload
def annotate_logs_scoped(key: str, value: object, /) -> Effect[None, Never, Scope]: ...
@overload
def annotate_logs_scoped(values: Mapping[str, object], /) -> Effect[None, Never, Scope]: ...
def annotate_logs_scoped(
    key_or_values: str | Mapping[str, object], value: object = _MISSING, /
) -> Effect[None, Never, Scope]:
    """Add log annotations for the rest of the current fiber's region,
    until the current scope closes. Closing it restores each key's earlier
    value (or removes the key), unless the key was set again since."""
    added = {key_or_values: value} if isinstance(key_or_values, str) else dict(key_or_values)

    def add(annotations: Mapping[str, object]) -> Mapping[str, object]:
        return {**annotations, **added}

    def restore(
        before: Mapping[str, object], _updated: Mapping[str, object], now: Mapping[str, object]
    ) -> Mapping[str, object]:
        restored = dict(now)
        for k, v in added.items():
            if not _same(now.get(k, _MISSING), v):
                continue
            if k in before:
                restored[k] = before[k]
            else:
                del restored[k]
        return restored

    return update_service_scoped(CurrentLogAnnotations, add, reset=restore)
