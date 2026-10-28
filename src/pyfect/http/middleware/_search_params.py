"""Parsing the query once for the app (Effect's
``HttpMiddleware.searchParamsParser``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from pyfect._core import Effect, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._primitives import _Locally
from pyfect.http.server_request import (
    HttpServerRequest,
    ParsedSearchParams,
    search_params_from_url,
)
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.url import parse


def search_params_parser[E, R](
    app: Effect[HttpServerResponse, E, R | ParsedSearchParams],
) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
    """``app`` with ``ParsedSearchParams``: the request URL's query as a
    record (a repeated key gives a list)."""
    require_effect(app, "app")

    def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R]:
        request = fiber._context.unsafe_get(HttpServerRequest)
        params = search_params_from_url(parse(request.original_url, "http://localhost"))
        return _Locally(app, lambda ctx: ctx.add(ParsedSearchParams, params))

    return _WithFiber(body)
