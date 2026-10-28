"""HTTP (Effect's ``effect/http`` client modules).

- ``client``: the ``HttpClient`` service, its combinators, ``make`` and
  ``layer_test``
- ``httpx_client``: an ``HttpClient`` on httpx (``pyfect[httpx]``)
- ``request`` / ``response``: requests and responses
- ``body``, ``headers``, ``url_params``, ``url``, ``cookies``, ``method``:
  the values they are made of
- ``error``: ``HttpClientError`` and its reasons
- ``trace_context``: ``traceparent`` / ``b3`` headers

::

    from pyfect.http import client, httpx_client, response

    @fx.fn
    def program():
        res = yield from client.get("https://example.com")
        return (yield from res.text)

    fx.run_sync(program().pipe(fx.provide(httpx_client.layer)))
"""

from pyfect.http import (
    abort,
    body,
    client,
    cookies,
    error,
    headers,
    incoming_message,
    method,
    request,
    response,
    trace_context,
    url,
    url_params,
)
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse

__all__ = [
    "HttpClient",
    "HttpClientError",
    "HttpClientRequest",
    "HttpClientResponse",
    "HttpClientService",
    "abort",
    "body",
    "client",
    "cookies",
    "error",
    "headers",
    "incoming_message",
    "method",
    "request",
    "response",
    "trace_context",
    "url",
    "url_params",
]
