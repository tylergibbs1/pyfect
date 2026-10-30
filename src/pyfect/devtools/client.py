"""The client side of the Effect DevTools (Effect's
``devtools/DevToolsClient``).

``make`` connects over the ``Socket``: it sends a ``Ping`` every 3 seconds,
answers ``MetricsRequest``\\s with a ``MetricsSnapshot``, and reconnects
every second while the socket fails. ``layer_tracer`` installs a tracer
that reports every span when it starts and ends, and its events.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Never

from pyfect._core import Effect
from pyfect._tracer_ref import CurrentTracer
from pyfect.context import Context, Tag
from pyfect.deferred import Deferred
from pyfect.devtools import schema as D
from pyfect.effect import context, gen, succeed, suspend, sync
from pyfect.encoding.ndjson import NdjsonError, duplex_schema_string
from pyfect.exit import Exit
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.logger._log import log_debug
from pyfect.metric._snapshot import snapshot_unsafe
from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    Snapshot,
    SummaryState,
)
from pyfect.queue import Queue
from pyfect.schedule import spaced
from pyfect.schema import SchemaError
from pyfect.scope import Scope, acquire_release, add_finalizer
from pyfect.socket import Socket, SocketChannel, SocketService, Writer, to_channel_string
from pyfect.socket import make as make_socket
from pyfect.stream import from_queue
from pyfect.tracer import Ended, ExternalSpan, Span, SpanKind, SpanLink, SpanStatus, Tracer
from pyfect.tracer._model import SpanRequest

__all__ = [
    "DevToolsClient",
    "DevToolsClientService",
    "layer",
    "layer_tracer",
    "make",
    "make_tracer",
]


class DevToolsClientService:
    """Sends span snapshots and events to the DevTools."""

    __slots__ = ("_requests",)

    def __init__(self, requests: Queue[D.Request, Any]) -> None:
        self._requests = requests

    def send_unsafe(self, request: D.Span | D.SpanEvent) -> None:
        self._requests.offer_unsafe(request)


class DevToolsClient(Tag[DevToolsClientService], key="effect/devtools/DevToolsClient"):
    """The DevTools connection."""


def _metric(snapshot: Snapshot) -> D.Metric:
    state = snapshot.state
    base: dict[str, Any] = {
        "id": snapshot.id,
        "description": snapshot.description,
        "attributes": None if snapshot.attributes is None else dict(snapshot.attributes),
    }
    match state:
        case CounterState():
            data: Any = {"count": state.count, "incremental": state.incremental}
        case GaugeState():
            data = {"value": state.value}
        case FrequencyState():
            data = {"occurrences": dict(state.occurrences)}
        case HistogramState():
            data = {
                "buckets": state.buckets,
                "count": state.count,
                "min": state.min,
                "max": state.max,
                "sum": state.sum,
            }
        case SummaryState():
            data = {
                "quantiles": state.quantiles,
                "count": state.count,
                "min": state.min,
                "max": state.max,
                "sum": state.sum,
            }
    return {**base, "type": snapshot.type, "state": data}  # pyright: ignore[reportReturnType]


def _metrics_snapshot(services: Context[Any]) -> D.MetricsSnapshot:
    return {"_tag": "MetricsSnapshot", "metrics": tuple(map(_metric, snapshot_unsafe(services)))}


def _make():
    socket = yield from Socket()
    services = yield from context()
    requests = yield from Queue[D.Request, Any].unbounded()
    yield from requests.offer({"_tag": "Ping"})
    connected = Deferred[None]()
    state = {"closing": False, "writable": False}

    def set_writable(value: bool) -> Effect[None]:
        return sync(lambda: state.__setitem__("writable", value))

    # Tracks whether the current connection has a writer that can drain
    # the queue on shutdown.
    def writer() -> Effect[Writer, Never, Scope]:
        return socket.writer.tap(
            lambda _: acquire_release(set_writable(True), lambda _a, _e: set_writable(False))
        )

    transport: SocketService = make_socket(socket.reader, suspend(writer))
    offer_metrics = sync(lambda: requests.offer_unsafe(_metrics_snapshot(services)))

    def handle(response: D.Response) -> Effect[None]:
        if response["_tag"] == "MetricsRequest":
            return offer_metrics.as_void()
        return succeed(None)

    def log_failure(error: object) -> Effect[None]:
        return log_debug("DevTools connection failed", error)

    socket_channel: SocketChannel[str, NdjsonError | SchemaError] = to_channel_string(transport)
    channel = duplex_schema_string(
        socket_channel,
        input_schema=D.REQUEST_CODEC,
        output_schema=D.RESPONSE_CODEC,
    )
    # Each run closes its stream scope, the socket's reader and writer
    # with it, before retrying with a fresh connection and the same queue.
    connection = (
        from_queue(requests)
        .pipe_through_channel(channel)
        .on_first(lambda _: connected.succeed(None))
        .run_for_each(handle)
        .tap_error(log_failure)
        .retry(schedule=spaced(1), while_=lambda _: not state["closing"])
    )
    fiber = yield from connection.fork_daemon()

    def close(_: object) -> Effect[None]:
        def body():
            state["closing"] = True
            yield from offer_metrics
            yield from requests.interrupt()
            # A ready writer drains the queue before stopping; a failed or
            # pending connection cannot see the interruption, so stop it.
            if state["writable"]:
                yield from fiber.await_exit()
            else:
                yield from fiber.interrupt()

        return gen(body)

    yield from add_finalizer(close)
    yield from (suspend(lambda: requests.offer({"_tag": "Ping"})).delay(3).forever().fork_scoped())
    yield from connected.wait().timeout_option(1)
    return DevToolsClientService(requests)


make: Effect[DevToolsClientService, Never, Scope | Socket] = gen(_make).annotate_logs(
    {"module": "DevTools", "service": "Client"}
)
"""A DevTools connection over the ``Socket``."""

layer: Layer[DevToolsClient, Never, Socket] = layer_effect(DevToolsClient, make)


def _parent(span: Any) -> Any:
    if span is None:
        return None
    if isinstance(span, ExternalSpan):
        return {
            "_tag": "ExternalSpan",
            "spanId": span.span_id,
            "traceId": span.trace_id,
            "sampled": span.sampled,
        }
    return _snapshot(span)


def _status(status: SpanStatus) -> D.SpanStatus:
    if isinstance(status, Ended):
        return {
            "_tag": "Ended",
            "startTime": status.start_time,
            "endTime": status.end_time,
            "exit": status.exit.as_void(),
        }
    return {"_tag": "Started", "startTime": status.start_time}


def _snapshot(span: Span) -> D.Span:
    from pyfect.option import Some

    parent = _parent(span.parent)
    return {
        "_tag": "Span",
        "spanId": span.span_id,
        "traceId": span.trace_id,
        "name": span.name,
        "sampled": span.sampled,
        "attributes": dict(span.attributes),
        "status": _status(span.status),
        "parent": None if parent is None else Some(parent),
    }


class _DevToolsSpan:
    """A span of the wrapped tracer that reports to the DevTools."""

    __slots__ = ("_client", "_span")

    def __init__(self, span: Span, client: DevToolsClientService) -> None:
        self._span = span
        self._client = client

    @property
    def name(self) -> str:
        return self._span.name

    @property
    def span_id(self) -> str:
        return self._span.span_id

    @property
    def trace_id(self) -> str:
        return self._span.trace_id

    @property
    def parent(self) -> Any:
        return self._span.parent

    @property
    def annotations(self) -> Context[Any]:
        return self._span.annotations

    @property
    def status(self) -> SpanStatus:
        return self._span.status

    @property
    def attributes(self) -> Mapping[str, object]:
        return self._span.attributes

    @property
    def links(self) -> Sequence[SpanLink]:
        return self._span.links

    @property
    def sampled(self) -> bool:
        return self._span.sampled

    @property
    def kind(self) -> SpanKind:
        return self._span.kind

    def end(self, end_time: int, exit: Exit[object, object], /) -> None:
        if isinstance(self._span.status, Ended):
            return
        self._span.end(end_time, exit)
        self._client.send_unsafe(_snapshot(self))

    def attribute(self, key: str, value: object, /) -> None:
        self._span.attribute(key, value)

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None:
        if isinstance(self._span.status, Ended):
            return
        self._client.send_unsafe(
            {
                "_tag": "SpanEvent",
                "traceId": self.trace_id,
                "spanId": self.span_id,
                "name": name,
                "startTime": start_time,
                "attributes": None if attributes is None else dict(attributes),
            }
        )
        self._span.event(name, start_time, attributes)

    def add_links(self, links: Sequence[SpanLink], /) -> None:
        self._span.add_links(links)


def _make_tracer():
    client = yield from DevToolsClient()
    current = yield from CurrentTracer()

    def span(request: SpanRequest) -> Span:
        wrapped = _DevToolsSpan(current.span(request), client)
        client.send_unsafe(_snapshot(wrapped))
        return wrapped

    return Tracer.make(span, current.context)


make_tracer: Effect[Tracer, Never, DevToolsClient] = gen(_make_tracer).annotate_logs(
    {"module": "DevTools", "service": "Tracer"}
)
"""The current tracer, reporting its spans to the DevTools."""

layer_tracer: Layer[Never, Never, Socket] = layer_effect(CurrentTracer, make_tracer).pipe(
    layer_provide(layer)
)
"""Reports every span to the DevTools over the ``Socket``."""
