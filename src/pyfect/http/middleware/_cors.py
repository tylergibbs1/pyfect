"""CORS (Effect's ``HttpMiddleware.cors``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.effect import succeed
from pyfect.http._request_state import append_pre_response_handler_unsafe
from pyfect.http._vary import vary_with
from pyfect.http.headers import Headers
from pyfect.http.middleware._types import AppMiddleware
from pyfect.http.server_error import HttpServerError
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse, empty

type AllowedOrigins = Sequence[str] | Callable[[str], bool]

_DEFAULT_METHODS = ("GET", "HEAD", "PUT", "PATCH", "POST", "DELETE")


def cors(
    *,
    allowed_origins: AllowedOrigins = (),
    allowed_methods: Sequence[str] = _DEFAULT_METHODS,
    allowed_headers: Sequence[str] = (),
    exposed_headers: Sequence[str] = (),
    max_age: int | None = None,
    credentials: bool = False,
) -> AppMiddleware[HttpServerRequest]:
    """Middleware answering preflight ``OPTIONS`` requests (204) and adding
    the CORS headers to every response. With no ``allowed_origins`` every
    origin is allowed (``*``); with several (or a test) the request's
    origin is echoed when allowed, and responses vary by ``Origin``. A
    request from an origin that is not allowed is still served: only the
    browser withholds the response, so CORS is no access control.
    ``credentials`` needs ``allowed_origins`` without ``*``: browsers refuse
    credentials with ``*``, so that combination raises ``ValueError`` here (Effect
    sends it)."""
    if (
        credentials
        and not callable(allowed_origins)
        and (not allowed_origins or "*" in allowed_origins)
    ):
        raise ValueError("cors(credentials=True) needs allowed_origins; browsers refuse '*'")
    is_allowed: Callable[[str], bool]
    if callable(allowed_origins):
        is_allowed = allowed_origins
        echo = True
        fixed: dict[str, str] = {}
    else:
        origins = tuple(allowed_origins)

        is_allowed = origins.__contains__

        echo = len(origins) > 1
        fixed = (
            {"access-control-allow-origin": "*"}
            if not origins
            else {"access-control-allow-origin": origins[0], "vary": "Origin"}
        )

    def allow_origin(origin: str | None) -> dict[str, str]:
        if not echo:
            return fixed
        if origin is None or not is_allowed(origin):
            return {"vary": "Origin"}
        return {"access-control-allow-origin": origin, "vary": "Origin"}

    allow_credentials = {"access-control-allow-credentials": "true"} if credentials else {}
    allow_methods = (
        {"access-control-allow-methods": ", ".join(allowed_methods)} if allowed_methods else {}
    )
    expose = {"access-control-expose-headers": ",".join(exposed_headers)} if exposed_headers else {}
    max_age_header = {"access-control-max-age": str(max_age)} if max_age else {}

    def allow_headers(requested: str | None) -> dict[str, str]:
        if not allowed_headers and requested:
            return {
                "vary": "Access-Control-Request-Headers",
                "access-control-allow-headers": requested,
            }
        return {"access-control-allow-headers": ",".join(allowed_headers)}

    def from_request(request: ServerRequest) -> Headers:
        return Headers(
            {**allow_origin(request.headers.get("origin")), **allow_credentials, **expose}
        )

    def from_preflight(request: ServerRequest) -> Headers:
        headers = Headers(
            {
                **allow_origin(request.headers.get("origin")),
                **allow_credentials,
                **expose,
                **allow_methods,
                **max_age_header,
            }
        )
        access = allow_headers(request.headers.get("access-control-request-headers"))
        vary = access.get("vary")
        if vary is not None:
            access = {**access, "vary": vary_with(headers, vary)}
        return headers.set_all(access)

    def pre_response(
        request: ServerRequest, response: HttpServerResponse
    ) -> Effect[HttpServerResponse, HttpServerError]:
        headers = from_request(request)
        if "vary" in headers:
            headers = headers.set("vary", vary_with(response.headers, "Origin"))
        return succeed(response.set_headers(headers))

    def middleware[E, R](
        app: Effect[HttpServerResponse, E, R],
    ) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
        def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R]:
            request = fiber._context.unsafe_get(HttpServerRequest)
            if request.method == "OPTIONS":
                return succeed(empty(status=204, headers=from_preflight(request)))
            append_pre_response_handler_unsafe(fiber._context, pre_response)
            return app

        return _WithFiber(body)

    return middleware
