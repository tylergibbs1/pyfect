"""Every logger and telemetry exporter hides what ``CurrentRedactedNames``
names, whatever value carries it: as Effect's ``format`` and ``formatJson``
apply ``Redactable.redact`` and ``toJSON`` before walking a value, a type's
own redacted form wins over its fields, its mapping entries or an
exception's attributes. Each redacting type is logged as the message, as an
annotation and inside a failure, through each sink."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable, Iterator, Mapping, Sequence

import httpx
import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from oracle._otlp import collector

import pyfect as fx
from pyfect import _json_text, devtools, logger, otel
from pyfect import layer as L
from pyfect.cause import Cause, Fail
from pyfect.http import headers, request, url_params
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError, TransportError
from pyfect.latch import Latch
from pyfect.logger._text import format_unknown, to_json
from pyfect.observability import otlp, otlp_exporter
from pyfect.redacted import Redacted
from pyfect.socket import CloseEvent, Reader, Socket, SocketError, Writer
from pyfect.socket import make as make_socket
from pyfect.socket._errors import SocketCloseError

AUTH, SESSION, SIGNATURE = "SECRET-AUTH-1", "SECRET-SESSION-2", "SECRET-SIG-3"
SECRETS = (AUTH, SESSION, SIGNATURE)
URL = f"http://upstream.test/items?sig={SIGNATURE}"
HEADERS = {"authorization": f"Bearer {AUTH}", "cookie": f"sid={SESSION}"}


class _Holder(Exception):
    """An exception keeping a redacting value among its attributes."""

    def __init__(self, held: object) -> None:
        super().__init__("held")
        self.held = held


def _values() -> dict[str, object]:
    sent = request.get(URL).set_headers(HEADERS)
    raw = httpx.Request("GET", URL, headers=HEADERS)
    error = HttpClientError(TransportError(sent, cause=httpx.ConnectError("refused", request=raw)))
    return {
        "headers": headers.from_input(HEADERS),
        "url_params": url_params.from_input({"sig": SIGNATURE}),
        "request": sent,
        "http_client_error": error,
        "redacted": Redacted(AUTH),
        "nested": {"calls": [headers.from_input(HEADERS), sent]},
        "exception_attribute": _Holder(headers.from_input(HEADERS)),
    }


def _logged(value: object) -> fx.Effect[None]:
    as_message = fx.log_error(value)
    as_annotation = fx.log_error("annotated").annotate_logs({"value": value})
    as_failure = fx.log_error("failed", Cause((Fail(value),)))
    return as_message.and_then(as_annotation).and_then(as_failure).with_span("job")


def _console(sink: logger.Logger[None]) -> Callable[[object], str]:
    def run(value: object) -> str:
        out = io.StringIO()
        program = _logged(value).pipe(fx.provide(logger.layer([sink])))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            fx.run_blocking(program)
        return out.getvalue()

    return run


def _otel_sdk(value: object) -> str:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    telemetry = otel.sdk.layer(
        otel.sdk.Configuration(
            resource=otel.sdk.ResourceConfig(service_name="redaction"),
            span_processor=[SimpleSpanProcessor(spans)],
            log_record_processor=[SimpleLogRecordProcessor(logs)],
        )
    )
    fx.run_blocking(_logged(value).pipe(fx.provide(telemetry)))
    events = [
        (event.name, dict(event.attributes or {}))
        for span in spans.get_finished_spans()
        for event in span.events
    ]
    records = [
        (record.log_record.body, dict(record.log_record.attributes or {}))
        for record in logs.get_finished_logs()
    ]
    assert events and records
    return repr((events, records))


def _otlp(value: object) -> str:
    seen, http = collector()

    @fx.fn
    def program():
        yield from _logged(value)
        yield from (yield from otlp_exporter.Flusher()).flush

    exporters = otlp.layer_json(
        base_url="http://localhost:4318", resource={"service_name": "redaction"}
    )
    provided = (
        fx.scoped(program()).pipe(fx.provide(exporters)).pipe(fx.provide_service(HttpClient, http))
    )
    fx.run_blocking(provided)
    bodies = b"\n".join(seen.bodies()).decode()
    assert "logRecords" in bodies and "events" in bodies
    return bodies


def _devtools(value: object) -> str:
    """What the DevTools client writes to its socket: span snapshots and
    events, as newline-delimited JSON."""
    written: list[str] = []

    def connection():
        closed = Latch()
        yield from fx.add_finalizer(lambda _: closed.open())
        pong = [True]

        def pull() -> fx.Effect[tuple[str, ...], SocketError]:
            if pong[0]:
                pong[0] = False
                return fx.succeed(('{"_tag":"Pong"}\n',))
            return closed.wait().and_then(fx.fail(SocketError(reason=SocketCloseError(code=1006))))

        return Reader(fx.suspend(pull))

    def write(chunk: bytes | str | CloseEvent) -> fx.Effect[None]:
        if not isinstance(chunk, CloseEvent):
            written.append(chunk if isinstance(chunk, str) else chunk.decode())
        return fx.void

    def write_all(chunks: Sequence[bytes | str]) -> fx.Effect[None]:
        return fx.for_each(chunks, write).as_void()

    socket = make_socket(
        fx.suspend(lambda: fx.gen(connection)), fx.succeed(Writer(write, write_all))
    )
    tracing = devtools.layer_socket.pipe(L.provide(L.succeed(Socket, socket)))
    fx.run_blocking(fx.scoped(_logged(value).pipe(fx.provide(tracing))))
    return "".join(written)


SINKS: dict[str, Callable[[object], str]] = {
    "devtools": _devtools,
    "console_json": _console(logger.console_json),
    "console_logfmt": _console(logger.console_logfmt),
    "console_pretty": _console(logger.console_pretty()),
    "console_structured": _console(logger.console_structured),
    "format_simple": _console(logger.format_simple.with_console_log()),
    "otel_span_events_and_logs": _otel_sdk,
    "otlp_logs_and_traces": _otlp,
}


@pytest.mark.parametrize("sink", sorted(SINKS))
@pytest.mark.parametrize("kind", sorted(_values()))
def test_no_secret_reaches_a_sink(sink: str, kind: str) -> None:
    output = SINKS[sink](_values()[kind])
    # The DevTools messages are JSON (``stringify``), which has no form for
    # an exception without ``to_json``: that batch is not sent at all.
    assert output or (sink, kind) == ("devtools", "exception_attribute")
    assert [secret for secret in SECRETS if secret in output] == []


class _OwnForm(Mapping[str, str]):
    """A mapping with its own JSON form, which wins over its entries."""

    def __getitem__(self, key: str) -> str:
        return {"token": AUTH}[key]

    def __iter__(self) -> Iterator[str]:
        return iter(["token"])

    def __len__(self) -> int:
        return 1

    def to_json(self) -> dict[str, str]:
        return {"token": "<hidden>"}


class _OwnFormError(Exception):
    def __init__(self) -> None:
        super().__init__("failed")
        self.token = AUTH

    def to_json(self) -> dict[str, str]:
        return {"_tag": "OwnFormError"}


def test_a_type_s_own_json_form_wins_over_walking_it() -> None:
    nested = {"a": [_OwnForm()], "b": _OwnFormError()}
    assert to_json(nested) == {"a": [{"token": "<hidden>"}], "b": {"_tag": "OwnFormError"}}
    assert _json_text.stringify(nested) == (
        '{"a":[{"token":"<hidden>"}],"b":{"_tag":"OwnFormError"}}'
    )
    assert format_unknown(_OwnForm()) == '{"token":"<hidden>"}'
