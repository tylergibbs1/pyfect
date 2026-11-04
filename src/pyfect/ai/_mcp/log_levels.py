"""MCP log levels against Effect's (Effect's ``mcpLogLevels``): which
notifications a client's threshold lets through, and the ``CurrentLogLevel``
a handler runs at."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeIs, get_args

from pyfect.ai.mcp_schema import LoggingLevel
from pyfect.logger import LogLevel, Severity

REQUEST_LOG_LEVEL_META = "io.modelcontextprotocol/logLevel"

LEVELS: tuple[LoggingLevel, ...] = get_args(LoggingLevel.__value__)

_EFFECT_LEVELS: Mapping[LoggingLevel, Severity] = {
    "debug": LogLevel.DEBUG,
    "info": LogLevel.INFO,
    "notice": LogLevel.INFO,
    "warning": LogLevel.WARN,
    "error": LogLevel.ERROR,
    "critical": LogLevel.FATAL,
    "alert": LogLevel.FATAL,
    "emergency": LogLevel.FATAL,
}


def is_logging_level(value: object) -> TypeIs[LoggingLevel]:
    return value in _EFFECT_LEVELS


def effect_level(level: LoggingLevel) -> Severity:
    return _EFFECT_LEVELS[level]


def at_least(level: LoggingLevel, minimum: LoggingLevel) -> bool:
    """``level`` is ``minimum`` or above in MCP's order."""
    return LEVELS.index(level) >= LEVELS.index(minimum)


def request_log_level(metadata: Mapping[str, Any]) -> object:
    """The level a 2026-07-28 request's ``_meta`` names (unchecked)."""
    return metadata.get(REQUEST_LOG_LEVEL_META)


def session_delivers(level: object, threshold: LoggingLevel | Severity) -> bool:
    """Whether a session at ``threshold`` (an MCP level once the client set
    one, else the server's Effect level) gets a log at ``level``; a log of an
    unknown level is never one Effect sends."""
    if not is_logging_level(level):
        return True
    if isinstance(threshold, str):
        return at_least(level, threshold)
    return effect_level(level) >= threshold
