"""``to_logging``: a logger that hands entries to the standard library's
``logging``."""

from __future__ import annotations

import logging

from pyfect.logger._level import LogLevel
from pyfect.logger._model import Logger, Options
from pyfect.logger._refs import CurrentLogAnnotations, CurrentLogSpans


def to_logging(target: str | logging.Logger = "pyfect") -> Logger[None]:
    """A logger writing each entry to ``target`` (a ``logging.Logger`` or
    the name of one) as a ``LogRecord``, at the matching standard level
    (``TRACE`` is 5, named ``"TRACE"``). The record's message is the logged
    items joined by spaces; its time is the entry's (the fiber's
    ``Clock``), and a logged cause becomes its ``exc_info``. It also
    carries ``fiber_id`` (``"#12"``), ``log_annotations`` (a dict),
    ``log_spans`` (label to elapsed milliseconds) and ``cause``. The
    target's own level and handlers then apply as usual."""
    std = target if isinstance(target, logging.Logger) else logging.getLogger(target)
    if logging.getLevelName(LogLevel.TRACE) == f"Level {int(LogLevel.TRACE)}":
        logging.addLevelName(LogLevel.TRACE, "TRACE")

    def emit(options: Options) -> None:
        level = int(options.log_level)
        if not std.isEnabledFor(level):
            return
        fiber = options.fiber
        cause = options.cause
        error = cause.squash() if cause.reasons else None
        now = options.millis
        record = std.makeRecord(
            std.name,
            level,
            "(pyfect)",
            0,
            " ".join(["%s"] * len(options.message)),
            options.message,
            None if error is None else (type(error), error, error.__traceback__),
            extra={
                "fiber_id": f"#{fiber.id}",
                "log_annotations": dict(fiber.get_ref(CurrentLogAnnotations)),
                "log_spans": {s.label: now - s.start for s in fiber.get_ref(CurrentLogSpans)},
                "cause": cause,
            },
        )
        record.created = options.date.timestamp()
        record.msecs = options.date.microsecond // 1000
        std.handle(record)

    return Logger(emit)
