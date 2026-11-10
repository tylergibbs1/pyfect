"""Ports of Effect's ``http/HttpClient.test.ts``.

Each test's docstring is the Effect test title. ``HttpClientResponse.fromWeb
(request, new Response(body, init))`` is ``response.make(request, body,
status=..., headers=...)``; a backend given to ``client.make`` takes the
request, the URL, the abort signal and the fiber. ``Tracer.make({ span })``
is ``Tracer(span)``, provided with ``with_tracer``. ``response.arrayBuffer``
is ``response.bytes_``; ``HttpClient.catch`` is ``catch_all``.

Adapted, with the reason:

- ``preserves a raw large integer through schemaBodyJson reviver context``:
  Python's JSON parser keeps every integer exact, so the reviver writes the
  parsed ``int`` out (JavaScript's reviver reads ``context.source``).
- ``reads cookies when Headers has no getSetCookie``: there is no web
  ``Headers`` without ``getSetCookie``; a response without ``set-cookie``
  headers has no cookies.

Omitted, with the reason:

- ``does not retain unread responses without FinalizationRegistry``,
  ``does not throw when unread response cleanup runs outside a Cloudflare
  request``, ``keeps unread response cleanup when toWeb finds no Web
  response``: JavaScript runtime registries and web ``Response`` objects;
  an unread response here is aborted by ``weakref.finalize`` (checked in
  ``tests/test_http_client.py``).

The ``withRateLimiter`` and ``withCircuitBreaker`` blocks are in
``test_http_client_resilience.py``.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import clock, testing
from pyfect import schema as S
from pyfect import stream as stream_
from pyfect.duration import Duration, millis
from pyfect.errors import TimeoutException
from pyfect.exit import Failure
from pyfect.http import client as c
from pyfect.http import headers as h
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http import url as u
from pyfect.http import url_params as up
from pyfect.http.abort import AbortSignal
from pyfect.http.error import EncodeError, HttpClientError, StatusCodeError, TransportError
from pyfect.redacted import Redacted
from pyfect.schedule import spaced
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

type Handler = Callable[[req.HttpClientRequest], res.HttpClientResponse]


def _client(handler: Handler) -> c.HttpClientService[HttpClientError]:
    return c.make(lambda request, _url, _signal, _fiber: fx.sync(lambda: handler(request)))


def _status_client(status: int) -> tuple[list[int], c.HttpClientService[HttpClientError]]:
    attempts = [0]

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        attempts[0] += 1
        return res.make(request, status=status)

    return attempts, _client(handle)


def _sequence_client(
    responses: list[tuple[int, dict[str, str]]],
) -> tuple[list[int], c.HttpClientService[HttpClientError]]:
    attempts = [0]

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        status, headers = responses[min(attempts[0], len(responses) - 1)]
        attempts[0] += 1
        return res.make(request, status=status, headers=headers)

    return attempts, _client(handle)


def _redirect_client(
    status: int, location: str | list[str]
) -> tuple[list[req.HttpClientRequest], c.HttpClientService[HttpClientError]]:
    locations = [location] if isinstance(location, str) else location
    requests: list[req.HttpClientRequest] = []

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        requests.append(request)
        if len(requests) <= len(locations):
            return res.make(
                request, status=status, headers={"location": locations[len(requests) - 1]}
            )
        return res.make(request)

    return requests, _client(handle).follow_redirects()


def _recording_tracer() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


def _only(spans: list[NativeSpan]) -> NativeSpan:
    assert len(spans) == 1
    return spans[0]


@testing.effect
def test_stream_after_json():
    """preserves the response stream after JSON serialization"""
    response = res.make(
        req.get("https://example.com"),
        "data: hello\n\n",
        headers={"content-type": "text/event-stream"},
    )
    response.to_json()
    chunks = yield from response.stream.run_collect()
    assert b"".join(chunks) == b"data: hello\n\n"


class _Value(TypedDict):
    value: str


class _Body(TypedDict):
    body: _Value


@testing.effect
def test_revivers():
    """applies JSON revivers to response schema decoders"""

    def make() -> res.HttpClientResponse:
        return res.make(req.get("https://example.com"), '{"value":"original"}')

    def reviver(key: str, value: object) -> object:
        return "revived" if key == "value" else value

    decoded = yield from res.schema_body_json(S.Struct(_Value), reviver=reviver)(make())
    assert decoded == {"value": "revived"}
    wrapped = yield from res.schema_json(S.Struct(_Body), reviver=reviver)(make())
    assert wrapped == {"body": {"value": "revived"}}


class _AB(TypedDict):
    a: str
    b: str


class _WithBody(TypedDict):
    body: _AB


class _WithHeaders(TypedDict):
    headers: _AB


@testing.effect
def test_parse_options():
    """forwards parse options to response schema decoders"""
    response = res.make(req.get("https://example.com"), "{}")
    error = yield from res.schema_json(S.Struct(_WithBody), errors="all")(response).flip()
    assert error.message == 'Missing key\n  at ["body"]["a"]\nMissing key\n  at ["body"]["b"]'


@testing.effect
def test_parse_options_no_body():
    """forwards parse options to response schema decoders without a body"""
    response = res.make(req.get("https://example.com"))
    error = yield from res.schema_no_body(S.Struct(_WithHeaders), errors="all")(response).flip()
    assert error.message == 'Missing key\n  at ["headers"]["a"]\nMissing key\n  at ["headers"]["b"]'


@testing.effect
def test_large_integer_reviver():
    """preserves a raw large integer through schemaBodyJson reviver context"""
    response = res.make(req.get("https://example.com"), '{"value":9223372036854775807}')

    def reviver(key: str, value: object) -> object:
        return str(value) if key == "value" else value

    decoded = yield from res.schema_body_json(S.Struct(_Value), reviver=reviver)(response)
    assert decoded["value"] == "9223372036854775807"


@testing.effect
def test_source_bytes_after_text():
    """preserves source bytes after reading response text"""
    response = res.make(req.get("https://example.com"), bytes([0xEF, 0xBB, 0xBF, 0x61]))
    assert (yield from response.text) == "a"
    assert list((yield from response.bytes_)) == [0xEF, 0xBB, 0xBF, 0x61]


# tracer


@testing.effect
def test_tracer_omits_headers():
    """omits request and response headers by default"""
    tracer, spans = _recording_tracer()
    client = _client(lambda request: res.make(request, headers={"x-response-default": "response"}))
    yield from client.get("http://test/", headers={"x-request-default": "request"}).with_tracer(
        tracer
    )
    attributes = _only(spans).attributes
    assert "http.request.header.x-request-default" not in attributes
    assert "http.response.header.x-response-default" not in attributes


@testing.effect
def test_tracer_filters_headers():
    """filters request and response header span attributes"""
    tracer, spans = _recording_tracer()
    client = _client(
        lambda request: res.make(
            request, headers={"x-response-drop": "drop", "x-response-keep": "keep"}
        )
    )
    yield from (
        client.get("http://test/", headers={"x-request-drop": "drop", "x-request-keep": "keep"})
        .with_tracer(tracer)
        .pipe(fx.provide_service(c.TracerHeaderFilter, lambda name, _phase: name.endswith("-keep")))
    )
    attributes = _only(spans).attributes
    assert "http.request.header.x-request-drop" not in attributes
    assert attributes["http.request.header.x-request-keep"] == "keep"
    assert "http.response.header.x-response-drop" not in attributes
    assert attributes["http.response.header.x-response-keep"] == "keep"


@testing.effect
def test_tracer_filters_by_phase():
    """filters the same header name independently by phase"""
    tracer, spans = _recording_tracer()
    client = _client(lambda request: res.make(request, headers={"x-phase-filter": "response"}))
    yield from (
        client.get("http://test/", headers={"x-phase-filter": "request"})
        .with_tracer(tracer)
        .pipe(fx.provide_service(c.TracerHeaderFilter, lambda _name, phase: phase == "response"))
    )
    attributes = _only(spans).attributes
    assert "http.request.header.x-phase-filter" not in attributes
    assert attributes["http.response.header.x-phase-filter"] == "response"


def _url_capturing_client() -> tuple[list[str], c.HttpClientService[HttpClientError]]:
    sent: list[str] = []

    def send(
        request: req.HttpClientRequest, url: fx.Url, _signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        sent.append(u.href(url))
        return fx.succeed(res.make(request))

    return sent, c.make(send)


@testing.effect
def test_tracer_redacts_query():
    """redacts sensitive query params in url attributes"""
    tracer, spans = _recording_tracer()
    sent, client = _url_capturing_client()
    yield from client.get(
        "http://test/path?Signature=sig-secret&page=1",
        url_params={"X-Goog-Signature": "goog-secret"},
    ).with_tracer(tracer)
    attributes = _only(spans).attributes
    assert (
        attributes["url.full"]
        == "http://test/path?Signature=REDACTED&page=1&X-Goog-Signature=REDACTED"
    )
    assert attributes["url.query"] == "Signature=REDACTED&page=1&X-Goog-Signature=REDACTED"
    assert sent == ["http://test/path?Signature=sig-secret&page=1&X-Goog-Signature=goog-secret"]


@testing.effect
def test_tracer_redacts_userinfo():
    """redacts userinfo in url.full"""
    tracer, spans = _recording_tracer()
    yield from _client(res.make).get("http://user:password@test/path").with_tracer(tracer)
    assert _only(spans).attributes["url.full"] == "http://REDACTED:REDACTED@test/path"


@testing.effect
def test_tracer_redacts_redacted_params():
    """redacts Redacted query params in url attributes"""
    tracer, spans = _recording_tracer()
    sent, client = _url_capturing_client()
    request = (
        req.get("http://test/path?page=1#frag")
        .append_url_param("remote", Redacted("param-secret"))
        .append_url_param("\ud800", Redacted("surrogate-secret"))
        .append_url_param("q", "visible")
    )
    yield from client.execute(request).with_tracer(tracer)
    attributes = _only(spans).attributes
    assert (
        attributes["url.full"]
        == "http://test/path?page=1&remote=REDACTED&%EF%BF%BD=REDACTED&q=visible#frag"
    )
    assert attributes["url.query"] == "page=1&remote=REDACTED&%EF%BF%BD=REDACTED&q=visible"
    assert sent == [
        "http://test/path?page=1&remote=param-secret&%EF%BF%BD=surrogate-secret&q=visible#frag"
    ]


def _capturing_client() -> tuple[list[req.HttpClientRequest], c.HttpClientService[HttpClientError]]:
    sent: list[req.HttpClientRequest] = []

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        sent.append(request)
        return res.make(request)

    return sent, _client(handle)


@testing.effect
def test_sends_trace_headers():
    """sends trace headers by default"""
    sent, client = _capturing_client()
    yield from client.get("http://test/")
    assert isinstance(sent[0].headers.get("b3"), str)
    assert isinstance(sent[0].headers.get("traceparent"), str)


@testing.effect
def test_propagation_disabled():
    """omits trace headers when propagation is disabled and keeps the client span"""
    sent, client = _capturing_client()
    tracer, spans = _recording_tracer()
    yield from (
        client.get("http://test/")
        .with_tracer(tracer)
        .pipe(fx.provide_service(c.TracerPropagationEnabled, False))
    )
    assert sent[0].headers.get("b3") is None
    assert sent[0].headers.get("traceparent") is None
    assert len(spans) == 1


# HttpClientError


@testing.effect
def test_error_hides_redacted_params():
    """does not expose Redacted query params"""
    client = _client(lambda request: res.make(request, status=500)).filter_status_ok()
    error = yield from client.get(
        "http://test/path", url_params={"remote": Redacted("param-secret"), "q": "visible"}
    ).flip()
    for output in (str(error.to_json()), str(error), repr(error)):
        assert "param-secret" not in output
    assert "http://test/path" in str(error.to_json())


@testing.effect
def test_error_to_json_hides_secrets():
    """does not expose request headers, query params or body in toJSON"""
    client = c.make(
        lambda request, _url, _signal, _fiber: fx.fail(HttpClientError(TransportError(request)))
    )
    request = (
        req.post("http://test/join")
        .set_header("x-token", "header-secret")
        .set_url_param("token", "query-secret")
        .body_json_unsafe({"JoinToken": "body-secret"})
    )
    error = yield from client.execute(request).flip()
    json = str(error.to_json())
    for secret in ("header-secret", "query-secret", "body-secret"):
        assert secret not in json
    assert error.message == "Transport error (POST http://test/join)"


@testing.effect
def test_error_current_redacted_names():
    """redacts query params in messages using the current redacted names"""

    def message() -> str:
        request = req.get("http://test/path?token=token-secret&sig=sig-visible")
        return HttpClientError(TransportError(request)).message

    text = yield from fx.sync(message).pipe(fx.provide_service(up.CurrentRedactedNames, ("token",)))
    assert text == "Transport error (GET http://test/path?token=REDACTED&sig=sig-visible)"


# followRedirects


@testing.effect
def test_redirect_preprocessing_recovery():
    """preserves preprocessing error recovery"""
    request = req.get("https://origin.test/")
    recovered = res.make(request, status=418)
    client = (
        _client(res.make)
        .map_request_effect(lambda _: fx.fail("preprocessing failed"))
        .catch_all(lambda _: fx.succeed(recovered))
        .follow_redirects()
    )
    assert (yield from client.execute(request)) is recovered


@testing.effect
def test_redirect_same_origin_credentials():
    """preserves credential headers on same-origin redirects"""
    requests, client = _redirect_client(302, "https://origin.test/destination")
    yield from client.get(
        "https://origin.test/start",
        headers={"Authorization": "Bearer secret", "Cookie": "session=secret"},
    )
    assert requests[1].headers["authorization"] == "Bearer secret"
    assert requests[1].headers["cookie"] == "session=secret"


@testing.effect
def test_redirect_cross_origin_credentials():
    """strips credential headers on cross-origin redirects"""
    requests, client = _redirect_client(302, "https://redirect.test/destination")
    yield from client.get(
        "https://origin.test/start",
        headers={
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "Proxy-Authorization": "Basic secret",
            "X-Test": "retained",
        },
    )
    redirected = requests[1].headers
    assert "authorization" not in redirected
    assert "cookie" not in redirected
    assert "proxy-authorization" not in redirected
    assert redirected["x-test"] == "retained"


@testing.effect
def test_redirect_scheme_downgrade():
    """strips credential headers on scheme downgrade redirects"""
    # pyfect does not follow a downgrade at all (decisions table); Effect
    # follows it without the credential headers.
    requests, client = _redirect_client(302, "http://origin.test/destination")
    response = yield from client.get(
        "https://origin.test/start",
        headers={
            "Authorization": "Bearer secret",
            "Cookie": "session=secret",
            "Proxy-Authorization": "Basic secret",
        },
    )
    assert response.status == 302
    assert len(requests) == 1


@testing.effect
def test_redirect_relative():
    """resolves relative locations against the current hop"""
    requests, client = _redirect_client(302, ["../next/step", "destination"])
    yield from client.get(
        "https://origin.test/path/start", headers={"Authorization": "Bearer secret"}
    )
    assert requests[2].url == "https://origin.test/next/destination"
    assert requests[2].headers["authorization"] == "Bearer secret"


@testing.effect
def test_redirect_keeps_query_encoding():
    """follows the location without re-encoding its query"""
    requests, client = _redirect_client(302, "https://origin.test/dest?q=caf%E9&sig=a%20b&flag#new")
    yield from client.get("https://origin.test/start", url_params={"old": "1"}, hash="old")
    assert requests[1].url == "https://origin.test/dest?q=caf%E9&sig=a%20b&flag"
    assert up.to_string(requests[1].url_params) == ""
    assert requests[1].hash == "new"


@testing.effect
def test_redirect_invalid_location():
    """returns the redirect response when the location is invalid"""
    requests, client = _redirect_client(302, "http://exa mple.com/")
    response = yield from client.get("https://origin.test/start")
    assert response.status == 302
    assert response.headers["location"] == "http://exa mple.com/"
    assert len(requests) == 1


@testing.effect
def test_redirect_303():
    """switches 303 requests to GET and drops the body"""
    requests, client = _redirect_client(303, "/destination")
    yield from client.execute(
        req.post("https://origin.test/start")
        .body_text("payload")
        .set_headers(
            {
                "content-encoding": "identity",
                "content-language": "en",
                "content-location": "/original",
            }
        )
    )
    redirected = requests[1]
    assert redirected.method == "GET"
    assert redirected.body.tag == "Empty"
    assert "content-type" not in redirected.headers
    assert "content-length" not in redirected.headers
    assert "content-encoding" not in redirected.headers
    assert "content-language" not in redirected.headers
    assert "content-location" not in redirected.headers


@pytest.mark.parametrize("status", [301, 302])
@testing.effect
def test_redirect_post_to_get(status: int):
    """switches POST to GET on %s redirects"""
    requests, client = _redirect_client(status, "/destination")
    yield from client.execute(req.post("https://origin.test/start").body_text("payload"))
    assert requests[1].method == "GET"
    assert requests[1].body.tag == "Empty"


@pytest.mark.parametrize("status", [301, 302])
@testing.effect
def test_redirect_keeps_put(status: int):
    """preserves non-POST methods on %s redirects"""
    requests, client = _redirect_client(status, "/destination")
    yield from client.execute(req.put("https://origin.test/start").body_text("payload"))
    assert requests[1].method == "PUT"
    assert requests[1].body.tag == "Bytes"


# retryTransient


@testing.effect
def test_retry_errors_and_responses():
    """retries transient responses with retryOn errors-and-responses"""
    attempts, client = _status_client(503)
    yield from (
        client.retry_transient(retry_on="errors-and-responses", times=2)
        .get("http://test/")
        .ignore()
    )
    assert attempts[0] == 3


@testing.effect
def test_retry_errors_only():
    """does not retry transient responses with retryOn errors-only"""
    attempts, client = _status_client(503)
    yield from client.retry_transient(retry_on="errors-only", times=2).get("http://test/").ignore()
    assert attempts[0] == 1


@pytest.mark.parametrize(
    ("header", "status", "delay", "scheduled"),
    [
        pytest.param("1", 503, 1.0, False, id="seconds"),
        pytest.param("300", 429, 300.0, False, id="a five-minute Retry-After"),
        pytest.param("date", 429, 30.0, False, id="HTTP date on an errors-only retry"),
        pytest.param("5", 503, 60.0, True, id="a longer schedule"),
        pytest.param(None, 503, 0.0, False, id="no header"),
        pytest.param("-5", 503, 0.0, False, id="a negative Retry-After"),
        pytest.param("1.5", 503, 0.0, False, id="a fractional Retry-After"),
    ],
)
@testing.effect
def test_retry_delay(header: str | None, status: int, delay: float, scheduled: bool):
    """honors the retry delay for $name"""
    now = yield from clock.current_time_millis()
    retry_after = (
        h.format_http_date(datetime.fromtimestamp(now / 1000 + 30, UTC))
        if header == "date"
        else header
    )
    attempts, client = _sequence_client(
        [(status, {} if retry_after is None else {"retry-after": retry_after}), (200, {})]
    )
    base = client.filter_status_ok() if header == "date" else client
    retrying = base.retry_transient(
        retry_on="errors-only" if header == "date" else "errors-and-responses",
        times=1,
        schedule=spaced("1 minute") if scheduled else None,
    )
    fiber = yield from retrying.get("http://test/").fork(start_immediately=True)
    if delay > 0:
        yield from testing.adjust(Duration(delay - 0.001))
        assert attempts[0] == 1
        yield from testing.adjust("1 millis")
    assert (yield from fiber.join()).status == 200


def test_classifies_transient() -> None:
    """classifies transient responses and errors"""
    request = req.get("http://test/")
    responses = [
        res.make(request, status=status) for status in (200, 404, 408, 429, 500, 501, 502, 503, 504)
    ]
    status_errors = [HttpClientError(StatusCodeError(request, response)) for response in responses]
    expected = [False, False, True, True, True, False, True, True, True]
    assert [c.is_transient_response(response) for response in responses] == expected
    assert [c.is_transient_error(error) for error in status_errors] == expected
    assert [
        c.is_transient_error(error)
        for error in (
            TimeoutException(millis(0)),
            HttpClientError(TransportError(request)),
            HttpClientError(EncodeError(request)),
            Exception("boom"),
        )
    ] == [True, True, False, False]


# timeout


def _squashed_failure(exit: fx.Exit[Any, Any] | None) -> object:
    assert isinstance(exit, Failure)
    return exit.cause.squash()


@testing.effect
def test_timeout_transport_error():
    """fails with a TransportError and aborts the request"""
    signals: list[AbortSignal] = []

    def send(
        _request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.never

    client = c.make(send).timeout("5 seconds")
    fiber = yield from client.get("http://test/").fork(start_immediately=True)
    yield from testing.adjust("5 seconds")
    error = _squashed_failure((yield from fiber.await_exit()))
    assert isinstance(error, HttpClientError)
    assert isinstance(error.reason, TransportError)
    assert error.request.url == "http://test/"
    assert isinstance(error.cause, TimeoutException)
    assert "timed out" in error.message
    assert signals[0].aborted


def _slow_client(
    first: fx.Effect[Any, Any],
) -> tuple[list[int], c.HttpClientService[HttpClientError]]:
    """Attempt 0 runs ``first``; later attempts answer 200 after 900 millis."""
    attempts = [0]

    def send(
        request: req.HttpClientRequest, *_: object
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        def attempt() -> fx.Effect[res.HttpClientResponse, HttpClientError]:
            n = attempts[0]
            attempts[0] += 1
            if n == 0:
                return first.flat_map(lambda _: fx.fail(HttpClientError(TransportError(request))))
            return clock.sleep("900 millis").as_(res.make(request))

        return fx.suspend(attempt)

    return attempts, c.make(send)


@testing.effect
def test_timeout_fresh_budget_per_attempt():
    """gives each retryTransient attempt a fresh budget"""
    attempts, base = _slow_client(fx.never)
    client = base.timeout("1 second").retry_transient(times=1)
    fiber = yield from client.get("http://test/").fork(start_immediately=True)
    yield from testing.adjust("1 second")
    assert attempts[0] == 2
    yield from testing.adjust("900 millis")
    assert (yield from fiber.join()).status == 200


@testing.effect
def test_timeout_bounds_retry_loop():
    """bounds the whole retry loop when applied after retryTransient"""
    attempts, base = _slow_client(clock.sleep("600 millis"))
    client = base.retry_transient(times=1).timeout("1 second")
    fiber = yield from client.get("http://test/").fork(start_immediately=True)
    yield from testing.adjust("1 second")
    exit = fiber.poll_unsafe()
    assert attempts[0] == 2
    error = _squashed_failure(exit)
    assert isinstance(error, HttpClientError)
    assert isinstance(error.cause, TimeoutException)


# stream


@testing.effect
def test_stream_ends_early_aborts():
    """aborts the request when the response stream ends early"""
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: fx.Url, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, stream_.succeed(b"\x01").forever()))

    response = yield from c.make(send).get("http://test/")
    chunks = yield from response.stream.take(5).run_collect()
    assert len(chunks) == 5
    assert signals[0].aborted


def test_cookies_without_set_cookie() -> None:
    """reads cookies when Headers has no getSetCookie"""
    response = res.make(req.get("http://localhost"), headers={"content-type": "text/plain"})
    assert response.cookies.is_empty()
