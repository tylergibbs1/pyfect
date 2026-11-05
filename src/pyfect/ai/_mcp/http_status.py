"""A request's failure that also sets its HTTP response's status (Effect's
``failWithHttpStatus``); over stdio only the failure counts."""

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect, _WithFiber  # pyright: ignore[reportPrivateUsage]
from pyfect._fiber import Fiber
from pyfect.ai.mcp_schema import McpError
from pyfect.effect import fail, succeed
from pyfect.http._request_state import append_pre_response_handler_unsafe
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse


def fail_with_http_status(status: int, error: McpError) -> Effect[Never, McpError]:
    def body(fiber: Fiber[Any, Any]) -> Effect[Never, McpError]:
        def set_status(
            _request: ServerRequest, response: HttpServerResponse
        ) -> Effect[HttpServerResponse]:
            return succeed(response.set_status(status))

        append_pre_response_handler_unsafe(fiber._context, set_status)  # pyright: ignore[reportPrivateUsage]
        return fail(error)

    return _WithFiber(body)
