"""Running an HTTP app: an ``Effect[HttpServerResponse, E, R]`` that
reads the current ``HttpServerRequest`` (Effect's ``HttpEffect``).

``to_handled`` is what servers run per request: the app in a request scope
(closed when the response is sent, or when a streamed body ends), its
failure turned into a response (``server_error.cause_response``) and
reported, pre-response handlers applied, then ``handle_response`` writing
it. The app runs uninterruptibly unless it opts in (routes do), so a client
abort only interrupts an app that allows it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._primitives import _Locally
from pyfect.cause import Cause
from pyfect.effect import fail_cause, succeed, void
from pyfect.error_reporter import report_unsafe
from pyfect.exit import Exit, Failure
from pyfect.http import _request_state
from pyfect.http import body as _body
from pyfect.http._request_state import CurrentRequestState, PreResponseHandler, RequestState
from pyfect.http.middleware._tracer import is_tracer_disabled_unsafe, tracer, uses_native_tracer
from pyfect.http.server_error import HttpServerError, cause_response
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.scope import CloseableScope, Scope

type HttpApp[E = Never, R = Never] = Effect[HttpServerResponse, E, R]
"""An app: the response to the current request."""

type HttpMiddleware = Callable[[HttpApp[Any, Any]], HttpApp[Any, Any]]
"""Wraps an app (``middleware.logger``, ``cors(...)``...)."""

type ResponseHandler[EH, RH] = Callable[[ServerRequest, HttpServerResponse], Effect[object, EH, RH]]
"""Writes a response; succeeding with a response says what was sent."""


def _send[EH, RH](
    state: RequestState,
    request: ServerRequest,
    response: HttpServerResponse,
    handle_response: ResponseHandler[EH, RH],
) -> Effect[HttpServerResponse, EH | HttpServerError, RH]:
    """Apply the pre-response handlers, then write; the result is what was
    sent."""
    handler = state.pre_response_handler

    def write(changed: HttpServerResponse) -> Effect[HttpServerResponse, EH, RH]:
        state.handled = True
        return handle_response(request, changed).map(
            lambda sent: sent if isinstance(sent, HttpServerResponse) else response
        )

    if handler is None:
        return write(response)
    return handler(request, response).flat_map(write)


def to_handled[E, R, EH = Never, RH = Never](
    app: Effect[HttpServerResponse, E, R | Scope],
    handle_response: ResponseHandler[EH, RH],
    middleware: HttpMiddleware | None = None,
) -> Effect[None, Never, R | RH | HttpServerRequest]:
    """Handle the current request with ``app`` and write the response with
    ``handle_response``. A failure becomes its response and is reported;
    the request's ``Scope`` closes with the handler's exit."""
    require_effect(app, "app")

    def body(fiber: Fiber[Any, Any]) -> Effect[None, Never, Any]:
        previous = fiber._context
        request = previous.get_unsafe(HttpServerRequest)
        state = RequestState()
        scope = CloseableScope()
        failed: list[Cause[Any]] = []

        def on_failure(cause: Cause[Any]) -> Effect[HttpServerResponse, Any, Any]:
            failed.append(cause)

            def respond(pair: tuple[HttpServerResponse, Cause[Any]]) -> Effect[Any, Any, Any]:
                response, reported = pair
                report_unsafe(fiber, reported)
                rest = succeed(response) if not reported.reasons else fail_cause(reported)
                return _send(state, request, response, handle_response).flat_map(lambda _: rest)

            return cause_response(cause).flat_map(respond)

        responded: Effect[HttpServerResponse, Any, Any] = app.match_cause_effect(
            on_success=lambda response: _send(state, request, response, handle_response),
            on_failure=on_failure,
        )
        handled: Effect[object, Any, Any]
        if middleware is None:
            skip_tracer = uses_native_tracer(fiber) or is_tracer_disabled_unsafe(fiber, request)
            handled = responded if skip_tracer else tracer(responded)
        else:

            def middleware_failed(cause: Cause[Any]) -> Effect[None, Any, Any]:
                report_unsafe(fiber, cause)
                if state.handled:
                    return void

                def write(pair: tuple[HttpServerResponse, Cause[Any]]) -> Effect[None, Any, Any]:
                    return handle_response(request, pair[0]).as_void()

                return cause_response(cause).match_cause_effect(
                    on_failure=lambda _: handle_response(request, empty(status=500)).as_void(),
                    on_success=write,
                )

            def middleware_succeeded(response: HttpServerResponse) -> Effect[None, Any, Any]:
                if state.handled:
                    return void
                return handle_response(request, response).as_void()

            handled = tracer(middleware(responded)).match_cause_effect(
                on_failure=middleware_failed, on_success=middleware_succeeded
            )

        def close(exit: Exit[Any, Any]) -> Effect[None]:
            if state.scope_ejected:
                return void
            return scope.close(Failure(failed[0]) if failed else exit)

        in_request: Effect[object, Any, Any] = _Locally(
            handled, lambda ctx: ctx.add(Scope, scope).add(CurrentRequestState, state)
        )
        # The cause is reported where it happens; the handled request ends.
        return in_request.on_exit(close).catch_cause(lambda _: void).as_void()

    return _WithFiber(body).uninterruptible()


def scope_disable_close(state: RequestState) -> None:
    state.scope_ejected = True


def scope_transfer_to_stream(response: HttpServerResponse) -> HttpServerResponse:
    """A streamed response whose body closes the request's scope when it
    ends, instead of the handler's end (call while handling the request)."""
    if not isinstance(response.body, _body.Stream):
        return response
    fiber = Fiber.get_current()
    if fiber is None:
        return response
    state = _request_state.get(fiber._context)
    found, scope = fiber._context.lookup(Scope)
    if state is None or not found:
        return response
    state.scope_ejected = True
    closeable: CloseableScope = scope
    stream = response.body.stream.on_exit(closeable.close)
    return response.set_body_keep_headers(
        _body.Stream(stream, response.body.content_type, response.body.content_length)
    )


def append_pre_response_handler(
    handler: PreResponseHandler,
) -> Effect[None, Never, HttpServerRequest]:
    """Run ``handler`` on the response before it is sent, after the ones
    already added."""

    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        _request_state.append_pre_response_handler_unsafe(fiber._context, handler)
        return void

    return _WithFiber(body)


def with_pre_response_handler[A, E, R](
    eff: Effect[A, E, R], handler: PreResponseHandler
) -> Effect[A, E, R | HttpServerRequest]:
    """``eff``, after adding ``handler`` (``append_pre_response_handler``)."""
    require_effect(eff, "eff")
    return append_pre_response_handler(handler).and_then(eff)


append_pre_response_handler_unsafe = _request_state.append_pre_response_handler_unsafe

__all__ = [
    "HttpApp",
    "HttpMiddleware",
    "PreResponseHandler",
    "ResponseHandler",
    "append_pre_response_handler",
    "append_pre_response_handler_unsafe",
    "scope_disable_close",
    "scope_transfer_to_stream",
    "to_handled",
    "with_pre_response_handler",
]
