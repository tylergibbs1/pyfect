"""Port of Effect's platform-node/test/GraphQLProtocol.test.ts: the
GraphQL transports against real servers. The live HTTP server answers
POSTs (JSON and graphql-sse); Node's hand-rolled graphql-transport-ws
server becomes a threaded ``websockets`` server on its own port (the live
server's upgrade hands over the raw connection, without WebSocket
framing)."""

import json
import threading
from collections.abc import Iterator
from http import HTTPStatus
from typing import Any, TypedDict

import pytest

pytest.importorskip("websockets")

from websockets.http11 import Request, Response
from websockets.sync.server import Server, ServerConnection, serve

import pyfect as fx
from pyfect import effect, layer, stream
from pyfect import schema as S
from pyfect.graphql import GraphQLGroup, client, query, subscription
from pyfect.graphql.protocol import WebSocketOptions, layer_http
from pyfect.http import router, server_response
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.socket import ws as ws_platform

from ._live_http import run_live


class Login(TypedDict):
    login: str


class ViewerResult(TypedDict):
    viewer: Login


class IssueId(TypedDict):
    id: str


class Title(TypedDict):
    title: str


class IssueUpdatedResult(TypedDict):
    issueUpdated: Title


Viewer = query("Viewer", document="query Viewer{viewer{login}}", result=S.Struct(ViewerResult))
IssueUpdated = subscription(
    "IssueUpdated",
    document="subscription IssueUpdated($id:ID!){issueUpdated(id:$id){title}}",
    variables=S.Struct(IssueId),
    result=S.Struct(IssueUpdatedResult),
)


class Group(GraphQLGroup):
    viewer = Viewer
    issue_updated = IssueUpdated


VIEWER = {"data": {"viewer": {"login": "tim"}}}


def issue(title: str) -> dict[str, Any]:
    return {"data": {"issueUpdated": {"title": title}}}


def post(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
    """POST answers queries with JSON and subscriptions with a graphql-sse
    stream."""
    if "text/event-stream" not in request.headers.get("accept", ""):
        return effect.succeed(server_response.json_unsafe(VIEWER))
    chunks = [
        f"event: next\ndata: {json.dumps(issue('over sse'))}\n\n",
        "event: complete\ndata:\n\n",
    ]
    body = stream.from_iterable([chunk.encode() for chunk in chunks])
    return effect.succeed(server_response.stream(body, content_type="text/event-stream"))


def graphql_ws(connection: ServerConnection) -> None:
    """A hand-rolled graphql-transport-ws server."""
    for frame in connection:
        message = json.loads(frame)
        if message["type"] == "connection_init":
            connection.send(json.dumps({"type": "connection_ack"}))
        elif message["type"] == "ping":
            connection.send(json.dumps({"type": "pong"}))
        elif message["type"] == "subscribe":
            payload = issue("over ws")
            connection.send(json.dumps({"id": message["id"], "type": "next", "payload": payload}))
            connection.send(json.dumps({"id": message["id"], "type": "complete"}))


def require_authorization(connection: ServerConnection, request: Request) -> Response | None:
    """The handshake needs an Authorization header."""
    if request.headers.get("authorization") != "Bearer secret":
        return connection.respond(HTTPStatus.UNAUTHORIZED, "")
    return None


@pytest.fixture
def ws_server() -> Iterator[int]:
    server: Server = serve(graphql_ws, "127.0.0.1", 0, process_request=require_authorization)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.socket.getsockname()[1]
    server.shutdown()
    thread.join()


def test_serves_a_query_over_post_and_subscriptions_over_graphql_ws_and_sse(ws_server: int):
    """GraphQLProtocol over a real server / serves a query over POST, a subscription over graphql-ws and one over graphql-sse"""  # noqa: E501
    app = router.add("POST", "/graphql", HttpServerRequest().flat_map(post))

    def program():
        # The live test client sends relative URLs to the server.
        url = "/graphql"

        options = WebSocketOptions(
            url=f"ws://127.0.0.1:{ws_server}/graphql",
            headers={"authorization": "Bearer secret"},
        )
        split_protocol = (
            yield from layer_http(url=url, web_socket=options)
            .pipe(layer.provide(ws_platform.layer_web_socket_constructor))
            .build()
        )
        split = yield from client.make(Group).pipe(fx.provide_context(split_protocol))
        assert (yield from split.viewer()) == VIEWER["data"]
        updates = yield from split.issue_updated({"id": "I_1"}).run_collect()
        assert updates == [issue("over ws")["data"]]

        sse_protocol = yield from layer_http(url=url).build()
        sse = yield from client.make(Group).pipe(fx.provide_context(sse_protocol))
        updates = yield from sse.issue_updated({"id": "I_1"}).run_collect()
        assert updates == [issue("over sse")["data"]]

    served: fx.Effect[None, Any, Any] = (
        effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True))).timeout(5)
    )
    run_live(served)
