"""Ports of Effect's ``OtlpExporter.test.ts``.

Each test's docstring is the Effect test title. ``OtlpExporter.make`` is
``otlp_exporter.make``, its ``Flusher`` is ``otlp_exporter.Flusher`` and
``layerFlusher`` is ``layer_flusher``. Durations are seconds. The
exporter's User-Agent names pyfect and Python
(``OTel-OTLP-Exporter-Python-Pyfect-<label>/<version>``) where Effect's
names Effect and JavaScript. A ``Response`` whose ``bodyUsed`` Effect
checks is a response whose body stream records that it was read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import config_provider, layer, metric, stream, testing
from pyfect._version import VERSION
from pyfect.clock import Clock, ClockService, current_time_millis
from pyfect.duration import Duration
from pyfect.duration import Input as DurationInput
from pyfect.http import body as http_body
from pyfect.http import client, response
from pyfect.http.body import HttpBody
from pyfect.http.client import HttpClient, HttpClientError, HttpClientService
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.observability import (
    otlp,
    otlp_exporter,
    otlp_logger,
    otlp_metrics,
    otlp_serialization,
    otlp_tracer,
)

from ._otlp import client_layer, collector, with_status

type Client = HttpClientService[HttpClientError]


def _make_exporter(
    http: Client,
    *,
    export_interval: DurationInput = "1 hour",
    max_batch_size: int | Literal["disabled"] = 1,
    shutdown_timeout: DurationInput = "1 second",
    body: Any = None,
    headers: dict[str, str] | None = None,
):
    def payload(items: list[Any]) -> tuple[HttpBody, fx.Effect[None]]:
        made = body(items) if body is not None else http_body.EMPTY
        return made, fx.void

    return (
        otlp_exporter.make(
            label="OtlpExporterTest",
            url="http://localhost:4318/v1/logs",
            headers=headers,
            export_interval=export_interval,
            max_batch_size=max_batch_size,
            body=payload,
            shutdown_timeout=shutdown_timeout,
        )
        .pipe(fx.provide_service(HttpClient, http))
        .pipe(layer.provide(otlp_exporter.layer_flusher))
    )


def _make_exporter_raw(max_batch_size: int | Literal["disabled"] = 1, body: Any = None):
    def payload(items: list[Any]) -> tuple[HttpBody, fx.Effect[None]]:
        return (body(items) if body is not None else http_body.EMPTY), fx.void

    return otlp_exporter.make(
        label="OtlpExporterTest",
        url="http://localhost:4318/v1/logs",
        headers=None,
        export_interval="1 hour",
        max_batch_size=max_batch_size,
        body=payload,
        shutdown_timeout="1 second",
    )


def _retrying_client(retry_after: str | None) -> tuple[list[int], Client]:
    """Answers the first request 429 (with ``retry_after``), then 200."""
    attempts = [0]

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        attempts[0] += 1
        if attempts[0] == 1:
            headers = {} if retry_after is None else {"retry-after": retry_after}
            return response.make(request, status=429, headers=headers)
        return response.make(request)

    _, http = collector(answer)
    return attempts, http


def _yield_now_n(times: int) -> fx.Effect[None]:
    return fx.for_each(range(times), lambda _: fx.yield_now()).as_void()


def _controlled_client(count: int):
    """Each request waits for its release deferred, counting interrupts."""

    @fx.gen
    def build():
        started = yield from fx.for_each(range(count), lambda _: fx.Deferred[None].make())
        releases = yield from fx.for_each(range(count), lambda _: fx.Deferred[None].make())
        interrupted = yield from fx.Ref.make(0)
        index = 0

        def post(
            requests: fx.Effect[HttpClientRequest, Any, Any],
        ) -> fx.Effect[HttpClientResponse, HttpClientError]:
            @fx.gen
            def send():
                nonlocal index
                request = yield from requests
                mine = index
                index += 1
                yield from started[mine].succeed(None)
                yield from releases[mine].wait().on_interrupt(interrupted.update(lambda n: n + 1))
                return response.make(request)

            return send

        return client.make_with(post, fx.succeed), interrupted, releases, started

    return build


@testing.effect
def test_appends_the_versioned_exporter_user_agent_to_a_user_supplied_value():
    """appends the versioned exporter User-Agent to a user-supplied value"""
    seen, http = collector()

    @fx.gen
    def push():
        exporter = yield from _make_exporter(
            http, headers={"UsEr-AgEnT": "my-app/1.0"}, max_batch_size=10
        )
        exporter.push({"value": 1})

    yield from fx.scoped(push)
    assert [request.headers.get("user-agent") for request in seen.requests] == [
        f"my-app/1.0 OTel-OTLP-Exporter-Python-Pyfect-OtlpExporterTest/{VERSION}"
    ]


@testing.effect
def test_allows_an_in_flight_timer_export_to_finish_during_shutdown():
    """allows an in-flight timer export to finish during shutdown"""
    scope = fx.CloseableScope()
    http, _, releases, started = yield from _controlled_client(1)
    exporter = yield from _make_exporter(http, export_interval="1 second", max_batch_size=10).pipe(
        fx.scope.provide(scope)
    )
    exporter.push({"value": 1})
    yield from testing.adjust("1 second")
    yield from started[0].wait()

    close_fiber = yield from scope.close(fx.Success(None)).fork()
    yield from fx.yield_now()
    assert close_fiber.poll_unsafe() is None

    yield from releases[0].succeed(None)
    yield from close_fiber.join()


@testing.effect
def test_waits_for_each_periodic_export_before_starting_the_next_interval():
    """waits for each periodic export before starting the next interval"""
    scope = fx.CloseableScope()
    http, _, releases, started = yield from _controlled_client(3)
    exporter = yield from _make_exporter(
        http, export_interval="1 second", max_batch_size="disabled"
    ).pipe(fx.scope.provide(scope))
    exporter.push({"value": 1})
    yield from testing.adjust("1 second")
    yield from started[0].wait()

    yield from testing.adjust("1 second")
    assert not (yield from started[1].is_done())

    yield from releases[0].succeed(None)
    exporter.push({"value": 2})
    yield from testing.adjust("1 second")
    yield from started[1].wait()

    exporter.push({"value": 3})
    close_fiber = yield from scope.close(fx.Success(None)).fork()
    yield from releases[1].succeed(None)
    yield from started[2].wait()
    yield from releases[2].succeed(None)
    yield from close_fiber.join()


@dataclass
class _CountingClock:
    """The test clock, counting the sleeps still pending."""

    inner: ClockService
    pending: int = 0

    def current_time_millis_unsafe(self) -> float:
        return self.inner.current_time_millis_unsafe()

    def monotonic_unsafe(self) -> float:
        return self.inner.monotonic_unsafe()

    def now_nanos_unsafe(self) -> int:
        return self.inner.now_nanos_unsafe()

    def monotonic_nanos_unsafe(self) -> int:
        return self.inner.monotonic_nanos_unsafe()

    def sleep(self, duration: Duration) -> fx.Effect[None]:
        def start() -> fx.Effect[None]:
            self.pending += 1
            return self.inner.sleep(duration).ensuring(fx.sync(self._done))

        return fx.suspend(start)

    def _done(self) -> None:
        self.pending -= 1


@testing.effect
def test_keeps_an_export_timer_pending_only_while_telemetry_is_buffered():
    """keeps an export timer pending only while telemetry is buffered"""
    seen, http = with_status(200)
    counting = _CountingClock((yield from Clock()))

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10).pipe(fx.provide_service(Clock, counting))
        flusher = yield from otlp_exporter.Flusher()
        yield from _yield_now_n(3)
        assert counting.pending == 0

        exporter.push({"value": 1})
        yield from _yield_now_n(3)
        assert counting.pending == 1
        yield from testing.adjust("1 hour")
        assert len(seen.requests) == 1
        assert counting.pending == 0

        exporter.push({"value": 2})
        yield from flusher.flush
        yield from _yield_now_n(3)
        assert len(seen.requests) == 2
        assert counting.pending == 0

    yield from _with_flusher(program, http)


@testing.effect
def test_exports_again_once_the_disabled_window_has_passed():
    """exports again once the disabled window has passed"""
    seen, http = with_status(400)

    @fx.gen
    def program():
        exporter = yield from _make_exporter(http, export_interval="1 second", max_batch_size=10)
        exporter.push({"value": 1})
        yield from testing.adjust("1 second")
        assert len(seen.requests) == 1

        yield from testing.adjust("61 seconds")
        exporter.push({"value": 2})
        yield from testing.adjust("1 second")
        assert len(seen.requests) == 2

    yield from fx.scoped(program)


@testing.effect
def test_allows_an_in_flight_batch_export_to_finish_during_shutdown():
    """allows an in-flight batch export to finish during shutdown"""
    scope = fx.CloseableScope()
    http, _, releases, started = yield from _controlled_client(1)
    exporter = yield from _make_exporter(http).pipe(fx.scope.provide(scope))
    exporter.push({"value": 1})
    yield from started[0].wait()

    close_fiber = yield from scope.close(fx.Success(None)).fork()
    yield from fx.yield_now()
    assert close_fiber.poll_unsafe() is None

    yield from releases[0].succeed(None)
    yield from close_fiber.join()


@testing.effect
def test_exports_remaining_telemetry_concurrently_and_waits_for_all_requests():
    """exports remaining telemetry concurrently and waits for all requests"""
    scope = fx.CloseableScope()
    http, _, releases, started = yield from _controlled_client(2)
    batches: list[list[int]] = []

    def body(items: list[Any]) -> HttpBody:
        batches.append([item["value"] for item in items])
        return http_body.EMPTY

    exporter = yield from _make_exporter(http, max_batch_size=2, body=body).pipe(
        fx.scope.provide(scope)
    )
    exporter.push({"value": 1})
    exporter.push({"value": 2})
    yield from started[0].wait()
    exporter.push({"value": 3})

    close_fiber = yield from scope.close(fx.Success(None)).fork()
    yield from started[1].wait()
    assert batches == [[1, 2], [3]]

    yield from releases[0].succeed(None)
    yield from fx.yield_now()
    assert close_fiber.poll_unsafe() is None
    yield from releases[1].succeed(None)
    yield from close_fiber.join()


@testing.effect
def test_bounds_shutdown_waiting_and_interrupts_remaining_requests():
    """bounds shutdown waiting and interrupts remaining requests"""
    scope = fx.CloseableScope()
    http, interrupted, _, started = yield from _controlled_client(1)
    exporter = yield from _make_exporter(http).pipe(fx.scope.provide(scope))
    exporter.push({"value": 1})
    yield from started[0].wait()

    close_fiber = yield from scope.close(fx.Success(None)).fork()
    yield from testing.adjust("1 second")
    yield from close_fiber.join()
    assert (yield from interrupted.get()) == 1


@testing.effect
def test_does_not_initiate_or_wait_for_delivery_when_disabled():
    """does not initiate or wait for delivery when disabled"""
    scope = fx.CloseableScope()
    blocked = yield from fx.Deferred[None].make()
    blocked_interrupted = yield from fx.Deferred[None].make()
    failed = yield from fx.Deferred[None].make()
    attempts = 0

    def post(
        requests: fx.Effect[HttpClientRequest, Any, Any],
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        @fx.gen
        def send():
            nonlocal attempts
            request = yield from requests
            attempts += 1
            if attempts == 1:
                yield from blocked.succeed(None)
                return (yield from fx.never.on_interrupt(blocked_interrupted.succeed(None)))
            yield from failed.succeed(None)
            return response.make(request, status=400)

        return send

    http = client.make_with(post, fx.succeed)
    exporter = yield from _make_exporter(http).pipe(fx.scope.provide(scope))
    exporter.push({"value": 1})
    yield from blocked.wait()
    exporter.push({"value": 2})
    yield from failed.wait()
    yield from _yield_now_n(3)
    exporter.push({"value": 3})

    yield from scope.close(fx.Success(None))
    yield from blocked_interrupted.wait()
    assert attempts == 2


def _retry_case(retry_after: str | None, first: float, second: float):
    @fx.gen
    def run():
        attempts, http = _retrying_client(retry_after)
        exporter = yield from _make_exporter(http)
        exporter.push({"value": 1})
        yield from _yield_now_n(3)
        assert attempts[0] == 1

        yield from testing.adjust(fx.duration.seconds(first))
        yield from _yield_now_n(2)
        assert attempts[0] == 1

        yield from testing.adjust(fx.duration.seconds(second))
        yield from _yield_now_n(2)
        assert attempts[0] == 2

    return run


@testing.effect
def test_retries_status_429_with_numeric_retry_after_delay():
    """retries status 429 with numeric retry-after delay"""
    yield from _retry_case("2", 1, 1)


@testing.effect
def test_retries_status_429_with_http_date_retry_after_delay():
    """retries status 429 with HTTP-date retry-after delay"""
    yield from _retry_case("Thu, 01 Jan 1970 00:01:00 GMT", 5, 55)


@testing.effect
def test_uses_fallback_retry_after_delay_when_header_is_non_numeric():
    """uses fallback retry-after delay when header is non-numeric"""
    yield from _retry_case("soon", 4, 1)


@testing.effect
def test_uses_fallback_retry_after_delay_when_header_is_negative():
    """uses fallback retry-after delay when header is negative"""
    yield from _retry_case("-5", 4, 1)


@testing.effect
def test_uses_fallback_retry_after_delay_when_header_is_missing():
    """uses fallback retry-after delay when header is missing"""
    yield from _retry_case(None, 4, 1)


def _with_flusher(eff: fx.Effect[Any, Any, Any], http: Client) -> fx.Effect[Any, Any, Any]:
    return fx.scoped(
        eff.pipe(fx.provide_service(HttpClient, http)).pipe(
            layer.provide(otlp_exporter.layer_flusher)
        )
    )


@testing.effect
def test_exports_buffered_items_without_advancing_to_the_export_interval():
    """flush exports buffered items without advancing to the export interval"""
    seen, http = with_status(200)

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        before = yield from current_time_millis()
        exporter.push({"value": 1})
        yield from flusher.flush
        assert (yield from current_time_millis()) == before
        assert len(seen.requests) == 1

    yield from _with_flusher(program, http)


class _Responses:
    """Answers 429 first, then 200, each with a body that records its read."""

    def __init__(self) -> None:
        self.used: list[bool] = []

    def answer(self, request: HttpClientRequest) -> HttpClientResponse:
        index = len(self.used)
        self.used.append(False)

        def read() -> bytes:
            self.used[index] = True
            return b"body"

        body = stream.from_effect(fx.sync(read))
        status = 429 if index == 0 else 200
        return response.make(request, body, status=status, headers={"retry-after": "1"})


@pytest.mark.parametrize("filter_status", [False, True], ids=["", "from a status-filtered client"])
@testing.effect
def test_drains_a_429_response_before_retrying(filter_status: bool):
    """flush drains a 429 response before retrying${filterStatus ? " from a status-filtered client" : ""}"""  # noqa: E501
    responses = _Responses()
    _, raw = collector(responses.answer)
    http = raw.filter_status_ok() if filter_status else raw

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        flush = yield from flusher.flush.fork()
        yield from _yield_now_n(3)
        assert responses.used == [True]

        yield from testing.adjust("1 second")
        yield from flush.join()
        assert responses.used == [True, True]

    yield from _with_flusher(program, http)


@testing.effect
def test_keeps_exporting_when_reading_a_successful_response_body_fails():
    """flush keeps exporting when reading a successful response body fails"""
    seen, http = collector(
        lambda request: response.make(request, stream.fail(Exception("body read failed")))
    )

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        yield from flusher.flush
        exporter.push({"value": 2})
        yield from flusher.flush
        assert len(seen.requests) == 2

    yield from _with_flusher(program, http)


@testing.effect
def test_does_not_export_empty_payloads_when_batching_is_disabled():
    """flush does not export empty payloads when batching is disabled"""
    _, http = with_status(200)
    payloads: list[list[Any]] = []

    def body(items: list[Any]) -> HttpBody:
        payloads.append(items)
        return http_body.EMPTY

    @fx.gen
    def program():
        yield from _make_exporter_raw("disabled", body)
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush

    yield from _with_flusher(program, http)
    assert payloads == []


@testing.effect
def test_exports_buffered_items_once_when_batching_is_disabled():
    """flush exports buffered items once when batching is disabled"""
    _, http = with_status(200)
    payloads: list[list[Any]] = []

    def body(items: list[Any]) -> HttpBody:
        payloads.append(items)
        return http_body.EMPTY

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw("disabled", body)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        yield from flusher.flush
        yield from flusher.flush

    yield from _with_flusher(program, http)
    assert payloads == [[{"value": 1}]]


@testing.effect
def test_shares_one_registry_across_traces_logs_and_metrics():
    """flush shares one registry across traces, logs and metrics"""
    seen, http = with_status(200)
    signals = (
        layer.merge(
            otlp_tracer.layer(
                url="http://localhost:4318/v1/traces",
                resource={"service_name": "test"},
                export_interval="1 hour",
                max_batch_size=100,
            ),
            otlp_logger.layer(
                url="http://localhost:4318/v1/logs",
                resource={"service_name": "test"},
                export_interval="1 hour",
                max_batch_size=100,
                merge_with_existing=False,
            ),
            otlp_metrics.layer(
                url="http://localhost:4318/v1/metrics",
                resource={"service_name": "test"},
                export_interval="1 hour",
            ),
        )
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide_merge(client_layer(http)))
    )

    @fx.gen
    def program():
        yield from fx.log("flush test")
        yield from metric.counter("otlp_flush_test").update(1)
        yield from fx.void.with_span("flush test")
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush
        assert sorted(seen.urls) == [
            "http://localhost:4318/v1/logs",
            "http://localhost:4318/v1/metrics",
            "http://localhost:4318/v1/traces",
        ]

    yield from program.pipe(layer.provide(signals))


@testing.effect
def test_otlp_layer_from_config_flushes_enabled_signals_when_one_is_disabled():
    """flush Otlp.layerFromConfig flushes enabled signals when one is disabled"""
    seen, http = with_status(200)
    env = {
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_BLRP_SCHEDULE_DELAY": "3600000",
        "OTEL_METRIC_EXPORT_INTERVAL": "3600000",
    }
    signals = (
        otlp.layer_from_config(resource={"service_name": "test"}, logger_merge_with_existing=False)
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide(client_layer(http)))
        .pipe(layer.provide(config_provider.layer(config_provider.from_env(env))))
    )

    @fx.gen
    def program():
        yield from fx.log("flush test")
        yield from metric.counter("otlp_flush_test").update(1)
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush
        assert sorted(seen.urls) == [
            "http://localhost:4318/v1/logs",
            "http://localhost:4318/v1/metrics",
        ]

    yield from program.pipe(layer.provide(signals))


@testing.effect
def test_is_a_no_op_while_the_exporter_is_disabled():
    """flush is a no-op while the exporter is disabled"""
    seen, http = with_status(400)

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        yield from flusher.flush
        assert len(seen.requests) == 1
        exporter.push({"value": 2})
        yield from flusher.flush
        assert len(seen.requests) == 1

    yield from _with_flusher(program, http)


@testing.effect
def test_deregisters_an_exporter_when_its_scope_closes():
    """flush deregisters an exporter when its scope closes"""
    seen, http = with_status(200)

    @fx.gen
    def program():
        flusher = yield from otlp_exporter.Flusher()
        scope = fx.CloseableScope()
        exporter = (
            yield from _make_exporter_raw("disabled")
            .pipe(fx.provide_service(HttpClient, http))
            .pipe(fx.scope.provide(scope))
        )
        exporter.push({"value": 1})
        yield from scope.close(fx.Success(None))
        assert len(seen.requests) == 1
        yield from flusher.flush
        assert len(seen.requests) == 1

    yield from program.pipe(layer.provide(otlp_exporter.layer_flusher))


@testing.effect
def test_succeeds_with_no_registered_exporters():
    """flush succeeds with no registered exporters"""

    @fx.gen
    def program():
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush

    yield from program.pipe(layer.provide(otlp_exporter.layer_flusher))


@testing.effect
def test_is_available_when_the_sdk_is_disabled():
    """flush is available when the SDK is disabled"""
    seen, http = with_status(200)
    provider = config_provider.from_env({"OTEL_SDK_DISABLED": "true"})
    signals = (
        otlp_tracer.layer_from_config()
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide_merge(client_layer(http)))
        .pipe(layer.provide_merge(config_provider.layer(provider)))
    )

    @fx.gen
    def program():
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush

    yield from program.pipe(layer.provide(signals))
    assert seen.requests == []


@testing.effect
def test_does_not_fail_when_the_collector_returns_500():
    """flush does not fail when the collector returns 500"""
    seen, http = with_status(500)

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        fiber = yield from flusher.flush.fork()
        yield from _yield_now_n(3)
        yield from testing.adjust("3 seconds")
        yield from fiber.join()
        assert len(seen.requests) == 4
        yield from flusher.flush
        assert len(seen.requests) == 4

    yield from _with_flusher(program, http)


@testing.effect
def test_a_failed_export_disables_the_exporter_for_60_seconds():
    """Not an Effect title: pins Effect's 60-second window (``disabledUntil``),
    which its tests leave unchecked. Items pushed inside it are dropped."""
    seen, http = with_status(400)

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        yield from flusher.flush
        yield from testing.adjust("59 seconds")
        yield from flusher.flush
        exporter.push({"value": 2})
        yield from flusher.flush
        assert len(seen.requests) == 1

        yield from testing.adjust("1 second")
        yield from flusher.flush
        exporter.push({"value": 3})
        yield from flusher.flush
        assert len(seen.requests) == 2

    yield from _with_flusher(program, http)


@testing.effect
def test_the_export_interval_starts_with_the_first_push():
    """Not an Effect 4.0.6 title: Effect 4.1.2's ``make`` arms the interval with
    the first push, so an item pushed at 2 seconds goes out at 7, not 5."""
    times: list[int] = []

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        return response.make(request)

    seen, http = collector(answer)

    @fx.gen
    def program():
        exporter = yield from _make_exporter(
            http, export_interval="5 seconds", max_batch_size="disabled"
        )
        yield from testing.adjust("2 seconds")
        exporter.push({"value": 1})
        yield from testing.adjust("4900 millis")
        times.append(len(seen.requests))
        yield from testing.adjust("100 millis")
        times.append(len(seen.requests))

    yield from fx.scoped(program)
    assert times == [0, 1]


@testing.effect
def test_an_exporter_that_emptied_its_buffer_rearms_on_the_next_push():
    """Not an Effect 4.0.6 title: Effect 4.1.2 disarms the interval once an
    export empties the buffer; the next push starts a fresh interval."""
    seen, http = collector()

    @fx.gen
    def program():
        exporter = yield from _make_exporter(
            http, export_interval="5 seconds", max_batch_size="disabled"
        )
        exporter.push({"value": 1})
        yield from testing.adjust("5 seconds")
        assert len(seen.requests) == 1
        yield from testing.adjust("3 seconds")
        exporter.push({"value": 2})
        yield from testing.adjust("4 seconds")
        assert len(seen.requests) == 1
        yield from testing.adjust("1 second")
        assert len(seen.requests) == 2

    yield from fx.scoped(program)


@testing.effect
def test_a_push_after_the_disabled_window_ends_it():
    """Not an Effect 4.0.6 title: in Effect 4.1.2 ``push`` ends a disabled window
    that has run out, so an item pushed after the minute is exported."""
    statuses = [400]

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        return response.make(request, status=statuses.pop() if statuses else 200)

    seen, http = collector(answer)

    @fx.gen
    def program():
        exporter = yield from _make_exporter_raw(10)
        flusher = yield from otlp_exporter.Flusher()
        exporter.push({"value": 1})
        yield from flusher.flush
        yield from testing.adjust("60 seconds")
        exporter.push({"value": 2})
        yield from flusher.flush
        assert len(seen.requests) == 2

    yield from _with_flusher(program, http)
