"""The console loggers: ``default_logger`` and ``console_pretty``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime

from pyfect.console import CurrentConsole
from pyfect.logger._level import LogLevel
from pyfect.logger._model import Logger, Options
from pyfect.logger._refs import CurrentLogAnnotations, CurrentLogSpans, LogToStderr
from pyfect.logger._text import format_log_span, structured_message


def default_date_format(when: datetime) -> str:
    """Local wall-clock time, ``HH:MM:SS.mmm``."""
    local = when.astimezone()
    return local.strftime("%H:%M:%S.") + f"{local.microsecond // 1000:03d}"


def _spans(options: Options) -> str:
    now = options.millis
    return "".join(
        " " + format_log_span(span, now) for span in options.fiber.get_ref(CurrentLogSpans)
    )


def _default(options: Options) -> None:
    fiber = options.fiber
    items = list(options.message)
    if options.cause.reasons:
        items.append(options.cause.pretty())
    annotations = fiber.get_ref(CurrentLogAnnotations)
    if annotations:
        items.append(dict(annotations))
    console = fiber.get_ref(CurrentConsole)
    write = console.error if fiber.get_ref(LogToStderr) else console.log
    header = f"[{default_date_format(options.date)}] {options.log_level.name} (#{fiber.id})"
    write(f"{header}{_spans(options)}:", *items)


default_logger: Logger[None] = Logger(_default)
"""Effect's default logger: ``[HH:MM:SS.mmm] LEVEL (#fiber) spans:`` and
then the logged items, the cause and the annotations, on the console."""


_COLORS = {
    "bold": "1",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "cyan": "36",
    "white": "37",
    "gray": "90",
    "black": "30",
    "bg_bright_red": "101",
}
_LEVEL_COLORS: dict[LogLevel, tuple[str, ...]] = {
    LogLevel.ALL: (),
    LogLevel.NONE: (),
    LogLevel.TRACE: ("gray",),
    LogLevel.DEBUG: ("blue",),
    LogLevel.INFO: ("green",),
    LogLevel.WARN: ("yellow",),
    LogLevel.ERROR: ("red",),
    LogLevel.FATAL: ("bg_bright_red", "black"),
}


def _paint(text: str, *colors: str) -> str:
    return "".join(f"\x1b[{_COLORS[c]}m" for c in colors) + text + "\x1b[0m"


def _plain(text: str, *_colors: str) -> str:
    return text


def console_pretty(
    *, colors: bool | None = None, format_date: Callable[[datetime], str] = default_date_format
) -> Logger[None]:
    """A readable multi-line logger for terminals: a colored header with
    the first message, then the cause, the other items and the
    annotations, indented in a console group. ``colors`` defaults to
    whether stdout is a terminal."""
    show = sys.stdout.isatty() if colors is None else colors
    color = _paint if show else _plain

    def log(options: Options) -> None:
        fiber = options.fiber
        console = fiber.get_ref(CurrentConsole)
        write = console.error if fiber.get_ref(LogToStderr) else console.log
        level = options.log_level
        items = list(options.message)
        first_line = (
            color(f"[{format_date(options.date)}]", "white")
            + f" {color(level.name, *_LEVEL_COLORS[level])}"
            + f" (#{fiber.id}){_spans(options)}:"
        )
        if items and isinstance(first := structured_message(items[0]), str):
            first_line += " " + color(first, "bold", "cyan")
            items.pop(0)
        write(first_line)
        console.group()
        try:
            if options.cause.reasons:
                write(options.cause.pretty())
            for item in items:
                write(item)
            for key, value in fiber.get_ref(CurrentLogAnnotations).items():
                write(color(f"{key}:", "bold", "white"), value)
        finally:
            console.group_end()

    return Logger(log)
