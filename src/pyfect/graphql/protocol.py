"""GraphQL transports (Effect's ``GraphQLProtocol``).

The client sends every operation through the ``GraphQLProtocol`` service:
``execute`` for queries and mutations, ``subscribe`` for subscriptions.
``layer_http`` / ``make_http`` speak GraphQL over HTTP, with subscriptions
over graphql-sse, or over graphql-transport-ws with ``web_socket=``;
``layer_web_socket`` / ``make_web_socket`` run every operation over
graphql-transport-ws. A test may provide any ``GraphQLProtocolService``.
"""

from __future__ import annotations

from typing import Any, Never, overload

from pyfect.effect import Effect
from pyfect.graphql._http import QueryMethod, Url, UrlOptions, make_http_sse
from pyfect.graphql._types import (
    Answer,
    ExecutionResult,
    GraphQLProtocol,
    GraphQLProtocolService,
    GraphQLRequest,
    Kind,
)
from pyfect.graphql._ws import WebSocketOptions, make_web_socket_protocol
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scope import Scope
from pyfect.socket import WebSocketConstructor


@overload
def make_http(
    *, url: Url, query_method: QueryMethod = "POST", web_socket: None = None
) -> Effect[GraphQLProtocolService, Never, HttpClient]: ...
@overload
def make_http[R](
    *, url: str, query_method: QueryMethod = "POST", web_socket: WebSocketOptions[R]
) -> Effect[GraphQLProtocolService, Never, HttpClient | WebSocketConstructor | Scope | R]: ...
def make_http(
    *,
    url: Url,
    query_method: QueryMethod = "POST",
    web_socket: WebSocketOptions[Any] | None = None,
) -> Effect[GraphQLProtocolService, Never, Any]:
    """A transport POSTing queries and mutations as JSON to ``url``
    (queries as GET URL params with ``query_method="GET"``) and running
    subscriptions over graphql-sse, or over graphql-transport-ws with
    ``web_socket`` (whose connection lives in the current scope)."""
    return _make_http(url, query_method, web_socket)


def _make_http(
    url: Url, query_method: QueryMethod, web_socket: WebSocketOptions[Any] | None
) -> Effect[GraphQLProtocolService, Never, Any]:
    http = make_http_sse(url=url, query_method=query_method)
    if web_socket is None:
        return http
    return http.zip_with(
        make_web_socket_protocol(web_socket),
        lambda over_http, over_ws: GraphQLProtocolService(
            execute=over_http.execute, subscribe=over_ws.subscribe, url=over_http.url
        ),
    )


@overload
def layer_http(
    *, url: Url, query_method: QueryMethod = "POST", web_socket: None = None
) -> Layer[GraphQLProtocol, Never, HttpClient]: ...
@overload
def layer_http[R](
    *, url: str, query_method: QueryMethod = "POST", web_socket: WebSocketOptions[R]
) -> Layer[GraphQLProtocol, Never, HttpClient | WebSocketConstructor | R]: ...
def layer_http(
    *,
    url: Url,
    query_method: QueryMethod = "POST",
    web_socket: WebSocketOptions[Any] | None = None,
) -> Layer[GraphQLProtocol, Never, Any]:
    """``make_http`` as a layer."""
    return layer_effect(GraphQLProtocol, _make_http(url, query_method, web_socket))


def make_web_socket[R = Never](
    options: WebSocketOptions[R],
) -> Effect[GraphQLProtocolService, Never, WebSocketConstructor | Scope | R]:
    """A transport running every operation over one shared
    graphql-transport-ws connection, opened on the first operation and
    living in the current scope (see ``WebSocketOptions``). Per-call
    headers and URL params are not sent: graphql-ws has none per
    operation."""
    return make_web_socket_protocol(options)


def layer_web_socket[R = Never](
    options: WebSocketOptions[R],
) -> Layer[GraphQLProtocol, Never, WebSocketConstructor | R]:
    """``make_web_socket`` as a layer."""
    return layer_effect(GraphQLProtocol, make_web_socket(options))


__all__ = [
    "Answer",
    "ExecutionResult",
    "GraphQLProtocol",
    "GraphQLProtocolService",
    "GraphQLRequest",
    "Kind",
    "QueryMethod",
    "Url",
    "UrlOptions",
    "WebSocketOptions",
    "layer_http",
    "layer_web_socket",
    "make_http",
    "make_web_socket",
]
