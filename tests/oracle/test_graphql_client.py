"""Ports of Effect's graphql/GraphQLClient.test.ts, GraphQLClient.pages.test.ts,
GraphQLClient.makeTest.test.ts and GraphQLClient.subscriptions.test.ts. Each
test's docstring is the Effect test title, prefixed by its describe blocks.

Groups are classes: ``ViewerGroup.middleware(Auth)`` is a group class
declared ``GraphQLGroup[Auth]``, and middleware of single operations is
declared as its second type argument (``GraphQLGroup[Never, Auth]``) so that
``make`` requires it, as Effect's ``make`` does; ``make_test`` handlers are keyed by the
group's attribute names. The makeTest check of an operation named after an
``Object.prototype`` method has no Python counterpart (attribute names are
plain identifiers) and is left out of that test.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, TypedDict

import pyfect as fx
from pyfect import effect, layer, schedule, stream, testing
from pyfect import schema as S
from pyfect.context import Context, Tag
from pyfect.duration import Seconds
from pyfect.effect import Effect
from pyfect.exit import Failure
from pyfect.graphql import (
    GraphQLGroup,
    GraphQLMiddleware,
    Implementation,
    client,
    map_request,
    query,
)
from pyfect.graphql.client import UnimplementedError
from pyfect.graphql.client_error import (
    DecodeError,
    EncodeError,
    PaginationError,
    ResponseError,
    TransportError,
)
from pyfect.graphql.middleware import ExecuteOptions, SubscribeOptions
from pyfect.graphql.protocol import Answer, GraphQLRequest
from pyfect.http import headers as H
from pyfect.schedule import Stop
from pyfect.stream import Stream

from ._graphql import (
    VIEWER_RESULT,
    IssuesGroup,
    RepoIssues,
    RepoIssuesVariables,
    Viewer,
    ViewerGroup,
    execute_layer,
    expect_reason,
    protocol_layer,
)


class CurrentUser(Tag[str]): ...


class TokenExpired(S.TaggedError):
    user: str


class Auth(GraphQLMiddleware[TokenExpired, CurrentUser]): ...


class OpA(GraphQLMiddleware): ...


class OpB(GraphQLMiddleware): ...


class GroupA(GraphQLMiddleware): ...


class GroupB(GraphQLMiddleware): ...


def _authorize(
    request: GraphQLRequest, _operation: object
) -> Effect[GraphQLRequest, TokenExpired, CurrentUser]:
    assert isinstance(request.headers, H.Headers)
    assert "X-Request-Id" not in dict(request.headers)

    def with_user(user: str) -> Effect[GraphQLRequest, TokenExpired]:
        if user == "expired":
            return effect.fail(TokenExpired(user=user))
        headers = request.headers.set("authorization", f"Bearer {user}")
        return effect.succeed(replace(request, headers=headers))

    return CurrentUser().flat_map(with_user)


AUTH_LIVE = layer.succeed(Auth, map_request(_authorize))

VIEWER_DATA = {"data": {"viewer": {"login": "tim"}}}
VARIABLES: RepoIssuesVariables = {"owner": "Effect-TS", "name": "effect"}
PARTIAL_ISSUES = {
    "data": {
        "repository": {
            "issues": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [{"number": 1, "title": "Hi", "createdAt": "2026-01-01T00:00:00Z"}, None],
            }
        }
    },
    "errors": [
        {"type": "NOT_FOUND", "message": "Not found", "path": ["repository", "issues", "nodes", 1]}
    ],
}


def _plain(value: object) -> object:
    return json.loads(json.dumps(value))


class AuthedViewer(GraphQLGroup[Auth]):
    viewer = Viewer


def _repo_issues_client(result: object) -> Effect[IssuesGroup, Any, Any]:
    protocol, _ = execute_layer(result)
    return client.make(IssuesGroup).pipe(fx.provide(protocol))


@testing.effect
def test_group_middleware_runs_outside_operation_middleware():
    """GraphQLClient / middleware / group middleware runs outside operation middleware, attach order within a level"""  # noqa: E501
    log: list[str] = []

    def record(name: str) -> Implementation:
        def step(request: GraphQLRequest, _operation: object) -> Effect[GraphQLRequest]:
            return effect.sync(lambda: log.append(name)).as_(request)

        return map_request(step)

    class Group(GraphQLGroup[GroupA | GroupB, OpA | OpB]):
        viewer = Viewer.middleware(OpA).middleware(OpB)

    protocol, _ = execute_layer(VIEWER_DATA)
    services = layer.merge(
        protocol,
        layer.succeed(OpA, record("OpA")),
        layer.succeed(OpB, record("OpB")),
        layer.succeed(GroupA, record("GroupA")),
        layer.succeed(GroupB, record("GroupB")),
    )
    yield from client.make(Group).flat_map(lambda api: api.viewer()).pipe(fx.provide(services))
    assert log == ["GroupA", "GroupB", "OpA", "OpB"]


@testing.effect
def test_map_request_transforms_the_request_and_its_errors_reach_the_caller():
    """GraphQLClient / middleware / mapRequest transforms the request and its errors reach the caller"""  # noqa: E501
    protocol, requests = execute_layer(VIEWER_DATA)
    api = yield from client.make(AuthedViewer).pipe(fx.provide(layer.merge(protocol, AUTH_LIVE)))
    yield from api.viewer().pipe(effect.provide_service(CurrentUser, "tim"))
    assert requests[0].headers["authorization"] == "Bearer tim"
    error = yield from api.viewer().pipe(effect.provide_service(CurrentUser, "expired")).flip()
    assert isinstance(error, TokenExpired)
    assert len(requests) == 1


@testing.effect
def test_per_call_context_provides_services_and_headers_are_normalized():
    """GraphQLClient / middleware / per-call context provides services and headers are normalized before middleware"""  # noqa: E501
    protocol, requests = execute_layer(VIEWER_DATA)
    api = yield from client.make(AuthedViewer).pipe(fx.provide(layer.merge(protocol, AUTH_LIVE)))
    call = api.viewer(context=Context.make(CurrentUser, "ctx"), headers=[("X-Request-Id", "abc")])
    yield from call.pipe(effect.provide_service(CurrentUser, "unused"))
    assert requests[0].headers == H.from_input(
        {"authorization": "Bearer ctx", "x-request-id": "abc"}
    )


@testing.effect
def test_middleware_see_the_transport_status_from_next_and_may_rewrite_it():
    """GraphQLClient / middleware / middleware see the transport status from next and may rewrite it; ResponseError carries it"""  # noqa: E501

    class Status(GraphQLMiddleware): ...

    def execute(options: ExecuteOptions) -> Any:
        return options.next(options.request).map(
            lambda result: replace(result, status=403 if result.status == 401 else 500)
        )

    def subscribe(options: SubscribeOptions) -> Any:
        return options.next(options.request)

    class StatusViewer(GraphQLGroup[Status]):
        viewer = Viewer

    protocol, _ = execute_layer({"errors": [{"message": "denied"}]}, 401)
    status_live = layer.succeed(Status, Implementation(execute=execute, subscribe=subscribe))
    reason = (
        yield from client.make(StatusViewer)
        .flat_map(lambda api: api.viewer())
        .pipe(fx.provide(layer.merge(protocol, status_live)))
        .pipe(expect_reason(ResponseError))
    )
    assert reason.status == 403


@testing.effect
def test_encodes_variables_through_the_custom_scalar_codec():
    """GraphQLClient / encodes variables through the custom scalar codec"""
    protocol, requests = execute_layer({"data": {"repository": None}})
    since = datetime(2026, 1, 1, tzinfo=UTC)
    yield from (
        client.make(IssuesGroup)
        .flat_map(
            lambda api: api.repo_issues({"owner": "Effect-TS", "name": "effect", "since": since})
        )
        .pipe(fx.provide(protocol))
    )
    [request] = requests
    assert request.operation_name == "RepoIssues"
    assert request.query == RepoIssues.document
    assert request.variables == {**VARIABLES, "since": "2026-01-01T00:00:00.000Z"}


class First(TypedDict):
    first: int


@testing.effect
def test_a_rejected_input_is_an_encode_error_and_nothing_is_sent():
    """GraphQLClient / a rejected input is an EncodeError and nothing is sent"""
    first = query(
        "First",
        document="query First($first:Int!){viewer{login}}",
        variables=S.Struct(First, first=S.Int.check(S.is_greater_than(0))),
        result=VIEWER_RESULT,
    )

    class Group(GraphQLGroup):
        first_viewer = first

    protocol, requests = execute_layer(VIEWER_DATA)
    yield from (
        client.make(Group)
        .flat_map(lambda api: api.first_viewer({"first": 0}))
        .pipe(fx.provide(protocol))
        .pipe(expect_reason(EncodeError))
    )
    assert requests == []


@testing.effect
def test_a_response_with_errors_fails_with_response_error():
    """GraphQLClient / a response with errors fails with ResponseError carrying the raw data and errors"""  # noqa: E501
    api = yield from _repo_issues_client(PARTIAL_ISSUES)
    reason = yield from api.repo_issues(VARIABLES).pipe(expect_reason(ResponseError))
    assert reason.data == PARTIAL_ISSUES["data"]
    assert _plain(reason.errors) == PARTIAL_ISSUES["errors"]


@testing.effect
def test_data_that_does_not_match_the_result_schema_is_a_decode_error():
    """GraphQLClient / data that does not match the result schema is a DecodeError"""
    protocol, _ = execute_layer({"data": {"viewer": {"login": 42}}})
    yield from (
        client.make(ViewerGroup)
        .flat_map(lambda api: api.viewer())
        .pipe(fx.provide(protocol))
        .pipe(expect_reason(DecodeError))
    )


@testing.effect
def test_partial_returns_decoded_data_alongside_the_errors():
    """GraphQLClient / partial: true / returns decoded data alongside the errors"""
    api = yield from _repo_issues_client(PARTIAL_ISSUES)
    partial = yield from api.repo_issues(VARIABLES, partial=True)
    repository = partial.data["repository"]
    assert repository is not None and repository["issues"] is not None
    nodes = repository["issues"]["nodes"]
    assert nodes is not None and nodes[0] is not None
    assert nodes[0]["title"] == "Hi"
    assert _plain(partial.errors) == PARTIAL_ISSUES["errors"]


@testing.effect
def test_partial_data_null_plus_errors_is_a_response_error():
    """GraphQLClient / partial: true / data: null plus errors is a ResponseError"""
    api = yield from _repo_issues_client({"data": None, "errors": [{"message": "boom"}]})
    yield from api.repo_issues(VARIABLES, partial=True).pipe(expect_reason(ResponseError))


@testing.effect
def test_data_null_with_no_errors_is_a_decode_error():
    """GraphQLClient / data: null with no errors is a DecodeError even when the result codec accepts null"""  # noqa: E501
    raw = query("Raw", document="query Raw{__typename}", result=S.Json)

    class Group(GraphQLGroup):
        raw_query = raw

    protocol, _ = execute_layer({"data": None})
    api = yield from client.make(Group).pipe(fx.provide(protocol))
    yield from api.raw_query().pipe(expect_reason(DecodeError))
    yield from api.raw_query(partial=True).pipe(expect_reason(DecodeError))


# --- pages / items ---------------------------------------------------------------------


def _issue(number: int) -> dict[str, object]:
    return {"number": number, "title": f"#{number}", "createdAt": "2026-01-01T00:00:00Z"}


def _page(nodes: list[object], has_next_page: bool, end_cursor: str | None) -> dict[str, object]:
    page_info = {"hasNextPage": has_next_page, "endCursor": end_cursor}
    return {"data": {"repository": {"issues": {"pageInfo": page_info, "nodes": nodes}}}}


NO_REPOSITORY = {"data": {"repository": None}}
TWO_PAGES: dict[str, object] = {
    "start": _page([_issue(1), None], True, "c1"),
    "c1": _page([_issue(2)], False, None),
}


def _paged_client(
    pages: dict[str, object],
) -> tuple[Effect[IssuesGroup, Any, Any], list[GraphQLRequest]]:
    requests: list[GraphQLRequest] = []

    def execute(request: GraphQLRequest) -> Effect[Answer, TransportError]:
        def answer() -> Answer:
            requests.append(request)
            variables: Any = request.variables
            return Answer(body=pages[variables.get("after") or "start"])

        return effect.sync(answer)

    return client.make(IssuesGroup).pipe(fx.provide(protocol_layer(execute=execute))), requests


def _issues_of(result: Any) -> Any:
    repository = result["repository"]
    return None if repository is None else repository["issues"]


@testing.effect
def test_pages_passes_end_cursor_as_after_until_has_next_page_is_false():
    """GraphQLClient.pages / items / pages passes endCursor as $after until hasNextPage is false"""
    make, requests = _paged_client(TWO_PAGES)
    api = yield from make
    pages = yield from client.pages(
        api.repo_issues, variables=VARIABLES, connection=_issues_of
    ).run_collect()
    assert [p["pageInfo"]["endCursor"] for p in pages] == ["c1", None]
    sent: list[Any] = [r.variables for r in requests]
    assert [v.get("after") for v in sent] == [None, "c1"]


@testing.effect
def test_items_flattens_nodes_across_pages_and_keeps_null_entries():
    """GraphQLClient.pages / items / items flattens nodes across pages and keeps null entries"""
    make, _ = _paged_client(TWO_PAGES)
    api = yield from make
    items = yield from client.items(
        api.repo_issues, variables=VARIABLES, connection=_issues_of
    ).run_collect()
    assert [None if i is None else i["number"] for i in items] == [1, None, 2]


@testing.effect
def test_options_are_forwarded_to_every_page_request():
    """GraphQLClient.pages / items / options are forwarded to every page request"""
    make, requests = _paged_client(TWO_PAGES)
    api = yield from make
    options = client.PageOptions(headers={"x-page-run": "1"}, url_params={"preview": "t"})
    yield from client.pages(
        api.repo_issues, variables=VARIABLES, connection=_issues_of, options=options
    ).run_drain()
    assert [r.headers["x-page-run"] for r in requests] == ["1", "1"]
    assert [list(r.url_params.get_all("preview")) for r in requests] == [["t"], ["t"]]


@testing.effect
def test_a_null_connection_on_the_first_page_is_an_empty_stream():
    """GraphQLClient.pages / items / a null connection on the first page is an empty stream"""
    make, _ = _paged_client({"start": NO_REPOSITORY})
    api = yield from make
    pages = yield from client.pages(
        api.repo_issues, variables=VARIABLES, connection=_issues_of
    ).run_collect()
    assert pages == []


@testing.effect
def test_a_null_connection_on_a_later_page_is_a_pagination_error():
    """GraphQLClient.pages / items / a null connection on a later page is a PaginationError naming the cursor used"""  # noqa: E501
    make, _ = _paged_client({**TWO_PAGES, "c1": NO_REPOSITORY})
    api = yield from make
    pages = client.pages(api.repo_issues, variables=VARIABLES, connection=_issues_of)
    reason = yield from pages.run_collect().pipe(expect_reason(PaginationError))
    assert reason.cursor == "c1"


@testing.effect
def test_a_cursor_that_does_not_advance_is_a_pagination_error():
    """GraphQLClient.pages / items / a cursor that does not advance is a PaginationError instead of a refetch"""  # noqa: E501
    make, requests = _paged_client({**TWO_PAGES, "c1": _page([_issue(2)], True, "c1")})
    api = yield from make
    pages = client.pages(api.repo_issues, variables=VARIABLES, connection=_issues_of)
    reason = yield from pages.run_collect().pipe(expect_reason(PaginationError))
    assert reason.cursor == "c1"
    assert len(requests) == 2


# --- makeTest --------------------------------------------------------------------------


def _test_page(
    nodes: list[object], has_next_page: bool, end_cursor: str | None
) -> dict[str, object]:
    page_info = {"hasNextPage": has_next_page, "endCursor": end_cursor}
    return {"repository": {"issues": {"pageInfo": page_info, "nodes": nodes}}}


class Login(TypedDict):
    login: str


NullableVariables = query(
    "NullableVariables",
    document="query NullableVariables{viewer{login}}",
    variables=S.NullOr(S.Struct(Login)),
    result=VIEWER_RESULT,
)


class NullableGroup(GraphQLGroup):
    nullable_variables = NullableVariables


@testing.effect
def test_a_handled_query_returns_the_handlers_value():
    """GraphQLClient.makeTest / a handled query returns the handler's value and receives the caller's variables"""  # noqa: E501
    result = _test_page([_issue(1)], False, None)
    received: list[object] = []

    def handler(variables: object, _options: object) -> Effect[Any]:
        received.append(variables)
        return effect.succeed(result)

    api = client.make_test(IssuesGroup, repo_issues=handler)
    called: RepoIssuesVariables = {**VARIABLES, "since": datetime(2026, 1, 1, tzinfo=UTC)}
    assert (yield from api.repo_issues(called)) is result
    assert received[0] is called

    def nullable_handler(variables: object, _options: object) -> Effect[Any]:
        received.append(variables)
        return effect.succeed({"viewer": {"login": "tim"}})

    nullable = client.make_test(NullableGroup, nullable_variables=nullable_handler)
    yield from nullable.nullable_variables(None)
    assert received[1] is None


@testing.effect
def test_make_test_partial_returns_the_handlers_value_as_data_with_no_errors():
    """GraphQLClient.makeTest / partial: true returns the handler's value as data with no errors"""
    result = _test_page([_issue(1)], False, None)
    api = client.make_test(IssuesGroup, repo_issues=lambda _v, _o: effect.succeed(result))
    partial = yield from api.repo_issues(VARIABLES, partial=True)
    assert partial.data is result
    assert partial.errors == ()


