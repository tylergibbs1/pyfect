"""Logging each response (Effect's ``HttpMiddleware.logger``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.cause import Interrupt
from pyfect.effect import from_exit
from pyfect.exit import Exit, Failure
from pyfect.http import _request_state
from pyfect.http._url_text import strip_search_and_hash
from pyfect.http.server_error import ClientAbort, cause_response_stripped
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.logger import log


def with_logger_disabled[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R | HttpServerRequest]:
    """``eff``, and the request it runs in is not logged."""
    require_effect(eff, "eff")

    def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
        state = _request_state.get(fiber._context)
        if state is not None:
            state.logger_disabled = True
        return eff

    return _WithFiber(body)


def logger[E, R](
    app: Effect[HttpServerResponse, E, R],
) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
    """Log ``"Sent HTTP response"`` (or the failure's cause) with the
    method, path and status, in an ``http.span`` log span."""
    require_effect(app, "app")

    def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
        request = fiber._context.get_unsafe(HttpServerRequest)
        state = _request_state.get(fiber._context)
        path = strip_search_and_hash(request.url)

        def after(exit: Exit[HttpServerResponse, E]) -> Effect[HttpServerResponse, E]:
            if state is not None and state.logger_disabled:
                return from_exit(exit)
            message: object = "Sent HTTP response"
            if isinstance(exit, Failure):
                response, cause = cause_response_stripped(exit.cause)
                if cause is not None and not all(
                    isinstance(reason, Interrupt) and ClientAbort in reason.annotations
                    for reason in cause.reasons
                ):
                    message = cause
                status = response.status
            else:
                status = exit.value.status
            logged = log(message).annotate_logs(
                {"http.method": request.method, "http.url": path, "http.status": status}
            )
            return logged.and_then(from_exit(exit))

        return app.exit().flat_map(after).with_log_span("http.span")

    return _WithFiber(body)
