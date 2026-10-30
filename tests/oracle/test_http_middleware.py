"""Ports of Effect's ``http/HttpMiddleware.test.ts``.

Each test's docstring is the Effect test title. A response carried by a
defect is ``Die(UnhandledError(response))`` (``server_response.die_with``),
since a pyfect defect is an exception.

Changed, with the reason:

- ``restores ParentSpan and ends the span if interrupted before handler
  registration``: Effect forces the gap with a scheduler whose
  ``shouldYield`` fires once the span is made; here the tracer interrupts
  the fiber from inside ``span()``, the same gap (the interrupt is
  delivered synchronously on the fiber's own thread).
"""

# pyright: reportPrivateUsage=false

import asyncio
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, logger
from pyfect._core import _WithFiber
from pyfect.cause import Cause, Fail, UnhandledError
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context
from pyfect.exit import Failure, Success
from pyfect.http import headers as headers_
from pyfect.http import server_response
from pyfect.http.abort import AbortController
from pyfect.http.middleware import cors, tracer, x_forwarded_headers
from pyfect.http.middleware import logger as http_logger
from pyfect.http.server_error import ClientAbort, HttpServerError, ResponseError
from pyfect.http.server_request import HttpServerRequest, ServerRequest, to_url
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import request_from_web, response_to_web, to_web_handler
from pyfect.logger import CurrentLogAnnotations, CurrentLogSpans, Logger, LogLevel
from pyfect.net import ip_network
from pyfect.tracer import (
    CurrentTracer,
    Ended,
    MinimumTraceLevel,
    NativeSpan,
    ParentSpan,
    SpanRequest,
    Tracer,
    current_span,
)


def _request(url: str = "http://localhost:3000/", **options: Any) -> ServerRequest:
    return request_from_web(WebRequest(url, **options))


def _serve(handler: Any, request: WebRequest) -> WebResponse:
    async def main() -> WebResponse:
        return await handler(request)

    return asyncio.run(main())


# --- cors -------------------------------------------------------------------------

_ORIGINS = ("https://client.example", "https://other.example")


@pytest.mark.parametrize(
    ("name", "vary", "expected"),
    [
        ("adds Origin when Vary is absent", None, "Origin"),
        (
            "preserves existing Vary dimensions when adding Origin",
            "Accept-Language",
            "Accept-Language, Origin",
        ),
        (
            "preserves other dimensions without duplicating a mixed-case Origin",
            "Accept-Language, oRiGiN",
            "Accept-Language, oRiGiN",
        ),
        ("preserves wildcard Vary", "*", "*"),
    ],
)
def test_cors_vary(name: str, vary: str | None, expected: str) -> None:
    """$name"""
    del name
    response = server_response.text("hello", headers={} if vary is None else {"Vary": vary})
    handler = to_web_handler(cors(allowed_origins=_ORIGINS)(effect.succeed(response)))
    web = _serve(
        handler, WebRequest("http://localhost/", headers={"Origin": "https://client.example"})
    )
    assert web.get("access-control-allow-origin") == "https://client.example"
    assert web.get("vary") == expected


def test_preserves_both_vary_dimensions_for_preflight_requests() -> None:
    """preserves both Vary dimensions for preflight requests"""
    handler = to_web_handler(
        cors(allowed_origins=_ORIGINS)(effect.succeed(server_response.empty()))
    )
    web = _serve(
        handler,
        WebRequest(
            "http://localhost/",
            method="OPTIONS",
            headers={
                "Origin": "https://client.example",
                "Access-Control-Request-Headers": "X-Test",
            },
        ),
    )
    vary = sorted(member.strip().lower() for member in (web.get("vary") or "").split(","))
    assert vary == ["access-control-request-headers", "origin"]


def test_varies_by_origin_when_the_request_origin_is_rejected() -> None:
    """varies by Origin when the request origin is rejected"""
    handler = to_web_handler(
        cors(allowed_origins=_ORIGINS)(effect.succeed(server_response.empty()))
    )
    web = _serve(
        handler, WebRequest("http://localhost/", headers={"Origin": "https://rejected.example"})
    )
    assert web.get("vary") == "Origin"