@testing.effect
def test_an_operation_without_a_handler_dies_with_an_unimplemented_error():
    """GraphQLClient.makeTest / an operation without a handler dies with an UnimplementedError"""
    api = client.make_test(IssuesGroup)
    exit = yield from api.repo_issues(VARIABLES).exit()
    assert isinstance(exit, Failure)
    defect = exit.cause.squash()
    assert isinstance(defect, UnimplementedError)
    assert str(defect) == 'GraphQLClient: Unimplemented operation "RepoIssues"'


@testing.effect
def test_pages_drives_a_mock_method_across_two_pages():
    """GraphQLClient.makeTest / GraphQLClient.pages drives a mock method across two pages"""
    cursors: list[object] = []

    def handler(variables: Any, _options: object) -> Effect[Any]:
        after = variables.get("after")
        cursors.append(after)
        if after == "c1":
            return effect.succeed(_test_page([_issue(2)], False, None))
        return effect.succeed(_test_page([_issue(1)], True, "c1"))

    api = client.make_test(IssuesGroup, repo_issues=handler)
    pages = yield from client.pages(
        api.repo_issues, variables=VARIABLES, connection=_issues_of
    ).run_collect()
    assert [[i["number"] for i in p["nodes"]] for p in pages] == [[1], [2]]
    assert cursors == [None, "c1"]


