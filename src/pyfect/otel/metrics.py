"""pyfect metrics as OpenTelemetry metrics (Effect's ``OtelMetrics``).

``layer(lambda: reader)`` hands the current metric registry to an SDK
``MetricReader`` (a ``PeriodicExportingMetricReader`` exporting over OTLP,
say), which collects it whenever it reads::

    metrics = otel.metrics.layer(lambda: PeriodicExportingMetricReader(exporter))
    program.pipe(fx.provide(metrics.pipe(layer.provide(otel.resource.layer_empty))))

Readers are bound to pyfect's producer instead of a ``MeterProvider``; a
reader can be bound once. Counters, frequencies and summaries become sums,
gauges gauges, histograms explicit-bucket histograms.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from typing import Any, Never, Protocol

from opentelemetry.sdk.metrics.export import MetricReader, MetricsData

from pyfect import layer as _layer
from pyfect._context_effects import context
from pyfect._core import Effect
from pyfect.duration import Duration, to_millis
from pyfect.effect import die, gen, suspend, sync
from pyfect.layer import Layer
from pyfect.otel._producer import MetricProducer, TemporalityPreference
from pyfect.otel._shutdown import DEFAULT_SHUTDOWN_TIMEOUT
from pyfect.otel.resource import OtelResource
from pyfect.scope import Scope, acquire_release

__all__ = [
    "MetricProducer",
    "Readers",
    "TemporalityPreference",
    "layer",
    "make_producer",
    "register_producer",
]

type Readers = Callable[[], MetricReader | Sequence[MetricReader]]
"""Makes the readers to bind, when the layer builds."""


def make_producer(
    temporality: TemporalityPreference = "cumulative",
) -> Effect[MetricProducer, Never, OtelResource]:
    """A producer of the current metric registry, with the ``OtelResource``."""

    @gen
    def make():
        resource = yield from OtelResource()
        services = yield from context()
        return MetricProducer(resource, services, temporality)

    return make


def _bind(reader: MetricReader, producer: MetricProducer) -> None:
    if reader._collect is not None:
        raise RuntimeError(f"MetricReader {reader} has been registered already")

    def collect(_reader: MetricReader, timeout_millis: float = 10_000) -> MetricsData:
        return producer.collect()

    reader._set_collect_callback(collect)


class _ShutsDown(Protocol):
    def shutdown(self, timeout_millis: float = ...) -> None: ...


def _shut_down(readers: Sequence[_ShutsDown], timeout: Duration) -> Effect[None]:
    """Shut every reader down, ignoring errors, as Effect does."""

    def run() -> None:
        for reader in readers:
            with contextlib.suppress(Exception):
                reader.shutdown(timeout_millis=to_millis(timeout))

    return sync(run)


def register_producer(
    producer: MetricProducer,
    readers: Readers,
    *,
    shutdown_timeout: Duration = DEFAULT_SHUTDOWN_TIMEOUT,
) -> Effect[list[MetricReader], Never, Scope]:
    """Bind each reader to its own fork of ``producer``, and shut them down
    when the scope closes. If a reader cannot be bound (it is bound
    already), the readers bound so far are shut down and the effect dies."""

    def acquire() -> Effect[list[MetricReader]]:
        made = readers()
        given = [made] if isinstance(made, MetricReader) else list(made)
        bound: list[MetricReader] = []
        try:
            for reader in given:
                _bind(reader, producer.fork())
                bound.append(reader)
        except Exception as error:
            failure = error
            return _shut_down(bound, shutdown_timeout).flat_map(lambda _: die(failure))
        return sync(lambda: bound)

    return acquire_release(
        suspend(acquire), lambda bound, _exit: _shut_down(bound, shutdown_timeout)
    )


def layer(
    readers: Readers,
    *,
    temporality: TemporalityPreference = "cumulative",
    shutdown_timeout: Duration = DEFAULT_SHUTDOWN_TIMEOUT,
) -> Layer[Never, Never, OtelResource]:
    """Bind the readers ``readers()`` makes to a producer of the current
    registry while the layer is in use."""
    registered: Effect[Any, Never, OtelResource | Scope] = make_producer(temporality).flat_map(
        lambda producer: register_producer(producer, readers, shutdown_timeout=shutdown_timeout)
    )
    return _layer.effect_discard(registered)
