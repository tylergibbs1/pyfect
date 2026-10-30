"""An OpenTelemetry ``Span`` over a pyfect span the bridge did not make
(Effect's ``makeOtelSpan``), for ``current_otel_span``."""

from __future__ import annotations

import traceback
from collections.abc import Mapping

from opentelemetry import trace
from opentelemetry.trace import SpanContext, Status, StatusCode, TraceFlags
from opentelemetry.util import types

from pyfect.clock import ClockService
from pyfect.exit import Exit, Success, die
from pyfect.otel._span import external_span_of, hex_id
from pyfect.tracer import Span, SpanLink


class EffectSpanView(trace.Span):
    """Writes through to ``span``: attributes, events, links and the end,
    with the exit the last ``set_status`` chose (an error status ends it
    with a defect). Times default to ``clock``'s now."""

    def __init__(self, span: Span, clock: ClockService) -> None:
        self._span = span
        self._clock = clock
        self._exit: Exit[object, object] = Success(None)
        self._context = SpanContext(
            hex_id(span.trace_id),
            hex_id(span.span_id),
            False,
            TraceFlags(TraceFlags.SAMPLED if span.sampled else TraceFlags.DEFAULT),
        )

    def _time(self, nanos: int | None) -> int:
        return self._clock.now_nanos_unsafe() if nanos is None else nanos

    def get_span_context(self) -> SpanContext:
        return self._context

    def set_attribute(self, key: str, value: types.AttributeValue) -> None:
        self._span.attribute(key, value)

    def set_attributes(self, attributes: Mapping[str, types.AttributeValue]) -> None:
        for key, value in attributes.items():
            self._span.attribute(key, value)

    def add_event(
        self, name: str, attributes: types.Attributes = None, timestamp: int | None = None
    ) -> None:
        self._span.event(name, self._time(timestamp), attributes)

    def add_link(self, context: SpanContext, attributes: types.Attributes = None) -> None:
        self._span.add_links([_link(context, attributes)])

    def update_name(self, name: str) -> None:
        pass

    def is_recording(self) -> bool:
        return True

    def set_status(self, status: Status | StatusCode, description: str | None = None) -> None:
        code = status.status_code if isinstance(status, Status) else status
        if code is StatusCode.ERROR:
            message = status.description if isinstance(status, Status) else description
            self._exit = die(Exception(message or "Unknown error"))
        else:
            self._exit = Success(None)

    def end(self, end_time: int | None = None) -> None:
        self._span.end(self._time(end_time), self._exit)

    def record_exception(
        self,
        exception: BaseException,
        attributes: types.Attributes = None,
        timestamp: int | None = None,
        escaped: bool = False,
    ) -> None:
        self._span.event(
            str(exception),
            self._time(timestamp),
            {
                "exception.type": type(exception).__name__,
                "exception.message": str(exception),
                "exception.stacktrace": "".join(traceback.format_exception(exception)),
            },
        )


def _link(context: SpanContext, attributes: types.Attributes) -> SpanLink:
    return SpanLink(external_span_of(context), dict(attributes or {}))