@testing.effect
def test_layer_test_provides_the_mock_client_through_the_service_tag():
    """GraphQLClient.makeTest / layerTest provides the mock client through the service tag"""

    class Issues(Tag[IssuesGroup]): ...

    result = _test_page([_issue(1)], False, None)
    test_layer = client.layer_test(
        Issues, IssuesGroup, repo_issues=lambda _v, _o: effect.succeed(result)
    )
    actual = (
        yield from Issues()
        .flat_map(lambda api: api.repo_issues(VARIABLES))
        .pipe(fx.provide(test_layer))
    )
    assert actual is result


# --- subscriptions ---------------------------------------------------------------------


def _event(title: str) -> dict[str, object]:
    return {"data": {"issueUpdated": {"title": title}}}


def _lost(**fields: Any) -> Stream[Any, TransportError]:
    given: dict[str, Any] = {"description": "connection lost", **fields}
    return stream.fail(TransportError(**given))


def _scripted(attempts: list[Stream[Any, TransportError]]) -> tuple[Any, list[int]]:
    count = [0]

    def subscribe(_request: GraphQLRequest) -> Stream[Answer, TransportError]:
        def attempt() -> Stream[Answer, TransportError]:
            count[0] += 1
            n = count[0]
            body = (
                attempts[n - 1]
                if n <= len(attempts)
                else stream.die(AssertionError(f"attempt {n}"))
            )
            return body.map(lambda b: Answer(body=b))

        return stream.suspend(attempt)

    return protocol_layer(subscribe=subscribe), count


