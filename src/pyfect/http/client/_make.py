"""Building a client from a send function: URL building, tracing,
interruption (Effect's ``HttpClient.make``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from typing import Any, Literal, final
from urllib.parse import SplitResult

from pyfect._core import Effect, _WithFiber
from pyfect._effect_resources import _call_user
from pyfect._fiber import Fiber
from pyfect._js import to_well_formed
from pyfect._primitives import uninterruptible_mask
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.clock import Clock
from pyfect.context import Reference
from pyfect.effect import fail, provide_service, succeed, suspend, sync
from pyfect.effect import fail_cause as fail_with_cause
from pyfect.exit import Failure
from pyfect.http import headers as _headers
from pyfect.http import trace_context
from pyfect.http import url as _url
from pyfect.http import url_params as _url_params
from pyfect.http.abort import AbortController, AbortSignal
from pyfect.http.client._service import HttpClientService
from pyfect.http.error import HttpClientError, InvalidUrlError, StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse, _InterruptibleResponse
from pyfect.result import Err, Ok
from pyfect.scope import Scope, add_finalizer
from pyfect.tracer import DisablePropagation, Span, TracerTimingEnabled
from pyfect.tracer._spans import in_parent_span, use_span

type Phase = Literal["request", "response"]
type Send = Callable[
    [HttpClientRequest, SplitResult, AbortSignal, Fiber[Any, Any]],
    Effect[HttpClientResponse, HttpClientError],
]
"""What a client backend implements: send the request to the URL (built
from its ``url``, ``url_params`` and ``hash``), stopping when the signal
aborts."""


class TracerDisabledWhen(Reference[Callable[[HttpClientRequest], bool]]):
    """Requests sent without a span (and without trace headers)."""

    @classmethod
    def default(cls) -> Callable[[HttpClientRequest], bool]:
        return lambda _request: False


class TracerHeaderFilter(Reference[Callable[[str, Phase], bool]]):
    """The headers recorded as span attributes (``http.request.header.x``),
    by name and phase. None by default."""

    @classmethod
    def default(cls) -> Callable[[str, Phase], bool]:
        return lambda _name, _phase: False


class TracerPropagationEnabled(Reference[bool]):
    """Whether requests carry ``traceparent`` and ``b3`` headers."""

    @classmethod
    def default(cls) -> bool:
        return True


class SpanNameGenerator(Reference[Callable[[HttpClientRequest], str]]):
    """The name of a request's span; its method by default."""

    @classmethod
    def default(cls) -> Callable[[HttpClientRequest], str]:
        return lambda request: request.method


@final
class _Scoped:
    """The controller ``with_scope`` aborts when its scope closes, for the
    one request it sends (Effect keys it on the request)."""

    __slots__ = ("controller", "request")

    def __init__(self, request: HttpClientRequest) -> None:
        self.request = request
        self.controller = AbortController()

    def controller_for(self, request: HttpClientRequest) -> AbortController | None:
        return self.controller if request is self.request else None


class _ScopedAbort(Reference[_Scoped | None]):
    @classmethod
    def default(cls) -> _Scoped | None:
        return None


def scoped[A, E, R](
    sending: Effect[A, E, R], request: HttpClientRequest
) -> Effect[A, E, R | Scope]:
    """Send ``request`` (by ``sending``) with a controller aborted when the
    scope closes."""

    def run() -> Effect[A, E, R | Scope]:
        tie = _Scoped(request)
        tied: Effect[A, E, R] = sending.pipe(provide_service(_ScopedAbort, tie))
        return add_finalizer(lambda _exit: sync(tie.controller.abort)).and_then(tied)

    return suspend(run)


_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _add_url_attributes(span: Span, url: SplitResult, redacted: Sequence[_headers.Pattern]) -> None:
    query = _url_params.redact_url(f"?{url.query}" if url.query else "", redacted)[1:]
    span.attribute("url.full", _url_params.redact_url(_url.href(url), redacted))
    span.attribute("url.path", url.path)
    if query:
        span.attribute("url.query", query)
    span.attribute("url.scheme", url.scheme)
    hostname = url.hostname
    if hostname:
        span.attribute("server.address", hostname)
        port = url.port if url.port is not None else _DEFAULT_PORTS.get(url.scheme)
        if port is not None:
            span.attribute("server.port", port)


def _redacted_names(
    params: _url_params.UrlParams, names: Sequence[_headers.Pattern]
) -> Sequence[_headers.Pattern]:
    keys = [to_well_formed(key) for key, value in params if not isinstance(value, str)]
    return names if not keys else (*names, *keys)


