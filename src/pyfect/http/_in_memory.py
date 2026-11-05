"""An ``HttpClientService`` answered by an app in the same process (the
client Effect's ``HttpApiTest.groups`` builds).

Each request runs the app on the requesting fiber, in its own scope forked
from the client's. A streamed response body is not buffered: the client
reads it as the app writes it, one chunk per pull, and the request's scope
closes when the body ends or the reader stops (or with the client's scope,
for a body never read).
"""

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect
from pyfect.effect import gen, provide_service, succeed
from pyfect.exit import Exit, Success
from pyfect.http._request_state import CurrentRequestState, RequestState
from pyfect.http.client import HttpClientService
from pyfect.http.client import make as make_http_client
from pyfect.http.error import HttpClientError
from pyfect.http.http_effect import scope_transfer_to_stream
from pyfect.http.request import HttpClientRequest
from pyfect.http.server_request import HttpServerRequest, from_client_request
from pyfect.http.server_response import HttpServerResponse, to_client_response
from pyfect.scope import CloseableScope, Scope


def client(
    app: Effect[HttpServerResponse, Any, Any], scope: CloseableScope
) -> HttpClientService[HttpClientError, Any]:
    """A client whose requests ``app`` answers; ``app`` 's failures are
    defects of the request. Bodies left open close with ``scope``."""
    return make_http_client(lambda request, _url, _signal, _fiber: _handle(app, scope, request))


def _handle(
    app: Effect[HttpServerResponse, Any, Any],
    scope: CloseableScope,
    request: HttpClientRequest,
) -> Effect[Any, Never, Any]:
    def run() -> Any:
        request_scope: CloseableScope = yield from scope.fork()
        server_request = from_client_request(request)
        state = RequestState()
        transferred = False

        def pre_response(response: HttpServerResponse) -> Effect[HttpServerResponse, Any, Any]:
            pre = state.pre_response_handler
            return succeed(response) if pre is None else pre(server_request, response)

        def to_client(response: HttpServerResponse) -> Any:
            nonlocal transferred
            transfer = scope_transfer_to_stream(response)
            transferred = transfer is not response
            return to_client_response(transfer, request=request)

        def on_exit(exit_: Exit[Any, Any]) -> Effect[None]:
            if transferred and isinstance(exit_, Success):
                return succeed(None)
            return request_scope.close(exit_)

        return (
            yield from app.flat_map(pre_response)
            .map(to_client)
            .pipe(provide_service(HttpServerRequest, server_request))
            .pipe(provide_service(CurrentRequestState, state))
            .pipe(provide_service(Scope, request_scope))
            .or_die()
            .on_exit(on_exit)
        )

    return gen(run)


__all__ = ["client"]