def _subscribe(protocol: Any, **options: Any) -> Stream[Any, Any, Any]:
    return stream.unwrap(
        client.make(IssuesGroup, **options)
        .map(lambda api: api.issue_updated({"id": "I_1"}))
        .pipe(fx.provide(protocol))
    )


@testing.effect
def test_emits_each_decoded_event_and_ends_when_the_transport_completes():
    """GraphQLClient subscriptions / emits each decoded event and ends when the transport completes"""  # noqa: E501
    protocol, _ = _scripted([stream.make(_event("a"), _event("b"))])
    events = yield from _subscribe(protocol).run_collect()
    assert events == [{"issueUpdated": {"title": "a"}}, {"issueUpdated": {"title": "b"}}]


@testing.effect
def test_an_event_with_errors_fails_the_stream_without_retrying():
    """GraphQLClient subscriptions / an event with errors fails the stream with ResponseError without retrying"""  # noqa: E501
    received: list[str] = []
    protocol, attempts = _scripted(
        [stream.make(_event("a"), {"data": None, "errors": [{"message": "gone"}]}, _event("c"))]
    )
    reason = (
        yield from _subscribe(protocol)
        .run_for_each(lambda e: effect.sync(lambda: received.append(e["issueUpdated"]["title"])))
        .pipe(expect_reason(ResponseError))
    )
    assert list(reason.errors) == [{"message": "gone"}]
    assert reason.status is None
    assert not reason.is_retryable
    assert received == ["a"]
    assert attempts[0] == 1


