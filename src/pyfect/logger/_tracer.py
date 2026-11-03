"""``tracer_logger``: logs recorded as events of the current span."""

from __future__ import annotations

from pyfect.clock import Clock
from pyfect.logger._model import Logger, Options
from pyfect.logger._refs import CurrentLogAnnotations
from pyfect.logger._text import to_string_unknown
from pyfect.tracer._model import Ended, ExternalSpan
from pyfect.tracer._refs import ParentSpan


def _event_name(message: tuple[object, ...]) -> str:
    """Effect's ``toStringUnknown`` of the message (its one item, if it has
    one): a string as it is, anything else as indented JSON."""
    return to_string_unknown(message[0] if len(message) == 1 else list(message))


def _record(options: Options) -> None:
    fiber = options.fiber
    span = fiber.get_ref(ParentSpan)
    if span is None or isinstance(span, ExternalSpan) or isinstance(span.status, Ended):
        return
    attributes: dict[str, object] = dict(fiber.get_ref(CurrentLogAnnotations))
    attributes["effect.fiberId"] = fiber.id
    attributes["effect.logLevel"] = str(options.log_level).upper()
    if options.cause.reasons:
        attributes["effect.cause"] = options.cause.pretty()
    span.event(_event_name(options.message), fiber.get_ref(Clock).now_nanos_unsafe(), attributes)


tracer_logger: Logger[None] = Logger(_record)
"""Records each log as an event of the current span (unless it is
external or has ended), with the log annotations, the fiber id, the level
and the cause as attributes. One of the default loggers."""
