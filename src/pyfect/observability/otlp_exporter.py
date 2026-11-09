"""The batch exporter every OTLP signal posts through (Effect's
``OtlpExporter``): it buffers encoded telemetry, posts batches on an
interval or when a batch is full, retries transient failures, stops
exporting for 60 seconds after one it cannot handle, and flushes when its
scope closes.

``Flusher`` drains every exporter sharing it on demand; the signal layers
share ``layer_flusher``, so one ``flush`` drains traces, logs and metrics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Never

from pyfect import layer as _layer
from pyfect._concurrency import for_each
from pyfect._fiber import Fiber
from pyfect._version import VERSION
from pyfect.cause import Cause
from pyfect.clock import Clock, now_millis_unsafe, sleep
from pyfect.context import Tag
from pyfect.duration import ZERO, Duration, Seconds, to_seconds
from pyfect.effect import (
    Effect,
    gen,
    provide_service,
    succeed,
    suspend,
    sync,
)
from pyfect.fiber_set import FiberSet
from pyfect.http import headers as _headers
from pyfect.http import request as _request
from pyfect.http.body import HttpBody
from pyfect.http.client import (
    HttpClient,
    HttpClientError,
    HttpClientService,
    TracerPropagationEnabled,
    transform_response,
)
from pyfect.http.error import StatusCodeError
from pyfect.http.headers import parse_retry_after, retry_after_delay
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.logger import log_debug
from pyfect.result import Ok
from pyfect.schedule import Metadata, forever
from pyfect.scope import Scope, add_finalizer

__all__ = [
    "Compression",
    "Exporter",
    "Flusher",
    "FlusherService",
    "layer_flusher",
    "make",
]

type Compression = Literal["gzip", "none"]
"""Request compression; ``"gzip"`` leaves bodies under 1 KB as they are."""


@dataclass(frozen=True, slots=True)
class FlusherService:
    """``flush`` drains every registered exporter at once and cannot fail.
    It skips exporters in their 60-second disabled window and waits only for
    the exports it starts; bound it with ``timeout_option``. ``register``
    adds an export until the current scope closes."""

    flush: Effect[None]
    register: Callable[[Effect[None]], Effect[None, Never, Scope]]


class Flusher(Tag[FlusherService]):
    """The registry of exporter flushes."""


def _make_flusher() -> FlusherService:
    registry: dict[int, Effect[None]] = {}

    def flush() -> Effect[None]:
        if not registry:
            return succeed(None)
        return for_each(list(registry.values()), lambda run: run, concurrency="unbounded").as_void()

    def register(run: Effect[None]) -> Effect[None, Never, Scope]:
        def add() -> None:
            registry[id(run)] = run

        return sync(add).and_then(
            add_finalizer(lambda _exit: sync(lambda: registry.pop(id(run), None)))
        )

    return FlusherService(flush=suspend(flush), register=register)


layer_flusher: Final[Layer[Flusher]] = _layer.sync(Flusher, _make_flusher)
"""A ``Flusher`` with a fresh registry. One constant, so every signal layer
that uses it shares one registry per layer build (layers are memoized by
identity). Flushing an empty registry does nothing."""


def _retry_after_delay(value: str | None) -> Effect[Duration]:
    """A valid ``Retry-After``'s delay; a missing or invalid one waits 5
    seconds."""
    retry_after = None if value is None else parse_retry_after(value)
    if not isinstance(retry_after, Ok):
        return succeed("5 seconds")
    parsed = retry_after.value
    return Clock().map(lambda clock: retry_after_delay(parsed, now_millis_unsafe(clock)))


def _delay(meta: Metadata[object, object]) -> Effect[Duration]:
    error = meta.output
    if (
        isinstance(error, HttpClientError)
        and isinstance(error.reason, StatusCodeError)
        and error.reason.response.status == 429
    ):
        return _retry_after_delay(error.reason.response.headers.get("retry-after"))
    return succeed("1 second")


_POLICY: Final = forever.passthrough().add_delay(_delay)
"""Retry with a second's pause, or a 429's ``Retry-After``."""

_DISABLED_MILLIS: Final = 60_000


@dataclass(frozen=True, slots=True)
class Exporter:
    """``push`` buffers one item for the next batch (dropped while the
    exporter is disabled)."""

    push: Callable[[Any], None]


def _drain(response: HttpClientResponse) -> Effect[None]:
    return response.bytes_.ignore()


def _drain_error(error: HttpClientError) -> Effect[None]:
    response = error.response
    return succeed(None) if response is None else response.bytes_.ignore()


def _client(http: HttpClientService[HttpClientError]) -> HttpClientService[HttpClientError]:
    return (
        http.tap(_drain)
        .tap_error(_drain_error)
        .filter_status_ok()
        .pipe(transform_response(provide_service(TracerPropagationEnabled, False)))
        .retry_transient(schedule=_POLICY, times=3)
    )


def _post(url: str, headers: _headers.Input | None, label: str) -> HttpClientRequest:
    exporter_agent = f"OTel-OTLP-Exporter-Python-Pyfect-{label}/{VERSION}"
    user_headers = _headers.from_input(headers)
    user_agent = user_headers.get("user-agent")
    return _request.post(
        url,
        headers=user_headers.set(
            "user-agent", f"{user_agent} {exporter_agent}" if user_agent else exporter_agent
        ),
    )


@dataclass(frozen=True, slots=True)
class _Timer:
    """The export interval: ``armed`` is open while there is something to
    export, and changes in the same synchronous step as the buffer check, so
    no push is stranded. ``wake`` cuts a sleep short once a flush disarmed it."""

    armed: Latch
    keep_armed: bool
    wake: Latch = field(default_factory=Latch)

    def disarm_if_empty(self, buffered: bool) -> None:
        if self.keep_armed or buffered or not self.armed.close_unsafe():
            return
        self.wake.open_unsafe()

    def loop(
        self,
        interval: Seconds,
        export: Effect[Fiber[None, Never]],
        buffered: Callable[[], bool],
    ) -> Effect[Never]:
        @gen
        def run():
            while True:
                self.wake.close_unsafe()
                yield from self.armed.wait()
                yield from sleep(interval).race(self.wake.wait())
                fiber = yield from export
                yield from fiber.await_exit()
                self.disarm_if_empty(buffered())

        return run


def make(
    *,
    url: str,
    headers: _headers.Input | None,
    label: str,
    export_interval: Duration,
    max_batch_size: int | Literal["disabled"],
    body: Callable[[list[Any]], tuple[HttpBody, Effect[None]]],
    shutdown_timeout: Duration,
    compression: Compression = "none",
    export_empty: bool = False,
) -> Effect[Exporter, Never, Flusher | HttpClient | Scope]:
    """A scoped batch exporter posting ``body(items)`` to ``url``.

    It exports ``export_interval`` after the first item is buffered (each
    export finishing before the next interval starts) and as soon as
    ``max_batch_size`` items are buffered; with ``max_batch_size="disabled"``
    only on the interval or a flush. An export that empties the buffer stops
    the interval until the next push, so an idle exporter keeps no timer;
    with ``export_empty`` and batching disabled it exports every interval.
    Transient failures are retried three times. Any other failure drops the
    buffer and disables exporting for 60 seconds; the first push or export
    after that ends the window. When the scope closes it exports
    what is left and waits up to ``shutdown_timeout`` for its exports,
    then interrupts them. ``"gzip"`` compression happens once, before the
    retries; ``body``'s effect runs after a successful post."""
    interval = Seconds(max(to_seconds(export_interval), ZERO))
    timeout = to_seconds(shutdown_timeout)

    @gen
    def build():
        clock = yield from Clock()
        client = _client((yield from HttpClient()))
        request = _post(url, headers, label)

        exports_empty = max_batch_size == "disabled" and export_empty
        disabled_until: int | None = None
        buffer: list[Any] = []

        def is_disabled() -> bool:
            nonlocal disabled_until
            if disabled_until is None:
                return False
            if now_millis_unsafe(clock) < disabled_until:
                return True
            disabled_until = None
            return False

        def export() -> Effect[None, Any]:
            nonlocal buffer
            if is_disabled() or (not buffer and not exports_empty):
                return succeed(None)
            items, buffer = buffer, []
            payload, on_success = body(items)
            batch = request.set_body(payload)
            response = (
                batch.compress_body("gzip").flat_map(client.execute)
                if compression == "gzip"
                else client.execute(batch)
            )
            return response.and_then(on_success).as_void().with_tracer_enabled(False)

        def disable(cause: Cause[object]) -> Effect[None]:
            nonlocal disabled_until, buffer
            if disabled_until is not None:
                return succeed(None)
            disabled_until = now_millis_unsafe(clock) + _DISABLED_MILLIS
            buffer = []
            return log_debug("Disabling exporter for 60 seconds", cause)

        run_export: Effect[None] = (
            suspend(export)
            .catch_cause(disable)
            .annotate_logs({"package": "pyfect", "module": label})
        )

        export_fibers = yield from FiberSet[None, Never].make()
        fork_export = yield from export_fibers.runtime()

        def shut_down() -> Effect[None]:
            if disabled_until is not None:
                return succeed(None)
            fork_export(run_export)
            return export_fibers.await_empty()

        yield from add_finalizer(
            lambda _exit: suspend(shut_down).ignore().interruptible().timeout_option(timeout)
        )

        timer = _Timer(armed=Latch(exports_empty), keep_armed=exports_empty)
        # Forked after the shutdown finalizer, so the loop stops before the
        # shutdown flush.
        scope = yield from Scope()
        yield from timer.loop(
            interval, export_fibers.run(run_export), lambda: bool(buffer)
        ).fork_in(scope)
        export_now = run_export.and_then(sync(lambda: timer.disarm_if_empty(bool(buffer))))

        flusher = yield from Flusher()
        yield from flusher.register(export_now)

        def push(item: Any) -> None:
            # With no idle timer, the next push ends the disabled window.
            if is_disabled():
                return
            buffer.append(item)
            if max_batch_size != "disabled" and len(buffer) >= max_batch_size:
                fork_export(export_now)
            else:
                timer.armed.open_unsafe()

        return Exporter(push)

    return build
