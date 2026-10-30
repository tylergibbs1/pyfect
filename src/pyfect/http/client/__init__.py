"""HTTP clients (Effect's ``HttpClient``).

``HttpClient`` is the service; ``httpx_client.layer`` provides one backed by
httpx (the ``pyfect-dev[httpx]`` extra), and ``layer_test`` one answering from a
function. A client is a value: its methods send requests and build new
clients::

    from pyfect.http import client, response

    @fx.fn
    def get_todo(todo_id: int):
        http = (yield from client.HttpClient()).filter_status_ok().retry_transient(times=3)
        res = yield from http.get(f"https://api.example.com/todos/{todo_id}")
        return (yield from response.schema_body_json(Todo)(res))

Every request runs in a client span with the HTTP semantic attributes and
sends ``traceparent`` / ``b3`` headers; interrupting a request aborts it.
``transform_response`` and ``catch_tag``, which change the error type
through a function of it, are used with ``.pipe``.
"""

from collections.abc import Callable

from pyfect.effect import Effect
from pyfect.http.abort import AbortController, AbortSignal
from pyfect.http.client._circuit_breaker import circuit_breaker_classifier
from pyfect.http.client._make import (
    Phase,
    Send,
    SpanNameGenerator,
    TracerDisabledWhen,
    TracerHeaderFilter,
    TracerPropagationEnabled,
    make,
)
from pyfect.http.client._rate_limit import RateLimitHeaders
from pyfect.http.client._retry import (
    is_transient_error,
    is_transient_response,
    with_retry_after,
)
from pyfect.http.client._service import (
    HttpClient,
    HttpClientService,
    Postprocess,
    Preprocess,
    RetryOn,
    catch_tag,
    delete,
    execute,
    get,
    head,
    make_with,
    options,
    patch,
    post,
    put,
    query,
    transform_response,
)
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed


def layer_test(
    handler: Callable[[HttpClientRequest], Effect[HttpClientResponse, HttpClientError]],
) -> Layer[HttpClient]:
    """An ``HttpClient`` answering each request with ``handler`` (built
    with ``make``, so URLs, tracing and interruption behave as with a real
    backend)."""
    return layer_succeed(HttpClient, make(lambda request, _url, _signal, _fiber: handler(request)))


__all__ = [
    "AbortController",
    "AbortSignal",
    "HttpClient",
    "HttpClientService",
    "Phase",
    "Postprocess",
    "Preprocess",
    "RateLimitHeaders",
    "RetryOn",
    "Send",
    "SpanNameGenerator",
    "TracerDisabledWhen",
    "TracerHeaderFilter",
    "TracerPropagationEnabled",
    "catch_tag",
    "circuit_breaker_classifier",
    "delete",
    "execute",
    "get",
    "head",
    "is_transient_error",
    "is_transient_response",
    "layer_test",
    "make",
    "make_with",
    "options",
    "patch",
    "post",
    "put",
    "query",
    "transform_response",
    "with_retry_after",
]