@testing.effect
def test_retries_a_retryable_transport_error_on_the_default_schedule():
    """GraphQLClient subscriptions / retries a retryable TransportError on the default schedule (500ms, then x1.5)"""  # noqa: E501
    protocol, attempts = _scripted([_lost(), _lost(), stream.make(_event("a"))])
    fiber = yield from _subscribe(protocol).run_collect().fork()
    yield from testing.adjust(0.499)
    assert attempts[0] == 1
    yield from testing.adjust(0.001)
    assert attempts[0] == 2
    yield from testing.adjust(0.749)
    assert attempts[0] == 2
    yield from testing.adjust(0.001)
    assert attempts[0] == 3
    assert (yield from fiber.join()) == [{"issueUpdated": {"title": "a"}}]


@testing.effect
def test_waits_for_retry_after_when_the_transport_reports_one():
    """GraphQLClient subscriptions / waits for retryAfter when the transport reports one"""
    protocol, attempts = _scripted([_lost(retry_after=Seconds(2)), stream.make(_event("a"))])
    fiber = yield from _subscribe(protocol).run_collect().fork()
    yield from testing.adjust(1.999)
    assert attempts[0] == 1
    yield from testing.adjust(0.001)
    assert attempts[0] == 2
    yield from fiber.join()


@testing.effect
def test_a_fatal_close_code_fails_the_stream_without_retrying():
    """GraphQLClient subscriptions / a fatal close code fails the stream without retrying"""
    protocol, attempts = _scripted([_lost(close_code=4401), stream.make(_event("a"))])
    reason = yield from _subscribe(protocol).run_collect().pipe(expect_reason(TransportError))
    assert reason.close_code == 4401
    assert attempts[0] == 1


