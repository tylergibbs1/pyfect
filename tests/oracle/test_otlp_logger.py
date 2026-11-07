"""Ports of Effect's ``OtlpLogger.test.ts``.

Each test's docstring is the Effect test title. ``logger.log({...})`` is
``logger.log(Options(...))``; ``new Date(1234)`` is a UTC ``datetime`` 1234
milliseconds after the epoch. The instrumentation scope is pyfect's, and
``exception.type`` is the exception's class name.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pyfect as fx
from pyfect import cause, layer, testing
from pyfect._version import VERSION
from pyfect.clock import now_nanos
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.logger import LogLevel, Options
from pyfect.observability import otlp_exporter, otlp_logger, otlp_serialization
from pyfect.tracer import ExternalSpan

from ._otlp import Collector, client_layer, collector


def _test_layer(seen_client: Any) -> Layer[otlp_exporter.Flusher]:
    return (
        otlp_logger.layer(
            url="http://localhost:4318/v1/logs",
            resource={"service_name": "test", "service_version": "service-version"},
            export_interval="1 hour",
            merge_with_existing=False,
        )
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide(client_layer(seen_client)))
    )


def _log_record(seen: Collector, index: int = 0) -> dict[str, Any]:
    return seen.json()[index]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]


def _flush() -> fx.Effect[None, Any, Any]:
    return otlp_exporter.Flusher().flat_map(lambda flusher: flusher.flush)


@testing.effect
def test_keeps_event_time_separate_from_observed_time():
    """keeps event time separate from observed time"""
    seen, http = collector()

    @fx.gen
    def program():
        logger = yield from otlp_logger.make(
            url="http://localhost:4318/v1/logs",
            resource={"service_name": "test"},
            export_interval="1 hour",
        )
        fiber = yield from fx.current_fiber()
        observed_time = yield from now_nanos()
        date = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=1234)
        logger.log(Options(("test",), LogLevel.INFO, cause.empty, fiber, date))
        yield from _flush()
        record = _log_record(seen)
        assert record["timeUnixNano"] == "1234000000"
        assert record["observedTimeUnixNano"] == str(observed_time)

    yield from (
        fx.scoped(program)
        .pipe(layer.provide(otlp_exporter.layer_flusher))
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(fx.provide_service(HttpClient, http))
    )


@testing.effect
def test_namespaces_generated_attributes_and_lets_them_override_annotations():
    """namespaces generated attributes and lets them override annotations"""
    seen, http = collector()

    def failing() -> TypeError:
        try:
            try:
                raise ValueError("nested failure")
            except ValueError as nested:
                raise TypeError("cause message") from nested
        except TypeError as error:
            return error

    @fx.gen
    def program():
        fiber = yield from fx.current_fiber()

        @fx.gen
        def logged():
            yield from testing.adjust("5 millis")
            yield from fx.log_error("boom", cause.fail(failing()))

        yield from logged.with_log_span("op").annotate_logs(
            {
                "effect.fiberId": -1,
                "effect.log_span.op": -1,
                "exception.type": "annotated type",
                "exception.message": "annotated message",
                "exception.stacktrace": "annotated stack",
            }
        )
        yield from _flush()
        record = _log_record(seen)
        keys = [attribute["key"] for attribute in record["attributes"]]
        assert len(set(keys)) == len(keys)
        attributes = {attribute["key"]: attribute["value"] for attribute in record["attributes"]}
        assert attributes["effect.fiberId"] == {"intValue": fiber.id}
        assert attributes["effect.log_span.op"] == {"intValue": 5}
        assert attributes["exception.type"] == {"stringValue": "TypeError"}
        assert attributes["exception.message"] == {"stringValue": "cause message"}
        assert "nested failure" in attributes["exception.stacktrace"]["stringValue"]
        assert seen.json()[0]["resourceLogs"][0]["scopeLogs"][0]["scope"] == {
            "name": "pyfect",
            "version": VERSION,
        }

    yield from program.pipe(layer.provide(_test_layer(http)))


@testing.effect
def test_pads_a_64_bit_trace_id_to_32_hex_characters():
    """pads a 64-bit trace id to 32 hex characters"""
    seen, http = collector()

    @fx.gen
    def program():
        parent = ExternalSpan(trace_id="463ac35c9f6413ad", span_id="0020000000000001")
        yield from fx.log("test").with_parent_span(parent)
        yield from _flush()
        assert _log_record(seen)["traceId"] == "0000000000000000463ac35c9f6413ad"

    yield from program.pipe(layer.provide(_test_layer(http)))
