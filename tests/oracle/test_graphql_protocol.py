"""Ports of Effect's graphql/GraphQLProtocol.test.ts and
GraphQLProtocol.sse.test.ts. Each test's docstring is the Effect test title,
prefixed by its describe blocks; the 502 / 400 table is two tests.

A web ``Response`` is ``response.make`` (a streamed body is a ``Stream`` of
bytes); a URL is the ``Url`` the client sends to.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from email.utils import formatdate
from typing import Any, TypedDict

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect import schema as S
from pyfect.context import Context, Reference
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.effect import Effect
from pyfect.graphql import GraphQLGroup, GraphQLMiddleware, Implementation, client, mutation
from pyfect.graphql.client_error import DecodeError, ResponseError, TransportError
from pyfect.graphql.middleware import ExecuteOptions
from pyfect.graphql.protocol import (
    ExecutionResult,
    GraphQLRequest,
    UrlOptions,
    layer_http,
    make_http,
)
from pyfect.http import client as http_client
from pyfect.http import error as http_error
from pyfect.http import headers as H
from pyfect.http import response as http_response
from pyfect.http import url_params as U
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.stream import Stream

from ._graphql import (
    IssuesGroup,
    IssueUpdated,
    RepoIssues,
    RepoIssuesVariables,
    Viewer,
    ViewerGroup,
    expect_reason,
    graphql_response,
    http_client_layer,
    url_params,
)
from ._graphql import layer_http as fixture_layer_http

VIEWER_DATA = {"data": {"viewer": {"login": "tim"}}}


class Ok(TypedDict):
    ok: bool


class AddStarResult(TypedDict):
    addStar: Ok


AddStar = mutation(
    "AddStar", document="mutation AddStar{addStar{ok}}", result=S.Struct(AddStarResult)
)


class GitHubHost(Reference[str]):
    @classmethod
    def default(cls) -> str:
        return "api.github.com"


class Routed(GraphQLGroup):
    viewer = Viewer
    add_star = AddStar
    issue_updated = IssueUpdated


def _call_viewer(handler: Any) -> Effect[Any, Any]:
    return (
        client.make(ViewerGroup)
        .flat_map(lambda api: api.viewer())
        .pipe(fx.provide(fixture_layer_http(handler)))
    )


def _unavailable(request: HttpClientRequest, retry_after: str) -> Any:
    headers = {"retry-after": retry_after, "content-type": "text/plain"}
    return http_response.make(request, "down", status=503, headers=headers)


def _complete_sse(request: HttpClientRequest) -> Any:
    return http_response.make(
        request, "event: complete\ndata:\n\n", headers={"content-type": "text/event-stream"}
    )


@testing.effect
def test_posts_the_document_operation_name_and_variables_as_json():
    """GraphQLProtocol.layerHttp / POSTs the document, operation name and variables as JSON with per-call headers and URL params"""  # noqa: E501
    seen: dict[str, Any] = {}

    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        seen.update(
            method=request.method,
            headers=request.headers,
            body=json.loads(body_text or ""),
            url=url,
        )
        return graphql_response(request, VIEWER_DATA)

    result = (
        yield from client.make(ViewerGroup)
        .flat_map(
            lambda api: api.viewer(headers={"x-request-id": "abc"}, url_params={"preview": "t"})
        )
        .pipe(fx.provide(fixture_layer_http(handler)))
    )
    assert result == {"viewer": {"login": "tim"}}
    assert seen["method"] == "POST"
    assert url_params(seen["url"]) == {"preview": ["t"]}
    assert seen["headers"]["x-request-id"] == "abc"
    assert "application/graphql-response+json" in seen["headers"]["accept"]
    assert seen["body"] == {"query": Viewer.document, "operationName": "Viewer", "variables": {}}


@testing.effect
def test_query_method_get_sends_a_query_as_url_params():
    """GraphQLProtocol.layerHttp / queryMethod GET sends a query as URL params over the URL's and caller's; a mutation is still POSTed"""  # noqa: E501
    seen: list[dict[str, Any]] = []

    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        seen.append(
            {
                "method": request.method,
                "accept": request.headers.get("accept"),
                "body": body_text,
                "url": url,
            }
        )
        data = (
            {"data": {"repository": None}}
            if request.method == "GET"
            else {"data": {"addStar": {"ok": True}}}
        )
        return graphql_response(request, data)

    protocol = layer_http(
        url="http://localhost/graphql?tenant=a&query=stale&operationName=Stale", query_method="GET"
    ).pipe(layer.provide(http_client_layer(handler)))

    class Group(GraphQLGroup):
        repo_issues = RepoIssues
        add_star = AddStar

    api = yield from client.make(Group).pipe(fx.provide(protocol))
    variables: RepoIssuesVariables = {"owner": "Effect-TS", "name": "effect"}
    yield from api.repo_issues(variables, url_params={"preview": "t", "query": "ignored"})
    yield from api.add_star()
    query, posted = seen
    assert query["method"] == "GET"
    assert query["body"] is None
    assert "application/graphql-response+json" in query["accept"]
    assert url_params(query["url"]) == {
        "tenant": ["a"],
        "preview": ["t"],
        "query": [RepoIssues.document],
        "operationName": ["RepoIssues"],
        "variables": [json.dumps(variables, separators=(",", ":"))],
    }
    assert posted["method"] == "POST"
    assert json.loads(posted["body"])["operationName"] == "AddStar"


def _host_of(url: Any) -> str:
    return url.host


@testing.effect
def test_a_url_function_routes_by_context_and_operation():
    """GraphQLProtocol.layerHttp / a url function routes queries, mutations and graphql-sse subscriptions by context and operation"""  # noqa: E501
    seen: list[str] = []

    def handler(request: HttpClientRequest, _body: str | None, url: Any) -> Any:
        seen.append(f"{request.method} {_host_of(url)} {url_params(url)['route'][0]}")
        if request.headers.get("accept") == "text/event-stream":
            return _complete_sse(request)
        data = VIEWER_DATA if request.method == "GET" else {"data": {"addStar": {"ok": True}}}
        return graphql_response(request, data)

    def route(options: UrlOptions) -> str:
        host = options.context.get_unsafe(GitHubHost)
        return f"http://{host}/graphql?route={options.kind}.{options.operation_name}"

    protocol = layer_http(url=route, query_method="GET").pipe(
        layer.provide(http_client_layer(handler))
    )
    api = yield from client.make(Routed).pipe(fx.provide(protocol))
    yield from api.viewer()
    yield from api.viewer().pipe(effect.provide_service(GitHubHost, "api.acme.ghe.com"))
    yield from api.add_star(context=Context.make(GitHubHost, "ghes.example.com"))
    yield from (
        api.issue_updated({"id": "I_1"})
        .run_drain()
        .pipe(effect.provide_service(GitHubHost, "api.acme.ghe.com"))
    )
    assert seen == [
        "GET api.github.com query.Viewer",
        "GET api.acme.ghe.com query.Viewer",
        "POST ghes.example.com mutation.AddStar",
        "POST api.acme.ghe.com subscription.IssueUpdated",
    ]


@testing.effect
def test_an_effect_url_is_resolved_in_the_context_of_each_call():
    """GraphQLProtocol.layerHttp / an Effect url is resolved asynchronously in the context of each query, mutation and subscription"""  # noqa: E501
    seen: list[str] = []

    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        seen.append(f"{_host_of(url)} {json.loads(body_text or '')['operationName']}")
        if request.headers.get("accept") == "text/event-stream":
            return _complete_sse(request)
        return graphql_response(
            request, {"data": {"viewer": {"login": "tim"}, "addStar": {"ok": True}}}
        )

    url = (
        effect.yield_now()
        .flat_map(lambda _: GitHubHost())
        .map(lambda host: f"http://{host}/graphql")
    )
    protocol = layer_http(url=url).pipe(layer.provide(http_client_layer(handler)))
    api = yield from client.make(Routed).pipe(fx.provide(protocol))
    yield from api.viewer()
    yield from api.viewer().pipe(effect.provide_service(GitHubHost, "api.acme.ghe.com"))
    yield from api.add_star(context=Context.make(GitHubHost, "ghes.example.com"))
    yield from (
        api.issue_updated({"id": "I_1"})
        .run_drain()
        .pipe(effect.provide_service(GitHubHost, "api.acme.ghe.com"))
    )
    assert seen == [
        "api.github.com Viewer",
        "api.acme.ghe.com Viewer",
        "ghes.example.com AddStar",
        "api.acme.ghe.com IssueUpdated",
    ]


@testing.effect
def test_accepts_an_application_json_body_with_graphql_keys():
    """GraphQLProtocol.layerHttp / accepts an application/json body with GraphQL keys, matching the media type case-insensitively"""  # noqa: E501
    for content_type in ["application/json", "Application/JSON; charset=utf-8"]:
        result = yield from _call_viewer(
            lambda request, _b, _u, ct=content_type: graphql_response(
                request, VIEWER_DATA, content_type=ct
            )
        )
        assert result == {"viewer": {"login": "tim"}}


@testing.effect
def test_a_200_application_json_body_without_data_or_errors_is_a_decode_error():
    """GraphQLProtocol.layerHttp / a 200 application/json body without data or errors is a DecodeError"""  # noqa: E501
    yield from _call_viewer(
        lambda request, _b, _u: graphql_response(
            request, {"ok": True}, content_type="application/json"
        )
    ).pipe(expect_reason(DecodeError))


def _failed_query(status: int) -> Effect[ResponseError, Any]:
    body = {"data": None, "errors": [{"message": "Query failed"}]}
    return _call_viewer(
        lambda request, _b, _u: graphql_response(request, body, status=status)
    ).pipe(expect_reason(ResponseError))


@testing.effect
def test_a_502_with_a_graphql_body_is_a_retryable_response_error():
    """GraphQLProtocol.layerHttp / a 502 with a GraphQL body is a ResponseError with isRetryable: true"""  # noqa: E501
    reason = yield from _failed_query(502)
    assert list(reason.errors) == [{"message": "Query failed"}]
    assert reason.status == 502
    assert reason.is_retryable


@testing.effect
def test_a_400_with_a_graphql_body_is_a_response_error_that_is_not_retryable():
    """GraphQLProtocol.layerHttp / a 400 with a GraphQL body is a ResponseError with isRetryable: false"""  # noqa: E501
    reason = yield from _failed_query(400)
    assert list(reason.errors) == [{"message": "Query failed"}]
    assert reason.status == 400
    assert not reason.is_retryable


@testing.effect
def test_a_429_with_a_graphql_body_carries_a_numeric_retry_after():
    """GraphQLProtocol.layerHttp / a 429 with a GraphQL body is a ResponseError carrying a numeric Retry-After"""  # noqa: E501
    body = {"data": None, "errors": [{"message": "Rate limited"}]}
    reason = yield from _call_viewer(
        lambda request, _b, _u: graphql_response(
            request, body, status=429, headers={"retry-after": "30"}
        )
    ).pipe(expect_reason(ResponseError))
    assert reason.status == 429
    assert reason.retry_after == Seconds(30)
    assert reason.is_retryable


@testing.effect
def test_http_response_headers_reach_middleware_through_next_and_response_error():
    """GraphQLProtocol.layerHttp / HTTP response headers reach middleware through next and ResponseError"""  # noqa: E501

    class RateLimit(GraphQLMiddleware): ...

    class Limited(GraphQLGroup[RateLimit]):
        viewer = Viewer

    seen: list[ExecutionResult] = []
    headers = {"content-type": "application/graphql-response+json", "x-ratelimit-remaining": "0"}
    body = json.dumps(
        {"errors": [{"message": "Rate limited", "extensions": {"code": "RATE_LIMITED"}}]}
    )

    def execute(options: ExecuteOptions) -> Any:
        return options.next(options.request).tap(
            lambda result: effect.sync(lambda: seen.append(result))
        )

    rate_limit = layer.succeed(
        RateLimit,
        Implementation(execute=execute, subscribe=lambda options: options.next(options.request)),
    )
    http = fixture_layer_http(
        lambda request, _b, _u: http_response.make(request, body, headers=headers)
    )
    reason = (
        yield from client.make(Limited)
        .flat_map(lambda api: api.viewer())
        .pipe(fx.provide(layer.merge(http, rate_limit)))
        .pipe(expect_reason(ResponseError))
    )
    assert seen[0].headers == H.from_input(headers)
    assert reason.headers == H.from_input(headers)


@testing.effect
def test_an_application_json_429_whose_errors_is_not_a_list_is_a_transport_error():
    """GraphQLProtocol.layerHttp / an application/json 429 whose errors is not a list is a TransportError carrying its Retry-After"""  # noqa: E501
    headers = {"content-type": "application/json", "retry-after": "5"}
    reason = yield from _call_viewer(
        lambda request, _b, _u: http_response.make(
            request, json.dumps({"errors": "Throttled"}), status=429, headers=headers
        )
    ).pipe(expect_reason(TransportError))
    assert reason.status == 429
    assert reason.retry_after == Seconds(5)


@testing.effect
def test_a_non_graphql_403_is_a_transport_error_carrying_response_headers():
    """GraphQLProtocol.layerHttp / a non-GraphQL 403 is a TransportError carrying response headers without Retry-After"""  # noqa: E501
    headers = {
        "content-type": "text/plain",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": "1791768600",
    }
    reason = yield from _call_viewer(
        lambda request, _b, _u: http_response.make(
            request, "Secondary rate limit", status=403, headers=headers
        )
    ).pipe(expect_reason(TransportError))
    assert reason.status == 403
    assert reason.headers == H.from_input(headers)


@testing.effect
def test_a_non_graphql_503_is_a_transport_error_carrying_a_numeric_retry_after():
    """GraphQLProtocol.layerHttp / a non-GraphQL 503 is a TransportError carrying a numeric Retry-After"""  # noqa: E501
    reason = yield from _call_viewer(lambda request, _b, _u: _unavailable(request, "30")).pipe(
        expect_reason(TransportError)
    )
    assert reason.status == 503
    assert reason.retry_after == Seconds(30)
    assert isinstance(reason.cause, http_error.HttpClientError)


@testing.effect
def test_an_http_date_retry_after_is_measured_from_the_effect_clock():
    """GraphQLProtocol.layerHttp / an HTTP-date Retry-After is measured from the Effect clock"""
    # testing.effect runs under the TestClock, whose current time is the epoch.
    date = formatdate(45, usegmt=True)
    reason = yield from _call_viewer(lambda request, _b, _u: _unavailable(request, date)).pipe(
        expect_reason(TransportError)
    )
    assert reason.retry_after == Seconds(45)


@testing.effect
def test_a_network_failure_is_a_retryable_transport_error_without_status():
    """GraphQLProtocol.layerHttp / a network failure is a retryable TransportError without status"""

    def refuse(request: HttpClientRequest, *_: Any) -> Any:
        reason = http_error.TransportError(request=request, description="ECONNREFUSED")
        return effect.fail(http_error.HttpClientError(reason=reason))

    failing = layer.succeed(HttpClient, http_client.make(refuse))
    protocol = layer_http(url="http://localhost/graphql").pipe(layer.provide(failing))
    reason = (
        yield from client.make(ViewerGroup)
        .flat_map(lambda api: api.viewer())
        .pipe(fx.provide(protocol))
        .pipe(expect_reason(TransportError))
    )
    assert reason.status is None
    assert reason.is_retryable


# --- graphql-sse -----------------------------------------------------------------------

URL = "http://localhost/graphql"
SUBSCRIPTION = GraphQLRequest(
    kind="subscription",
    query=IssueUpdated.document,
    operation_name="IssueUpdated",
    variables={"id": "I_1"},
    headers=H.from_input({"authorization": "Bearer t"}),
    url_params=U.from_input({"preview": "t"}),
)


def _event(title: str) -> dict[str, object]:
    return {"data": {"issueUpdated": {"title": title}}}


def _next(payload: object) -> str:
    return f"event: next\ndata: {json.dumps(payload)}\n\n"


def _event_stream(
    request: HttpClientRequest, chunks: list[str], error: Exception | None = None
) -> Any:
    body: Stream[bytes, object] = stream.from_iterable([chunk.encode() for chunk in chunks])
    if error is not None:
        body = body.concat(stream.fail(error))
    return http_response.make(request, body, headers={"content-type": "text/event-stream"})


def _subscribe(http: Any) -> Stream[Any, TransportError]:
    return stream.unwrap(
        make_http(url=URL)
        .map(lambda protocol: protocol.subscribe(SUBSCRIPTION))
        .pipe(fx.provide(http))
    )


SSE_HEADERS = H.from_input({"content-type": "text/event-stream"})


@testing.effect
def test_posts_with_accept_event_stream_and_emits_next_events_until_complete():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / POSTs with Accept: text/event-stream and emits next events, without a status, until complete"""  # noqa: E501
    seen: dict[str, Any] = {}

    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        seen.update(headers=request.headers, body=json.loads(body_text or ""), url=url)
        chunks = [_next(_event("a")), _next(_event("b")), "event: complete\ndata:\n\n"]
        return _event_stream(request, chunks)

    events = yield from _subscribe(http_client_layer(handler)).run_collect()
    assert [(e.body, e.status, e.headers) for e in events] == [
        (_event("a"), None, SSE_HEADERS),
        (_event("b"), None, SSE_HEADERS),
    ]
    assert "text/event-stream" in seen["headers"]["accept"]
    assert seen["headers"]["authorization"] == "Bearer t"
    assert url_params(seen["url"])["preview"] == ["t"]
    assert seen["body"] == {
        "query": IssueUpdated.document,
        "operationName": "IssueUpdated",
        "variables": {"id": "I_1"},
    }