@testing.effect
def test_fails_with_the_last_transport_error_once_subscription_retry_is_exhausted():
    """GraphQLClient subscriptions / fails with the last TransportError once subscriptionRetry is exhausted"""  # noqa: E501
    protocol, attempts = _scripted([_lost(), _lost(description="lost again"), _lost()])
    run = _subscribe(protocol, subscription_retry=schedule.recurs(1)).run_collect()
    fiber = yield from run.pipe(expect_reason(TransportError)).fork()
    yield from testing.adjust(60)
    assert (yield from fiber.join()).description == "lost again"
    assert attempts[0] == 2


@testing.effect
def test_a_middleware_failure_is_not_retried_and_does_not_step_subscription_retry():
    """GraphQLClient subscriptions / a middleware failure is not retried and does not step subscriptionRetry"""  # noqa: E501
    failure = RuntimeError("subscription denied")

    class Reject(GraphQLMiddleware[RuntimeError]): ...

    subscribes = [0]
    steps = [0]

    def reject(_options: SubscribeOptions) -> Stream[Any, RuntimeError]:
        def run() -> Stream[Any, RuntimeError]:
            subscribes[0] += 1
            return stream.fail(failure)

        return stream.suspend(run)

    def step(_now: float, _input: object) -> Effect[Any]:
        return effect.sync(lambda: steps.__setitem__(0, steps[0] + 1)).as_(Stop(None))

    retry = schedule.from_step(effect.succeed(step))

    class Rejected(GraphQLGroup[Reject]):
        issue_updated = IssuesGroup.issue_updated

    reject_live = layer.succeed(
        Reject,
        Implementation(execute=lambda options: options.next(options.request), subscribe=reject),
    )
    error = (
        yield from stream.unwrap(
            client.make(Rejected, subscription_retry=retry)
            .map(lambda api: api.issue_updated({"id": "I_1"}))
            .pipe(fx.provide(layer.merge(protocol_layer(), reject_live)))
        )
        .run_collect()
        .flip()
    )
    assert error is failure
    assert subscribes[0] == 1
    assert steps[0] == 0
