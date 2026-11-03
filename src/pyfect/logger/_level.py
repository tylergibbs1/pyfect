"""``LogLevel``: Effect's eight levels as an ``IntEnum``.

The severities use the standard library's numbers (``logging.DEBUG`` is
``LogLevel.DEBUG``), with ``TRACE`` at 5 below them. ``ALL`` and ``NONE``
are thresholds only: nothing is logged at them, which ``Severity`` says.
Levels order as Effect's do, so compare them with ``<`` and ``>``. A level
prints as Effect's ``LogLevel`` string: ``str(LogLevel.INFO)`` is ``"Info"``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pyfect._core import Effect

_MAX_SAFE_INTEGER = 2**53 - 1


class LogLevel(IntEnum):
    """Effect's log levels, in Effect's order (``values``)."""

    ALL = -_MAX_SAFE_INTEGER
    FATAL = 50
    ERROR = 40
    WARN = 30
    INFO = 20
    DEBUG = 10
    TRACE = 5
    NONE = _MAX_SAFE_INTEGER

    def __str__(self) -> str:
        """Effect's name for the level: ``"Info"``, ``"Warn"``, ``"All"``."""
        return self.name.capitalize()

    def __format__(self, format_spec: str) -> str:
        return format(str(self), format_spec)

    def is_enabled(self) -> Effect[bool]:
        """Whether a log at this level passes the current
        ``MinimumLogLevel``."""
        from pyfect._core import _Succeed, _WithFiber
        from pyfect.logger._refs import MinimumLogLevel

        return _WithFiber(lambda fiber: _Succeed(fiber.get_ref(MinimumLogLevel) <= self))


type Severity = Literal[
    LogLevel.FATAL, LogLevel.ERROR, LogLevel.WARN, LogLevel.INFO, LogLevel.DEBUG, LogLevel.TRACE
]
"""A level a log can be written at: every level but ``ALL`` and ``NONE``."""
