"""Exporting spans over OTLP/HTTP (Effect's ``OtlpTracer``): a ``Tracer``
whose spans are posted to a traces endpoint when they end, with their ids,
parent, attributes, events, links, timing, kind and status."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, Never, NotRequired, Protocol, TypedDict

from pyfect import config
from pyfect import layer as _layer
from pyfect._fiber import Fiber
from pyfect._tracer_ref import CurrentTracer
from pyfect.context import Context
from pyfect.duration import Input as DurationInput
from pyfect.effect import Effect, gen, succeed
from pyfect.exit import Exit, Success
from pyfect.http import headers as _headers
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.observability import _otlp_env as env
from pyfect.observability import otlp_exporter as exporter
from pyfect.observability._pretty import pretty_errors
from pyfect.observability.otlp_exporter import Compression, Flusher
from pyfect.observability.otlp_resource import (
    KeyValue,
    Resource,
    ResourceOptions,
    entries_to_attributes,
    from_options,
    instrumentation_scope,
)
from pyfect.observability.otlp_serialization import OtlpSerialization
from pyfect.scope import Scope
from pyfect.tracer import (
    AnySpan,
    Ended,
    ParentSpan,
    SpanKind,
    SpanLink,
    SpanRequest,
    SpanStatus,
    Started,
    Tracer,
)

__all__ = [
    "Event",
    "Link",
    "OtlpSpan",
    "ResourceSpan",
    "ScopeSpan",
    "SpanContextHook",
    "Status",
    "TraceData",
    "layer",
    "layer_from_config",
    "make",
]


class Status(TypedDict):
    code: Literal[0, 1, 2]
    """Unset, Ok or Error."""
    message: NotRequired[str]


class Event(TypedDict):
    name: str
    timeUnixNano: str
    droppedAttributesCount: int
    attributes: list[KeyValue]


class Link(TypedDict):
    traceId: str
    spanId: str
    attributes: list[KeyValue]
    droppedAttributesCount: int


class OtlpSpan(TypedDict):
    traceId: str
    spanId: str
    parentSpanId: NotRequired[str]
    name: str
    kind: int
    startTimeUnixNano: str
    endTimeUnixNano: str
    attributes: list[KeyValue]
    droppedAttributesCount: int
    events: list[Event]
    droppedEventsCount: int
    status: Status
    links: list[Link]
    droppedLinksCount: int


class _InstrumentationScope(TypedDict):
    name: str
    version: NotRequired[str]


class ScopeSpan(TypedDict):
    scope: _InstrumentationScope
    spans: list[OtlpSpan]
    schemaUrl: NotRequired[str]


class ResourceSpan(TypedDict):
    resource: Resource
    scopeSpans: list[ScopeSpan]
    schemaUrl: NotRequired[str]


class TraceData(TypedDict):
    """The body of a traces export."""

    resourceSpans: list[ResourceSpan]


class SpanContextHook(Protocol):
    """Runs one fiber step inside ``span``, the fiber's current span: call
    ``run()`` and return what it returns (Effect's ``context`` option)."""

    def __call__[T](self, run: Callable[[], T], span: AnySpan, /) -> T: ...


type _SpanEvent = tuple[str, int, Mapping[str, object] | None]

_SPAN_KINDS: dict[SpanKind, int] = {
    "internal": 1,
    "server": 2,
    "client": 3,
    "producer": 4,
    "consumer": 5,
}


def _hex_id(digits: int) -> str:
    return f"{random.getrandbits(digits * 4):0{digits}x}"


class _OtlpTracerSpan:
    """A span recorded in memory and exported once it ends (if sampled)."""

    __slots__ = (
        "_attributes",
        "_events",
        "_export",
        "_span_id",
        "_trace_id",
        "annotations",
        "kind",
        "links",
        "name",
        "parent",
        "sampled",
        "status",
    )

    def __init__(self, request: SpanRequest, export: Callable[[_OtlpTracerSpan], None]) -> None:
        self.name: str = request.name
        self.parent: AnySpan | None = request.parent
        self.annotations: Context = request.annotations
        self.links: list[SpanLink] = request.links
        self.kind: SpanKind = request.kind
        self.sampled: bool = request.sampled
        self.status: SpanStatus = Started(request.start_time)
        self._export = export
        self._trace_id: str | None = None
        self._span_id: str | None = None
        self._attributes: dict[str, object] | None = None
        self._events: list[_SpanEvent] | None = None

    def __repr__(self) -> str:
        return f"OtlpSpan({self.name!r})"

    @property
    def trace_id(self) -> str:
        if self._trace_id is None:
            self._trace_id = _hex_id(32) if self.parent is None else self.parent.trace_id
        return self._trace_id

    @property
    def span_id(self) -> str:
        if self._span_id is None:
            self._span_id = _hex_id(16)
        return self._span_id

    @property
    def attributes(self) -> dict[str, object]:
        if self._attributes is None:
            self._attributes = {}
        return self._attributes

    @property
    def events(self) -> list[_SpanEvent]:
        if self._events is None:
            self._events = []
        return self._events

    def end(self, end_time: int, exit: Exit[object, object], /) -> None:
        if isinstance(self.status, Ended):
            return
        self.status = Ended(self.status.start_time, end_time, exit)
        self._export(self)

    def attribute(self, key: str, value: object, /) -> None:
        if isinstance(self.status, Started):
            self.attributes[key] = value

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None:
        if isinstance(self.status, Started):
            self.events.append((name, start_time, attributes))

    def add_links(self, links: Sequence[SpanLink], /) -> None:
        if isinstance(self.status, Started):
            self.links.extend(links)


def _status_of(span: _OtlpTracerSpan, attributes: list[KeyValue], events: list[Event]) -> Status:
    status = span.status
    assert isinstance(status, Ended)
    exit = status.exit
    if isinstance(exit, Success):
        return {"code": 1}
    if exit.cause.has_interrupts_only:
        attributes.append({"key": "effect.fiber.interrupted", "value": {"boolValue": True}})
        return {"code": 0}
    errors = pretty_errors(exit.cause)
    events.extend(
        {
            "name": "exception",
            "timeUnixNano": str(status.end_time),
            "droppedAttributesCount": 0,
            "attributes": [
                {"key": "exception.type", "value": {"stringValue": error.name}},
                {"key": "exception.message", "value": {"stringValue": error.message}},
                {"key": "exception.stacktrace", "value": {"stringValue": error.stack}},
            ],
        }
        for error in errors
    )
    return {"code": 2, "message": errors[0].message} if errors else {"code": 1}


def _otlp_span(span: _OtlpTracerSpan) -> OtlpSpan:
    status = span.status
    assert isinstance(status, Ended)
    attributes = entries_to_attributes(span.attributes.items())
    events: list[Event] = [
        {
            "name": name,
            "timeUnixNano": str(start_time),
            "attributes": entries_to_attributes(event_attributes.items())
            if event_attributes
            else [],
            "droppedAttributesCount": 0,
        }
        for name, start_time, event_attributes in span.events
    ]
    otel_status = _status_of(span, attributes, events)
    links: list[Link] = [
        {
            "traceId": link.span.trace_id.rjust(32, "0"),
            "spanId": link.span.span_id,
            "attributes": entries_to_attributes(link.attributes.items()),
            "droppedAttributesCount": 0,
        }
        for link in span.links
    ]
    result: dict[str, Any] = {
        "traceId": span.trace_id.rjust(32, "0"),
        "spanId": span.span_id,
    }
    if span.parent is not None:
        result["parentSpanId"] = span.parent.span_id
    result.update(
        {
            "name": span.name,
            "kind": _SPAN_KINDS.get(span.kind, 0),
            "startTimeUnixNano": str(status.start_time),
            "endTimeUnixNano": str(status.end_time),
            "attributes": attributes,
            "droppedAttributesCount": 0,
            "events": events,
            "droppedEventsCount": 0,
            "status": otel_status,
            "links": links,
            "droppedLinksCount": 0,
        }
    )
    return result  # pyright: ignore[reportReturnType]


def _context_hook(hook: SpanContextHook) -> Any:
    def run_in_span[T](run: Callable[[], T], fiber: Fiber[Any, Any], /) -> T:
        span = fiber.get_ref(ParentSpan)
        return run() if span is None else hook(run, span)

    return run_in_span


def make(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: DurationInput | None = None,
    max_batch_size: int | None = None,
    context: SpanContextHook | None = None,
    shutdown_timeout: DurationInput | None = None,
) -> Effect[Tracer, Never, Flusher | OtlpSerialization | HttpClient | Scope]:
    """A tracer exporting each sampled span to ``url`` when it ends, in
    batches of ``max_batch_size`` (1000) every ``export_interval`` (5
    seconds), flushed for at most ``shutdown_timeout`` (3 seconds) when the
    scope closes. ``context`` runs every step of a fiber inside a span
    (an OpenTelemetry-style bridge)."""

    @gen
    def build():
        otel_resource = yield from from_options(resource)
        serialization = yield from OtlpSerialization()
        scope = instrumentation_scope()

        def body(spans: list[Any]) -> tuple[Any, Effect[None]]:
            data: TraceData = {
                "resourceSpans": [
                    {"resource": otel_resource, "scopeSpans": [{"scope": scope, "spans": spans}]}
                ]
            }
            return serialization.traces(data), succeed(None)

        made = yield from exporter.make(
            label="OtlpTracer",
            url=url,
            headers=headers,
            compression=compression,
            export_interval="5 seconds" if export_interval is None else export_interval,
            max_batch_size=1000 if max_batch_size is None else max_batch_size,
            body=body,
            shutdown_timeout="3 seconds" if shutdown_timeout is None else shutdown_timeout,
        )

        def export(span: _OtlpTracerSpan) -> None:
            if span.sampled:
                made.push(_otlp_span(span))

        return Tracer(
            lambda request: _OtlpTracerSpan(request, export),
            None if context is None else _context_hook(context),
        )

    return build


def layer(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: DurationInput | None = None,
    max_batch_size: int | None = None,
    context: SpanContextHook | None = None,
    shutdown_timeout: DurationInput | None = None,
) -> Layer[Flusher, Never, OtlpSerialization | HttpClient]:
    """Installs ``make``'s tracer, with the shared ``layer_flusher``."""
    tracer = make(
        url=url,
        resource=resource,
        headers=headers,
        compression=compression,
        export_interval=export_interval,
        max_batch_size=max_batch_size,
        context=context,
        shutdown_timeout=shutdown_timeout,
    )
    return _layer.effect(CurrentTracer, tracer).pipe(_layer.provide_merge(exporter.layer_flusher))


def layer_from_config(
    *,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    context: SpanContextHook | None = None,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """``layer`` configured from the OpenTelemetry environment: nothing
    but the flusher unless ``OTEL_TRACES_EXPORTER`` lists ``otlp``, an
    endpoint is set and ``OTEL_SDK_DISABLED`` is not true. Reads the
    compression, ``OTEL_EXPORTER_OTLP_(TRACES_)TIMEOUT`` /
    ``OTEL_BSP_EXPORT_TIMEOUT`` (shutdown), ``OTEL_BSP_SCHEDULE_DELAY``
    and ``OTEL_BSP_MAX_EXPORT_BATCH_SIZE``. Invalid configuration is a
    defect."""

    @gen
    def build():
        disabled = yield from config.boolean("OTEL_SDK_DISABLED").with_default(False)
        endpoint = yield from env.endpoint("TRACES")
        exporters = yield from env.exporters("TRACES")
        if disabled or endpoint is None or "otlp" not in exporters:
            return exporter.layer_flusher
        compression = yield from env.compression("TRACES")
        base_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_TIMEOUT")
        traces_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT")
        export_timeout = yield from env.millis("OTEL_BSP_EXPORT_TIMEOUT")
        schedule_delay = yield from env.millis("OTEL_BSP_SCHEDULE_DELAY")
        max_batch_size = yield from config.integer("OTEL_BSP_MAX_EXPORT_BATCH_SIZE").with_default(
            None
        )
        signal_headers = headers if headers is not None else (yield from env.headers("TRACES"))
        return layer(
            url=str(endpoint),
            resource=resource,
            headers=signal_headers,
            compression=compression,
            export_interval=schedule_delay,
            max_batch_size=max_batch_size,
            context=context,
            shutdown_timeout=env.first_of(traces_timeout, base_timeout, export_timeout),
        )

    return _layer.unwrap(build.or_die())
