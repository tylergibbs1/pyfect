"""The server span of a request (Effect's ``HttpMiddleware.tracer``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._primitives import Restore, _Locally, uninterruptible_mask
from pyfect._tracer_ref import CurrentTracer
from pyfect.cause import fail
from pyfect.clock import Clock
from pyfect.context import Reference
from pyfect.effect import sync
from pyfect.exit import Exit, Failure, Success
from pyfect.http import _redacted_path, _request_state, trace_context
from pyfect.http import headers as _headers
from pyfect.http import url_params as _url_params
from pyfect.http._request_state import RequestState
from pyfect.http._url_text import strip_search_and_hash
from pyfect.http.client._make import _add_header_attributes, _add_url_attributes
from pyfect.http.server_error import (
    HttpServerError,
    ResponseError,
    cause_response_stripped,
)
from pyfect.http.server_request import HttpServerRequest, ServerRequest, to_url
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.url import set_pathname
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.tracer import ParentSpan, Span, TracerEnabled, native_tracer
from pyfect.tracer._model import SpanOptions
from pyfect.tracer._spans import make_span_unsafe

type Phase = Literal["request", "response"]


class TracerDisabledWhen(Reference[Callable[[ServerRequest], bool]]):
    """Requests handled without a server span."""

    @classmethod
    def default(cls) -> Callable[[ServerRequest], bool]:
        return lambda _request: False


def layer_tracer_disabled_for_urls(urls: Sequence[str]) -> Layer[TracerDisabledWhen]:
    """No spans for requests to exactly these URLs."""
    disabled = tuple(urls)
    return layer_succeed(TracerDisabledWhen, lambda request: request.url in disabled)


class SpanNameGenerator(Reference[Callable[[ServerRequest], str]]):
    """The name of a request's span; its method by default."""

    @classmethod
    def default(cls) -> Callable[[ServerRequest], str]:
        return lambda request: request.method


class TracerHeaderFilter(Reference[Callable[[str, Phase], bool]]):
    """The headers recorded as span attributes, by name and phase (none by
    default)."""

    @classmethod
    def default(cls) -> Callable[[str, Phase], bool]:
        return lambda _name, _phase: False


def is_tracer_disabled_unsafe(fiber: Fiber[Any, Any], request: ServerRequest) -> bool:
    return not fiber.get_ref(TracerEnabled) or fiber.get_ref(TracerDisabledWhen)(request)


def uses_native_tracer(fiber: Fiber[Any, Any]) -> bool:
    """The native tracer keeps spans nobody can observe."""
    return fiber.get_ref(CurrentTracer) is native_tracer


def _response_span_exit(
    fiber: Fiber[Any, Any],
    request: ServerRequest,
    response: HttpServerResponse,
    state: RequestState | None,
) -> Exit[HttpServerResponse, HttpServerError]:
    # OpenTelemetry fails server spans of 5xx responses.
    if not 500 <= response.status < 600:
        return Success(response)
    # The message is path-only, but exporters can still read the error's request URL
    # after the request's redacted names are gone.
    url = _url_params.redact_url(
        request.url,
        _with_state_names(
            fiber.get_ref(_url_params.CurrentRedactedNames),
            () if state is None else state.redacted_url_param_names,
        ),
    )
    if state is not None and state.redacted_path is not None:
        url = (
            _redacted_path.format_path(state.redacted_path) + url[len(strip_search_and_hash(url)) :]
        )
    if url != request.url:
        request = request.modify(url=url)
    return Failure(fail(HttpServerError(ResponseError(request, response))))


def _with_state_names(
    names: tuple[_headers.Pattern, ...], state_names: tuple[_headers.Pattern, ...]
) -> tuple[_headers.Pattern, ...]:
    return names if not state_names else (*names, *state_names)


def _end(
    fiber: Fiber[Any, Any],
    span: Span,
    request: ServerRequest,
    state: RequestState | None,
    exit: Exit[Any, Any],
) -> None:
    end_time = fiber.get_ref(Clock).now_nanos_unsafe()
    if isinstance(exit, Success) and (
        not span.sampled or fiber.get_ref(CurrentTracer) is native_tracer
    ):
        span.end(end_time, _response_span_exit(fiber, request, exit.value, state))
        return
    redacted_headers = _with_state_names(
        fiber.get_ref(_headers.CurrentRedactedNames),
        () if state is None else state.redacted_header_names,
    )
    accept = fiber.get_ref(TracerHeaderFilter)
    span_exit: Exit[Any, Any]
    if isinstance(exit, Failure):
        response, cause = cause_response_stripped(exit.cause)
        # Only 5xx responses fail a server span; interrupts still do.
        if cause is not None and (response.status >= 500 or cause.has_interrupts):
            span_exit = Failure(cause)
        else:
            span_exit = _response_span_exit(fiber, request, response, state)
    else:
        response = exit.value
        span_exit = _response_span_exit(fiber, request, response, state)
    if span.sampled:
        span.attribute("http.request.method", request.method)
        url = to_url(request)
        if url is not None:
            if state is not None and state.redacted_path is not None:
                url = set_pathname(url, _redacted_path.format_path(state.redacted_path))
            redacted_params = _with_state_names(
                fiber.get_ref(_url_params.CurrentRedactedNames),
                () if state is None else state.redacted_url_param_names,
            )
            _add_url_attributes(span, url, redacted_params)
        user_agent = request.headers.get("user-agent")
        if user_agent is not None:
            span.attribute("user_agent.original", user_agent)
        _add_header_attributes(span, "request", request.headers, accept, redacted_headers)
        if request.remote_address is not None:
            span.attribute("client.address", request.remote_address)
        span.attribute("http.response.status_code", response.status)
        _add_header_attributes(span, "response", response.headers, accept, redacted_headers)
    span.end(end_time, span_exit)


def tracer[E, R](
    app: Effect[HttpServerResponse, E, R],
) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
    """Run ``app`` in a server span named by ``SpanNameGenerator``, a child
    of the span in the request's trace headers, with the HTTP attributes of
    the request and response."""
    require_effect(app, "app")

    def body(
        fiber: Fiber[Any, Any], restore: Restore
    ) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
        request = fiber._context.get_unsafe(HttpServerRequest)
        if is_tracer_disabled_unsafe(fiber, request):
            return restore(app)
        parent = trace_context.from_headers(request.headers)
        options: SpanOptions = {"kind": "server"}
        if parent is not None:
            options["parent"] = parent
        span = make_span_unsafe(fiber, fiber.get_ref(SpanNameGenerator)(request), options)
        state = _request_state.get(fiber._context)

        def finish(exit: Exit[HttpServerResponse, E]) -> Effect[None]:
            return sync(lambda: _end(fiber, span, request, state, exit))

        inner: Effect[HttpServerResponse, E, R | HttpServerRequest] = _Locally(
            app, lambda ctx: ctx.add(ParentSpan, span)
        )
        return restore(inner).on_exit(finish)

    # The span is made and its end registered in one uninterruptible step.
    return uninterruptible_mask(lambda restore: _WithFiber(lambda fiber: body(fiber, restore)))
