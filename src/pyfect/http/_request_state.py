"""What a request being handled keeps besides its context: the handlers
run on its response before it is sent, whether the logger is off, and
whether its scope closes with the handler or with the response stream."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect.context import Context, Tag
from pyfect.effect import void

if TYPE_CHECKING:
    from pyfect.exit import Exit
    from pyfect.http.headers import Pattern
    from pyfect.http.server_error import HttpServerError
    from pyfect.http.server_request import ServerRequest
    from pyfect.http.server_response import HttpServerResponse
    from pyfect.scope import CloseableScope

type PreResponseHandler = Callable[
    [ServerRequest, HttpServerResponse], Effect[HttpServerResponse, HttpServerError]
]
"""Runs on a response before it is sent, and may replace it."""


class RequestState:
    __slots__ = (
        "handled",
        "logger_disabled",
        "pre_response_handler",
        "redacted_header_names",
        "redacted_url_param_names",
        "request_scope",
        "scope_ejected",
    )

    def __init__(self, request_scope: RequestScope | None = None) -> None:
        self.pre_response_handler: PreResponseHandler | None = None
        self.logger_disabled = False
        self.handled = False
        self.scope_ejected = False
        self.redacted_url_param_names: tuple[Pattern, ...] = ()
        self.redacted_header_names: tuple[Pattern, ...] = ()
        self.request_scope = request_scope
        """The scope ``to_handled`` made for the request, which a transferred body and the
        request both have to finish before it closes."""


class RequestScope:
    """Closes the scope ``to_handled`` made for a request once the request has finished and,
    when its body was transferred with ``scope_transfer_to_stream``, the body has exited too,
    with the body's exit (Effect's ``RequestScopeJoin``)."""

    __slots__ = ("_body_exit", "_finished", "scope", "transferred")

    def __init__(self, scope: CloseableScope) -> None:
        self.scope = scope
        self.transferred = False
        self._finished = False
        self._body_exit: Exit[Any, Any] | None = None

    def finish(self, exit: Exit[Any, Any], ejected: bool) -> Effect[None]:
        """The request has finished with ``exit``."""
        self._finished = True
        if self.transferred:
            body_exit = self._body_exit
            return void if body_exit is None else self.scope.close(body_exit)
        return void if ejected else self.scope.close(exit)

    def finish_body(self, exit: Exit[Any, Any]) -> Effect[None]:
        """The transferred body has exited. A body can be transferred more than once: the
        first exit wins, so a later transfer cannot replace it before the request ends."""
        if self._body_exit is None:
            self._body_exit = exit
        return self.scope.close(self._body_exit) if self._finished else void


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


def add_redacted_names_unsafe(
    context: Context[Any], url_param_names: Sequence[Pattern], header_names: Sequence[Pattern]
) -> None:
    """Redact these names too in the server span of the request being handled (outside one,
    nothing). The span is recorded after the handler restores its context, so a scoped
    ``CurrentRedactedNames`` does not reach it."""
    state = get(context)
    if state is None:
        return
    state.redacted_url_param_names = (*state.redacted_url_param_names, *url_param_names)
    state.redacted_header_names = (*state.redacted_header_names, *header_names)