@testing.effect
def test_a_body_that_ends_without_a_complete_event_is_a_retryable_transport_error():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / a body that ends without a complete event is a retryable TransportError"""  # noqa: E501
    error = (
        yield from _subscribe(
            http_client_layer(lambda request, _b, _u: _event_stream(request, [_next(_event("a"))]))
        )
        .run_drain()
        .flip()
    )
    assert isinstance(error, TransportError)
    assert error.is_retryable


@testing.live
def test_a_complete_event_without_a_data_line_ends_the_stream():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / a complete event without a data: line ends the stream"""  # noqa: E501
    events = (
        yield from _subscribe(
            http_client_layer(
                lambda request, _b, _u: _event_stream(
                    request, [_next(_event("a")), "event: complete\n\n"]
                )
            )
        )
        .run_collect()
        .timeout("2 seconds")
    )
    assert [e.body for e in events] == [_event("a")]


@testing.effect
def test_a_retry_line_becomes_retry_after_when_the_stream_then_fails():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / a retry: line becomes retryAfter when the stream then fails"""  # noqa: E501
    error = (
        yield from _subscribe(
            http_client_layer(
                lambda request, _b, _u: _event_stream(
                    request,
                    [_next(_event("a")), "retry: 3000\n\n"],
                    ConnectionResetError("connection reset"),
                )
            )
        )
        .run_drain()
        .flip()
    )
    assert isinstance(error, TransportError)
    assert error.is_retryable
    assert error.retry_after == Seconds(3)


@testing.effect
def test_a_graphql_error_response_instead_of_a_stream_fails_with_response_error():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / a GraphQL error response instead of a stream fails the client stream with ResponseError"""  # noqa: E501
    protocol = layer_http(url=URL).pipe(
        layer.provide(
            http_client_layer(
                lambda request, _b, _u: graphql_response(
                    request, {"errors": [{"message": "denied"}]}, status=400
                )
            )
        )
    )
    reason = (
        yield from stream.unwrap(
            client.make(IssuesGroup)
            .map(lambda api: api.issue_updated({"id": "I_1"}))
            .pipe(fx.provide(protocol))
        )
        .run_drain()
        .pipe(expect_reason(ResponseError))
    )
    assert list(reason.errors) == [{"message": "denied"}]
    assert reason.status == 400


