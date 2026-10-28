"""HTTP (Effect's ``effect/http``).

Client:

- ``client``: the ``HttpClient`` service, its combinators, ``make`` and
  ``layer_test``
- ``httpx_client``: an ``HttpClient`` on httpx (``pyfect[httpx]``)
- ``request`` / ``response``: requests and responses
- ``body``, ``headers``, ``url_params``, ``url``, ``cookies``, ``method``:
  the values they are made of
- ``error``: ``HttpClientError`` and its reasons
- ``trace_context``: ``traceparent`` / ``b3`` headers

Server:

- ``server``: the ``HttpServer`` service, ``serve`` and the test client;
  ``live_server``: the stdlib HTTP/1.1 server behind it
- ``server_request`` / ``server_response`` / ``server_error`` /
  ``server_respondable``: what a handler reads, returns and fails with
- ``router`` (on ``find_my_way``), ``middleware``, ``http_effect``,
  ``web_handler``: building and running apps
- ``platform``, ``static_server``, ``multipart``, ``etag``, ``mime``,
  ``template``, ``status``

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
    etag,
    find_my_way,
    headers,
    http_effect,
    incoming_message,
    live_server,
    method,
    middleware,
    mime,
    multipart,
    platform,
    request,
    response,
    router,
    server,
    server_error,
    server_request,
    server_respondable,
    server_response,
    static_server,
    status,
    template,
    trace_context,
    url,
    url_params,
    web_handler,
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
    "etag",
    "find_my_way",
    "headers",
    "http_effect",
    "incoming_message",
    "live_server",
    "method",
    "middleware",
    "mime",
    "multipart",
    "platform",
    "request",
    "response",
    "router",
    "server",
    "server_error",
    "server_request",
    "server_respondable",
    "server_response",
    "static_server",
    "status",
    "template",
    "trace_context",
    "url",
    "url_params",
    "web_handler",
]