def test_preserves_vary_when_allowing_all_origins() -> None:
    """preserves Vary when allowing all origins"""
    response = server_response.text("hello", headers={"Vary": "Accept-Language"})
    handler = to_web_handler(cors()(effect.succeed(response)))
    web = _serve(
        handler, WebRequest("http://localhost/", headers={"Origin": "https://client.example"})
    )
    assert web.get("access-control-allow-origin") == "*"
    assert web.get("vary") == "Accept-Language"


# --- logger -----------------------------------------------------------------------


def test_preserves_failures_mixed_with_client_aborts_even_with_status_499() -> None:
    """preserves failures mixed with client aborts even with status 499"""
    cause = interrupt_cause(2).annotate(Context.make(ClientAbort, True)) + fail_cause(
        "handler failed"
    )
    logs: list[tuple[object, Cause[object], object]] = []
    recorder = Logger.make(
        lambda options: logs.append(
            (
                options.message,
                options.cause,
                options.fiber.get_ref(CurrentLogAnnotations).get("http.status"),
            )
        )
    )
    # The server attaches the response to the failed handler cause.
    handler_cause = cause + die_cause(UnhandledError(server_response.empty(status=499)))
    exit = fx.run_sync(
        http_logger(effect.fail_cause(handler_cause))
        .pipe(effect.provide_service(HttpServerRequest, _request("http://localhost/slow")))
        .pipe(fx.provide(logger.layer([recorder])))
        .exit()
    )
    assert isinstance(exit, Failure)
    assert exit.cause == handler_cause
    assert logs == [((), cause, 499)]


def test_logs_client_aborts_as_sent_responses_with_status_499() -> None:
    """logs client aborts as sent responses with status 499"""
    logs: list[tuple[object, Cause[object], LogLevel, dict[str, object]]] = []
    recorder = Logger.make(
        lambda options: logs.append(
            (
                options.message,
                options.cause,
                options.log_level,
                dict(options.fiber.get_ref(CurrentLogAnnotations)),
            )
        )
    )

    async def main() -> WebResponse:
        started = asyncio.Event()
        app = effect.sync(started.set).and_then(effect.never).interruptible()
        handler = to_web_handler(
            app, lambda inner: http_logger(inner).pipe(fx.provide(logger.layer([recorder])))
        )
        controller = AbortController()
        pending = asyncio.ensure_future(
            handler(WebRequest("http://localhost/slow", signal=controller.signal))
        )
        await started.wait()
        controller.abort()
        return await pending

    response = asyncio.run(main())
    assert response.status == 499
    assert len(logs) == 1
    message, cause, level, annotations = logs[0]
    assert annotations == {"http.method": "GET", "http.url": "/slow", "http.status": 499}
    assert level == LogLevel.INFO
    assert message == ("Sent HTTP response",)
    assert cause.reasons == ()


def test_annotates_method_path_and_status_without_query_or_hash() -> None:
    """annotates method, path, and status without query or hash"""
    annotations: list[dict[str, object]] = []
    recorder = Logger.make(
        lambda options: annotations.append(dict(options.fiber.get_ref(CurrentLogAnnotations)))
    )
    request = _request("http://localhost:3000/todos/1?foo=bar#top")
    fx.run_sync(
        http_logger(effect.succeed(server_response.empty(status=204)))
        .pipe(effect.provide_service(HttpServerRequest, request))
        .pipe(fx.provide(logger.layer([recorder])))
    )
    assert len(annotations) == 1
    assert annotations[0]["http.method"] == "GET"
    assert annotations[0]["http.url"] == "/todos/1"
    assert annotations[0]["http.status"] == 204


def test_uses_a_stable_http_span_log_span_name() -> None:
    """uses a stable http.span log span name"""
    spans: list[list[str]] = []
    recorder = Logger.make(
        lambda options: spans.append(
            [span.label for span in options.fiber.get_ref(CurrentLogSpans)]
        )
    )
    logged = http_logger(effect.succeed(server_response.empty(status=204))).pipe(
        fx.provide(logger.layer([recorder]))
    )
    for path in ("one", "two"):
        request = _request(f"http://localhost:3000/{path}")
        fx.run_sync(logged.pipe(effect.provide_service(HttpServerRequest, request)))
    assert spans == [["http.span"], ["http.span"]]