def _add_header_attributes(
    span: Span,
    phase: Phase,
    headers: _headers.Headers,
    accept: Callable[[str, Phase], bool],
    redacted: Sequence[_headers.Pattern],
) -> None:
    for name, value in headers.items():
        if accept(name, phase):
            shown = "<redacted>" if _headers.is_redacted_name(name, redacted) else value
            span.attribute(f"http.{phase}.header.{name}", shown)


def _interruptible(response: HttpClientResponse, controller: AbortController) -> HttpClientResponse:
    """Abort when the unread ``response`` is collected, when a body read is
    interrupted, or when its stream ends."""
    finalizer = weakref.finalize(response, controller.abort)

    def release() -> None:
        finalizer.detach()

    return _InterruptibleResponse(response, controller.abort, release)


def _guarded(
    sending: Effect[HttpClientResponse, HttpClientError],
    controller: AbortController,
    on_response: Callable[[HttpClientResponse], None],
    scoped: bool,
) -> Effect[HttpClientResponse, HttpClientError]:
    def on_failure(cause: Cause[HttpClientError]) -> Effect[HttpClientResponse, HttpClientError]:
        if not scoped and cause.has_interrupts:
            controller.abort()
        return fail_with_cause(cause)

    def on_success(response: HttpClientResponse) -> Effect[HttpClientResponse, HttpClientError]:
        on_response(response)
        return succeed(response if scoped else _interruptible(response, controller))

    return uninterruptible_mask(
        lambda restore: restore(sending).match_cause_effect(
            on_failure=on_failure, on_success=on_success
        )
    )


def _send(
    send: Send, request: HttpClientRequest, fiber: Fiber[Any, Any]
) -> Effect[HttpClientResponse, HttpClientError]:
    tie = fiber.get_ref(_ScopedAbort)
    scoped_controller = None if tie is None else tie.controller_for(request)
    controller = scoped_controller or AbortController()
    match _url.make(request.url, request.url_params, request.hash):
        case Err(error):
            return fail(HttpClientError(InvalidUrlError(request, error)))
        case Ok(url):
            pass
    if fiber.get_ref(DisablePropagation) or fiber.get_ref(TracerDisabledWhen)(request):
        sending = _call_user(send, request, url, controller.signal, fiber)
        if scoped_controller is not None:
            return sending
        return _guarded(sending, controller, lambda _response: None, False)

    def traced(span: Span) -> Effect[HttpClientResponse, HttpClientError]:
        span.attribute("http.request.method", request.method)
        redacted_headers = fiber.get_ref(_headers.CurrentRedactedNames)
        _add_url_attributes(
            span,
            url,
            _redacted_names(request.url_params, fiber.get_ref(_url_params.CurrentRedactedNames)),
        )
        accept = fiber.get_ref(TracerHeaderFilter)
        _add_header_attributes(span, "request", request.headers, accept, redacted_headers)
        sent = (
            request.set_headers(trace_context.to_headers(span))
            if fiber.get_ref(TracerPropagationEnabled)
            else request
        )

        def on_response(response: HttpClientResponse) -> None:
            span.attribute("http.response.status_code", response.status)
            _add_header_attributes(span, "response", response.headers, accept, redacted_headers)
            if 400 <= response.status < 600:
                span.attribute("error.type", str(response.status))
                now = (
                    fiber.get_ref(Clock).now_nanos_unsafe()
                    if fiber.get_ref(TracerTimingEnabled)
                    else 0
                )
                error = HttpClientError(StatusCodeError(sent, response))
                span.end(now, Failure(fail_cause(error)))

        sending = in_parent_span(_call_user(send, sent, url, controller.signal, fiber), span)
        return _guarded(sending, controller, on_response, scoped_controller is not None)

    return use_span(fiber.get_ref(SpanNameGenerator)(request), traced, kind="client")


def make(send: Send) -> HttpClientService[HttpClientError]:
    """A client sending each request with ``send``. It builds the URL
    (failing with an ``InvalidUrlError``), runs each request in a client
    span with HTTP attributes and trace headers, and aborts the request's
    signal when it is interrupted or its unread response is dropped."""

    def postprocess(
        requests: Effect[HttpClientRequest, Any, Any],
    ) -> Effect[HttpClientResponse, HttpClientError]:
        return requests.flat_map(
            lambda request: _WithFiber(lambda fiber: _send(send, request, fiber))
        )

    return HttpClientService(postprocess, succeed)
