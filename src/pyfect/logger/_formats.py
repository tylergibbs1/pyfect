"""Loggers that render an entry: ``format_simple`` and ``format_logfmt``
(``key=value`` lines), ``format_structured`` (a dict) and ``format_json``,
plus ``console_*`` loggers writing them to the console."""

from __future__ import annotations

from collections.abc import Callable
from typing import NotRequired, TypedDict

from pyfect.logger._model import Logger, Options
from pyfect.logger._refs import CurrentLogAnnotations, CurrentLogSpans
from pyfect.logger._text import (
    escape_double_quotes,
    format_label,
    format_log_span,
    format_unknown,
    is_text_only,
    iso_millis,
    json_quote_line,
    json_text,
    structured_message,
)


def _key_values(quote: Callable[[str], str]) -> Callable[[Options], str]:
    def text(value: object) -> str:
        return value if isinstance(value, str) else format_unknown(value)

    def pair(label: str, value: str) -> str:
        return f"{format_label(label)}={value if is_text_only(value) else quote(value)}"

    def render(options: Options) -> str:
        fiber = options.fiber
        parts = [
            pair("timestamp", iso_millis(options.date)),
            pair("level", str(options.log_level).upper()),
            pair("fiber", f"#{fiber.id}"),
        ]
        parts.extend(pair("message", text(m)) for m in options.message)
        if options.cause.reasons:
            parts.append(pair("cause", options.cause.pretty()))
        now = options.millis
        parts.extend(format_log_span(span, now) for span in fiber.get_ref(CurrentLogSpans))
        parts.extend(
            pair(label, text(value))
            for label, value in fiber.get_ref(CurrentLogAnnotations).items()
        )
        return " ".join(parts)

    return render


format_simple: Logger[str] = Logger(_key_values(escape_double_quotes))
"""``key=value`` pairs; values with spaces, ``=`` or ``"`` are quoted."""

format_logfmt: Logger[str] = Logger(_key_values(json_quote_line))
"""The logfmt format: ``key=value`` pairs, values that need it quoted as
JSON strings."""


class StructuredLog(TypedDict):
    """An entry as ``format_structured`` gives it; the keys are Effect's.
    ``message`` is the item when one was logged, else the list of them;
    ``cause`` is there only when a cause was logged."""

    message: object
    level: str
    timestamp: str
    cause: NotRequired[str]
    annotations: dict[str, object]
    spans: dict[str, int]
    fiberId: str


def _structured(options: Options) -> StructuredLog:
    fiber = options.fiber
    now = options.millis
    items = options.message
    log: StructuredLog = {
        "message": (
            structured_message(items[0])
            if len(items) == 1
            else [structured_message(m) for m in items]
        ),
        "level": str(options.log_level).upper(),
        "timestamp": iso_millis(options.date),
        "annotations": {
            k: structured_message(v) for k, v in fiber.get_ref(CurrentLogAnnotations).items()
        },
        "spans": {span.label: now - span.start for span in fiber.get_ref(CurrentLogSpans)},
        "fiberId": f"#{fiber.id}",
    }
    if options.cause.reasons:
        log["cause"] = options.cause.pretty()
    return log


format_structured: Logger[StructuredLog] = Logger(_structured)
format_json: Logger[str] = format_structured.map(json_text)
"""``format_structured`` as one line of JSON."""

console_logfmt: Logger[None] = format_logfmt.with_console_log()
console_structured: Logger[None] = format_structured.with_console_log()
console_json: Logger[None] = format_json.with_console_log()
