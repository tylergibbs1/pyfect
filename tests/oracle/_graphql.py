"""Shared fixtures for the ``pyfect.graphql`` ports (Effect's
test/graphql/fixtures.ts): operations standing in for generated output, a
scripted ``GraphQLProtocol``, a scripted ``HttpClient`` and
``expect_reason``."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NotRequired, TypedDict
from urllib.parse import SplitResult, parse_qs

from pyfect import effect, layer, stream
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.effect import Effect
from pyfect.exit import Success
from pyfect.graphql import GraphQLGroup, query, subscription
from pyfect.graphql.client_error import GraphQLClientError, Reason, TransportError
from pyfect.graphql.protocol import Answer, GraphQLProtocol, GraphQLProtocolService, GraphQLRequest
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.socket import WebSocketConstructor
from pyfect.socket._web_socket import Listener, WebSocketClientOptions, WebSocketEvent
from pyfect.stream import Stream


class Issue(TypedDict):
    number: int
    title: str
    createdAt: datetime


class PageInfo(TypedDict):
    hasNextPage: bool
    endCursor: str | None


class Issues(TypedDict):
    pageInfo: PageInfo
    nodes: Sequence[Issue | None] | None


class Repository(TypedDict):
    issues: Issues | None


class RepoIssuesResult(TypedDict):
    repository: Repository | None


class RepoIssuesVariables(TypedDict):
    owner: str
    name: str
    after: NotRequired[str | None]
    since: NotRequired[datetime | None]


ISSUE = S.Struct(Issue, createdAt=S.DateTimeUtcFromString)
ISSUES = S.Struct(Issues, nodes=S.NullOr(S.Array(S.NullOr(ISSUE))))
REPO_ISSUES_RESULT = S.Struct(
    RepoIssuesResult, repository=S.NullOr(S.Struct(Repository, issues=S.NullOr(ISSUES)))
)

RepoIssues = query(
    "RepoIssues",
    document="query RepoIssues($owner:String!,$name:String!,$after:String,$since:DateTime){repository(owner:$owner,name:$name){issues(first:2,after:$after,filterBy:{since:$since}){pageInfo{hasNextPage endCursor}nodes{number title createdAt}}}}",  # noqa: E501
    variables=S.Struct(RepoIssuesVariables, since=S.NullOr(S.DateTimeUtcFromString)),
    result=REPO_ISSUES_RESULT,
)


class Login(TypedDict):
    login: str


class ViewerResult(TypedDict):
    viewer: Login


VIEWER_RESULT = S.Struct(ViewerResult)

Viewer = query("Viewer", document="query Viewer{viewer{login}}", result=VIEWER_RESULT)


class IssueId(TypedDict):
    id: str


class Title(TypedDict):
    title: str


class IssueUpdatedResult(TypedDict):
    issueUpdated: Title


IssueUpdated = subscription(
    "IssueUpdated",
    document="subscription IssueUpdated($id:ID!){issueUpdated(id:$id){title}}",
    variables=S.Struct(IssueId),
    result=S.Struct(IssueUpdatedResult),
)


class IssuesGroup(GraphQLGroup):
    repo_issues = RepoIssues
    issue_updated = IssueUpdated


class ViewerGroup(GraphQLGroup):
    viewer = Viewer


# --- transport doubles -------------------------------------------------------------


def protocol_layer(
    *,
    execute: Callable[[GraphQLRequest], Effect[Answer, TransportError]] | None = None,
    subscribe: Callable[[GraphQLRequest], Stream[Answer, TransportError]] | None = None,
) -> Layer[GraphQLProtocol]:
    """A ``GraphQLProtocol`` with scripted behaviour."""
    service = GraphQLProtocolService(
        execute=execute or (lambda request: effect.die(AssertionError("execute not scripted"))),
        subscribe=subscribe
        or (lambda request: stream.die(AssertionError("subscribe not scripted"))),
    )
    return layer.succeed(GraphQLProtocol, service)


def execute_layer(
    body: object, status: int | None = None
) -> tuple[Layer[GraphQLProtocol], list[GraphQLRequest]]:
    """A protocol answering every request with ``body`` (and ``status``),
    recording the requests."""
    requests: list[GraphQLRequest] = []

    def execute(request: GraphQLRequest) -> Effect[Answer, TransportError]:
        def record() -> Answer:
            requests.append(request)
            return Answer(body=body, status=status)

        return effect.sync(record)

    return protocol_layer(execute=execute), requests


type Handler = Callable[[HttpClientRequest, str | None, SplitResult], HttpClientResponse]


def body_text(request: HttpClientRequest) -> str | None:
    body = request.body
    return body.body.decode() if isinstance(body, http_body.Bytes) else None


def http_client_layer(handler: Handler) -> Layer[HttpClient]:
    """An ``HttpClient`` answering every request from ``handler``, given
    the request, its body text and its final URL."""

    def send(request: HttpClientRequest, url: SplitResult, _signal: Any, _fiber: Any) -> Any:
        return effect.sync(lambda: handler(request, body_text(request), url))

    return layer.succeed(HttpClient, http_client.make(send))


def graphql_response(
    request: HttpClientRequest,
    body: object,
    *,
    status: int = 200,
    content_type: str = "application/graphql-response+json",
    headers: dict[str, str] | None = None,
) -> HttpClientResponse:
    return http_response.make(
        request,
        json.dumps(body),
        status=status,
        headers={"content-type": content_type, **(headers or {})},
    )


def url_params(url: SplitResult) -> dict[str, list[str]]:
    """Every value of every URL param."""
    return parse_qs(url.query)


def layer_http(handler: Handler) -> Layer[GraphQLProtocol]:
    from pyfect.graphql.protocol import layer_http as graphql_layer_http

    return graphql_layer_http(url="http://localhost/graphql").pipe(
        layer.provide(http_client_layer(handler))
    )


def expect_reason[R: Reason](
    tag: type[R],
) -> Callable[[Effect[Any, Any, Any]], Effect[R, Any, Any]]:
    """The reason of the ``GraphQLClientError`` the effect fails with,
    checked to be a ``tag``."""

    def check(error: object) -> R:
        assert isinstance(error, GraphQLClientError), error
        assert isinstance(error.reason, tag), error.reason
        return error.reason

    return lambda eff: eff.flip().map(check)


# --- an in-memory graphql-ws server ----------------------------------------------------


type WsMessage = dict[str, Any]


class FakeWebSocket:
    """A ``WebSocketLike`` whose frames go to its ``WsConnection``."""

    def __init__(self, inbox: Queue[WsMessage], closed: Deferred[int]) -> None:
        self.state = 1
        self.inbox = inbox
        self.closed = closed
        self.listeners: list[tuple[str, Listener, bool]] = []

    @property
    def ready_state(self) -> int:
        return self.state

    def add_event_listener(self, type: Any, listener: Listener, *, once: bool = False) -> None:
        self.listeners.append((type, listener, once))

    def remove_event_listener(self, type: Any, listener: Listener) -> None:
        self.listeners = [
            entry for entry in self.listeners if entry[0] != type or entry[1] != listener
        ]

    def dispatch(self, type: str, event: WebSocketEvent) -> None:
        for entry in [entry for entry in self.listeners if entry[0] == type]:
            if entry[2]:
                self.listeners = [other for other in self.listeners if other is not entry]
            entry[1](event)

    def send(self, data: bytes | str) -> None:
        self.inbox.offer_unsafe(json.loads(data))

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        if self.state >= 2:
            return
        self.state = 3
        self.closed.done_unsafe(Success(1005 if code is None else code))
        self.dispatch("close", WebSocketEvent(code=1005 if code is None else code, reason=reason))

    def server_close(self, code: int, reason: str | None = None) -> None:
        if self.state >= 2:
            return
        self.state = 3
        self.dispatch("close", WebSocketEvent(code=code, reason=reason or ""))


@dataclass(frozen=True)
class WsConnection:
    """The server end of one in-memory WebSocket the transport opened."""

    url: str
    options: WebSocketClientOptions
    ws: FakeWebSocket

    @property
    def received(self) -> Queue[WsMessage]:
        """Every frame the client sent, parsed."""
        return self.ws.inbox

    @property
    def closed(self) -> Deferred[int]:
        """The code the client closed with, once it does."""
        return self.ws.closed

    def send(self, message: WsMessage) -> Effect[None]:
        return effect.sync(
            lambda: self.ws.dispatch("message", WebSocketEvent(data=json.dumps(message)))
        )

    def close(self, code: int, reason: str | None = None) -> Effect[None]:
        return effect.sync(lambda: self.ws.server_close(code, reason))


@dataclass(frozen=True)
class Accepted:
    connection: WsConnection
    init: WsMessage


class WsServer:
    """A ``WebSocketConstructor`` whose sockets are in-memory queue pairs.
    Each socket the transport opens shows up on ``connections``, already
    open, for the test to script the server side."""

    def __init__(self) -> None:
        self.connections: Queue[WsConnection] = Queue()

        def construct(url: str, options: WebSocketClientOptions) -> FakeWebSocket:
            ws = FakeWebSocket(Queue(), Deferred())
            self.connections.offer_unsafe(WsConnection(url, options, ws))
            return ws

        self.layer: Layer[WebSocketConstructor] = layer.succeed(WebSocketConstructor, construct)

    @property
    def accept(self) -> Effect[Accepted]:
        """Takes the next connection, reads its ``connection_init`` and
        acknowledges it."""

        def accepted():
            connection = yield from self.connections.take()
            init = yield from connection.received.take()
            assert init["type"] == "connection_init"
            yield from connection.send({"type": "connection_ack"})
            return Accepted(connection, init)

        return effect.gen(accepted)
