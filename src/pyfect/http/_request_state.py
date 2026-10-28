"""What a request being handled keeps besides its context: the handlers
run on its response before it is sent, whether the logger is off, and
whether its scope closes with the handler or with the response stream."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect.context import Context, Tag

if TYPE_CHECKING:
    from pyfect.http.server_error import HttpServerError
    from pyfect.http.server_request import ServerRequest
    from pyfect.http.server_response import HttpServerResponse

type PreResponseHandler = Callable[
    [ServerRequest, HttpServerResponse], Effect[HttpServerResponse, HttpServerError]
]
"""Runs on a response before it is sent, and may replace it."""


class RequestState:
    __slots__ = ("handled", "logger_disabled", "pre_response_handler", "scope_ejected")

    def __init__(self) -> None:
        self.pre_response_handler: PreResponseHandler | None = None
        self.logger_disabled = False
        self.handled = False
        self.scope_ejected = False


class CurrentRequestState(Tag[RequestState], key="effect/http/HttpEffect/CurrentRequestState"):
    """The state of the request being handled."""


def get(context: Context[Any]) -> RequestState | None:
    found, state = context.lookup(CurrentRequestState)
    return state if found else None


def append_pre_response_handler_unsafe(context: Context[Any], handler: PreResponseHandler) -> None:
    """Run ``handler`` after the handlers already added (outside a request
    being handled, nothing)."""
    state = get(context)
    if state is None:
        return
    previous = state.pre_response_handler
    if previous is None:
        state.pre_response_handler = handler
        return

    def both(
        request: ServerRequest, response: HttpServerResponse
    ) -> Effect[HttpServerResponse, HttpServerError]:
        return previous(request, response).flat_map(lambda changed: handler(request, changed))

    state.pre_response_handler = both