@testing.effect
def test_a_client_stream_refused_with_403_and_retry_after_reconnects_after_the_delay():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / a client stream refused with 403 and Retry-After reconnects after the delay"""  # noqa: E501
    attempts = [0]

    def handler(request: HttpClientRequest, _b: str | None, _u: Any) -> Any:
        attempts[0] += 1
        if attempts[0] == 1:
            body = json.dumps({"message": "You have exceeded a secondary rate limit"})
            headers = {"content-type": "application/json", "retry-after": "2"}
            return http_response.make(request, body, status=403, headers=headers)
        return _event_stream(request, [_next(_event("a")), "event: complete\ndata:\n\n"])

    protocol = layer_http(url=URL).pipe(layer.provide(http_client_layer(handler)))
    fiber = (
        yield from stream.unwrap(
            client.make(IssuesGroup)
            .map(lambda api: api.issue_updated({"id": "I_1"}))
            .pipe(fx.provide(protocol))
        )
        .run_collect()
        .fork()
    )
    yield from testing.adjust("1999 millis")
    assert attempts[0] == 1
    yield from testing.adjust("1 millis")
    assert (yield from fiber.join()) == [{"issueUpdated": {"title": "a"}}]
    assert attempts[0] == 2


@testing.effect
def test_interrupting_the_stream_aborts_the_request():
    """GraphQLProtocol.layerHttp subscriptions (graphql-sse distinct mode) / interrupting the stream aborts the request"""  # noqa: E501
    signals: list[Any] = []

    def send(request: HttpClientRequest, _url: Any, signal: Any, _fiber: Any) -> Any:
        signals.append(signal)
        body: Stream[bytes, object] = stream.make(_next(_event("a")).encode()).concat(stream.never)
        return effect.succeed(
            http_response.make(request, body, headers={"content-type": "text/event-stream"})
        )

    http = layer.succeed(HttpClient, http_client.make(send))
    received = yield from Deferred[None].make()
    fiber = yield from _subscribe(http).run_for_each(lambda _: received.succeed(None)).fork()
    yield from received.wait()
    assert not signals[0].aborted
    yield from fiber.interrupt()
    assert signals[0].aborted