# --- tracer -----------------------------------------------------------------------


class _Recording:
    def __init__(self) -> None:
        self.spans: list[NativeSpan] = []

    def span(self, request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        self.spans.append(span)
        return span

    @property
    def tracer(self) -> Tracer:
        return Tracer.make(self.span)


def _traced(
    app: fx.Effect[HttpServerResponse, Any, Any],
    request: ServerRequest,
    recording: _Recording | None = None,
) -> fx.Effect[HttpServerResponse, Any, Any]:
    traced = tracer(app).pipe(effect.provide_service(HttpServerRequest, request))
    if recording is None:
        return traced
    return traced.pipe(effect.provide_service(CurrentTracer, recording.tracer))


def test_restores_parent_span_and_ends_the_span_if_interrupted_before_handler_registration() -> (
    None
):
    """restores ParentSpan and ends the span if interrupted before handler registration"""
    spans: list[NativeSpan] = []
    seen: dict[str, Context[Any]] = {}

    def interrupting(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        fiber = fx.Fiber.get_current()
        assert fiber is not None
        fiber.interrupt_as_unsafe(None)
        return span

    def remember(name: str) -> fx.Effect[None]:
        return _WithFiber(lambda fiber: effect.sync(lambda: seen.__setitem__(name, fiber._context)))

    program = (
        remember("original")
        .and_then(tracer(effect.succeed(server_response.empty())))
        .on_exit(lambda _: remember("observed"))
        .pipe(effect.provide_service(HttpServerRequest, _request()))
        .pipe(effect.provide_service(CurrentTracer, Tracer.make(interrupting)))
    )
    exit = fx.run_sync_exit(program)
    assert isinstance(exit, Failure)
    assert seen["observed"] is seen["original"]
    assert isinstance(spans[0].status, Ended)


def test_restores_the_parent_span_context_identity() -> None:
    """restores the ParentSpan context identity"""
    seen: list[Context[Any]] = []

    def app(fiber: Any) -> fx.Effect[HttpServerResponse]:
        seen.append(fiber._context)
        assert fiber.get_ref(ParentSpan) is not None
        return effect.succeed(server_response.empty())

    def program(fiber: Any) -> fx.Effect[tuple[Context[Any], Context[Any]], Any, Any]:
        before = fiber._context
        return tracer(_WithFiber[HttpServerResponse, Any, Any](app)).and_then(
            _WithFiber(lambda after: effect.succeed((before, after._context)))
        )

    before, after = fx.run_sync(
        _WithFiber(program).pipe(effect.provide_service(HttpServerRequest, _request())).or_die()
    )
    assert seen[0] is not before
    assert after is before


def test_records_attributes_for_sampled_spans() -> None:
    """records attributes for sampled spans"""
    recording = _Recording()
    request = _request(
        "https://localhost:3000/todos/1?foo=bar",
        method="POST",
        headers={
            "user-agent": "test-agent",
            "x-request": "request",
            "x-request-secret": "request-secret",
        },
    )
    response = server_response.empty(
        status=201, headers={"x-response": "response", "x-response-secret": "response-secret"}
    )
    fx.run_sync(
        _traced(effect.succeed(response), request, recording)
        .pipe(
            effect.provide_service(
                headers_.CurrentRedactedNames, ("x-request-secret", "x-response-secret")
            )
        )
        .or_die()
    )
    span = recording.spans[0]
    assert span.sampled
    attributes = span.attributes
    assert attributes["http.request.method"] == "POST"
    assert attributes["url.path"] == "/todos/1"
    assert attributes["url.query"] == "foo=bar"
    assert attributes["user_agent.original"] == "test-agent"
    assert "http.request.header.x-request" not in attributes
    assert "http.request.header.x-request-secret" not in attributes
    assert attributes["http.response.status_code"] == 201
    assert "http.response.header.x-response" not in attributes
    assert "http.response.header.x-response-secret" not in attributes


def test_redacts_sensitive_query_params_in_url_attributes() -> None:
    """redacts sensitive query params in url attributes"""
    recording = _Recording()
    urls: list[str] = []
    app = HttpServerRequest().map(
        lambda request: (urls.append(request.url), server_response.empty())[1]
    )
    request = _request("http://localhost/todos?sig=sig-secret&foo=bar")
    fx.run_sync(_traced(app, request, recording).or_die())
    attributes = recording.spans[0].attributes
    assert attributes["url.full"] == "http://localhost/todos?sig=REDACTED&foo=bar"
    assert attributes["url.query"] == "sig=REDACTED&foo=bar"
    assert urls == ["/todos?sig=sig-secret&foo=bar"]


def test_skips_attributes_for_unsampled_spans() -> None:
    """skips attributes for unsampled spans"""
    recording = _Recording()
    app = effect.succeed(server_response.empty(status=204))
    fx.run_sync(
        _traced(app, _request("http://localhost:3000/unsampled"), recording)
        .pipe(effect.provide_service(MinimumTraceLevel, LogLevel.FATAL))
        .or_die()
    )
    span = recording.spans[0]
    assert not span.sampled
    assert span.attributes == {}
    assert isinstance(span.status, Ended)


def test_ends_the_span_and_restores_the_context_when_the_app_is_interrupted() -> None:
    """ends the span and restores the context when the app is interrupted"""
    recording = _Recording()
    parents: list[object] = []
    finalizer = _WithFiber(
        lambda fiber: effect.sync(lambda: parents.append(fiber.get_ref(ParentSpan)))
    )
    child = (
        tracer(effect.never)
        .ensuring(finalizer)
        .pipe(effect.provide_service(HttpServerRequest, _request("http://localhost:3000/slow")))
        .pipe(effect.provide_service(CurrentTracer, recording.tracer))
    )

    @fx.fn
    def program():
        fiber = yield from child.fork()
        yield from effect.yield_now()
        yield from fiber.interrupt()
        yield from effect.yield_now()

    fx.run_sync(program())
    assert len(recording.spans) == 1
    assert isinstance(recording.spans[0].status, Ended)
    assert parents == [None]


def _span_error(span: Any) -> object:
    assert isinstance(span.status, Ended)
    exit = span.status.exit
    assert isinstance(exit, Failure)
    reason = exit.cause.reasons[0]
    assert isinstance(reason, Fail)
    return reason.error


def test_fails_the_span_for_a_rendered_599_without_changing_the_response() -> None:
    """fails the span for a rendered 599 without changing the response"""
    spans: list[Any] = []
    request = _request("http://localhost:3000/error")
    response = server_response.empty(status=599)
    app = (
        current_span()
        .flat_map(lambda span: (spans.append(span), effect.fail("handler failed"))[1])
        .catch_all(lambda _: effect.succeed(response))
    )
    recording = _Recording()
    result = fx.run_sync(_traced(app, request, recording).or_die())
    assert result is response
    error = _span_error(spans[0])
    assert isinstance(error, HttpServerError)
    assert isinstance(error.reason, ResponseError)
    assert error.reason.request is request
    assert error.reason.response is response


def test_fails_a_native_span_without_changing_a_returned_500_response() -> None:
    """fails a native span without changing a returned 500 response"""
    spans: list[Any] = []
    request = _request("http://localhost:3000/native")
    response = server_response.empty(status=500)
    app = current_span().map(lambda span: (spans.append(span), response)[1])
    exit = fx.run_sync(_traced(app, request).exit())
    assert isinstance(exit, Success)
    assert exit.value is response
    error = _span_error(spans[0])
    assert isinstance(error, HttpServerError)
    assert isinstance(error.reason, ResponseError)
    assert error.reason.response is response


def test_preserves_the_stream_failure_when_the_sent_response_is_500() -> None:
    """preserves the stream failure when the sent response is 500"""
    recording = _Recording()
    request = _request("http://localhost:3000/stream")
    response = server_response.empty(status=500, headers={"content-type": "text/event-stream"})
    stream_error = RuntimeError("stream failed")
    # Once headers are sent, the platform attaches the response to the
    # stream failure so the server can finish the request correctly.
    cause = fail_cause(stream_error) + die_cause(UnhandledError(response))
    exit = fx.run_sync(_traced(effect.fail_cause(cause), request, recording).exit())
    assert isinstance(exit, Failure)
    assert exit.cause == cause
    span = recording.spans[0]
    assert span.attributes["http.response.status_code"] == 500
    assert isinstance(span.status, Ended)
    span_exit = span.status.exit
    assert isinstance(span_exit, Failure)
    errors = [reason.error for reason in span_exit.cause.reasons if isinstance(reason, Fail)]
    assert errors == [stream_error]


# --- forwarded headers ------------------------------------------------------------------

_TRUSTED = [ip_network.from_string_unsafe("10.0.0.0/8")]


def _observe(middleware: Any, peer: str, headers: dict[str, str]) -> object:
    def respond(request: ServerRequest) -> HttpServerResponse:
        url = to_url(request)
        return server_response.json_unsafe(
            {
                "remoteAddress": request.remote_address,
                "host": request.headers.get("host"),
                "url": None if url is None else url.geturl(),
            }
        )

    app = middleware(HttpServerRequest().map(respond))
    request = _request("http://app.test/a", headers={"host": "app.test", **headers}).modify(
        remote_address=peer
    )
    response = fx.run_sync(app.pipe(effect.provide_service(HttpServerRequest, request)).or_die())

    async def main() -> object:
        return await response_to_web(response).json()

    return asyncio.run(main())


@pytest.mark.parametrize(
    ("name", "peer", "headers", "expected"),
    [
        (
            "ignores forwarded metadata from an untrusted peer",
            "203.0.113.9",
            {
                "x-forwarded-for": "6.6.6.6",
                "x-forwarded-host": "evil.test",
                "x-forwarded-proto": "https",
            },
            {"remoteAddress": "203.0.113.9", "host": "app.test", "url": "http://app.test/a"},
        ),
        (
            "selects the rightmost untrusted hop and its aligned host and proto",
            "10.0.0.1",
            {
                "x-forwarded-for": "6.6.6.6, 198.51.100.7, 10.0.0.2",
                "x-forwarded-host": "evil.test, b.test, internal.test",
                "x-forwarded-proto": "http, https, http",
            },
            {"remoteAddress": "198.51.100.7", "host": "b.test", "url": "https://b.test/a"},
        ),
        (
            "keeps the transport host when X-Forwarded-Host does not align with X-Forwarded-For",
            "10.0.0.1",
            {"x-forwarded-for": "198.51.100.7", "x-forwarded-host": "a.test, b.test"},
            {"remoteAddress": "198.51.100.7", "host": "app.test", "url": "http://app.test/a"},
        ),
        (
            "stops at an invalid entry instead of skipping to attacker-controlled entries",
            "10.0.0.1",
            {
                "x-forwarded-for": "6.6.6.6, unknown, 10.0.0.2",
                "x-forwarded-host": "a.test, b.test, c.test",
            },
            {"remoteAddress": "10.0.0.1", "host": "app.test", "url": "http://app.test/a"},
        ),
    ],
)
def test_x_forwarded_headers(
    name: str, peer: str, headers: dict[str, str], expected: dict[str, str]
) -> None:
    """xForwardedHeaders $name"""
    del name
    assert _observe(x_forwarded_headers(_TRUSTED), peer, headers) == expected


def test_authorizes_against_the_transport_peer_not_an_address_resolved_by_earlier_middleware() -> (
    None
):
    """authorizes against the transport peer, not an address resolved by earlier middleware"""
    outer = x_forwarded_headers(_TRUSTED)
    inner = x_forwarded_headers([ip_network.from_string_unsafe("198.51.100.0/24")])

    def both(app: Any) -> Any:
        return outer(inner(app))

    observed = _observe(
        both,
        "10.0.0.1",
        {
            "x-forwarded-for": "6.6.6.6, 198.51.100.7",
            "x-forwarded-host": "evil.test, b.test",
            "x-forwarded-proto": "https, http",
        },
    )
    assert observed == {
        "remoteAddress": "198.51.100.7",
        "host": "b.test",
        "url": "http://b.test/a",
    }
