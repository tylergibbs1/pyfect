"""Ports of Effect's graphql/GraphQLResolver.test.ts. Each test's docstring
is the Effect test title, prefixed by its describe blocks; the two URL
forms are one parametrized test."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, Literal, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, layer, testing
from pyfect import schema as S
from pyfect.batching import RequestResolver
from pyfect.context import Context, Reference, Tag
from pyfect.effect import Effect
from pyfect.errors import NoSuchElementException
from pyfect.graphql import GraphQLGroup, GraphQLMiddleware, client, map_request, query, resolver
from pyfect.graphql.client_error import DecodeError, GraphQLClientError, ResponseError
from pyfect.graphql.protocol import Answer, GraphQLRequest, layer_http
from pyfect.graphql.template import DocumentTemplate, Selection, Variable
from pyfect.http import headers as H
from pyfect.http.request import HttpClientRequest
from pyfect.result import Ok

from ._graphql import graphql_response, http_client_layer, protocol_layer

# Functional syntax: ``__typename`` in a class body would be name-mangled.
Repository = TypedDict("Repository", {"__typename": Literal["Repository"], "nameWithOwner": str})
User = TypedDict("User", {"__typename": Literal["User"], "login": str})


NODE = S.Union(S.Struct(Repository), S.Struct(User))


class Ids(TypedDict):
    ids: Sequence[str]


class Nodes(TypedDict):
    nodes: Sequence[Repository | User | None]


RepoNodes = query(
    "RepoNodes",
    document="query RepoNodes($ids:[ID!]!){nodes(ids:$ids){__typename ...on Repository{nameWithOwner} ...on User{login}}}",  # noqa: E501
    variables=S.Struct(Ids),
    result=S.Struct(Nodes, nodes=S.Array(S.NullOr(NODE))),
)


class SearchQuery(TypedDict):
    query: str


class PageInfo(TypedDict):
    hasNextPage: bool
    endCursor: str | None


class Search(TypedDict):
    pageInfo: PageInfo
    nodes: Sequence[Repository | User | None] | None


class SearchResult(TypedDict):
    search: Search


SearchRepos = query(
    "SearchRepos",
    document="query SearchRepos($query:String!){search(query:$query,type:REPOSITORY,first:100){pageInfo{hasNextPage endCursor} nodes{__typename ...on Repository{nameWithOwner} ...on User{login}}}}",  # noqa: E501
    variables=S.Struct(SearchQuery),
    result=S.Struct(SearchResult, search=S.Struct(Search, nodes=S.NullOr(S.Array(S.NullOr(NODE))))),
)


class PullRequestVariables(TypedDict):
    name: str
    number: int


class Title(TypedDict):
    title: str


class PullRequestRepository(TypedDict):
    pullRequest: Title | None


class PullRequestResult(TypedDict):
    repository: PullRequestRepository | None


# Generated operations carry a document template, which ``aliased``
# repeats once per slice.
PullRequest = query(
    "PullRequest",
    document=DocumentTemplate(
        variables=(Variable("name", "String!"), Variable("number", "Int!")),
        selections=(
            Selection(
                name="repository",
                body=(
                    '(owner:"Effect-TS",name:$',
                    "name",
                    "){pullRequest(number:$",
                    "number",
                    "){title}}",
                ),
            ),
        ),
    ),
    variables=S.Struct(PullRequestVariables),
    result=S.Struct(PullRequestResult),
)


class RepoIssuesVariables(TypedDict):
    name: str
    after: NotRequired[str | None]


class TotalCount(TypedDict):
    totalCount: int


class IssuesRepository(TypedDict):
    issues: TotalCount


class RepoIssuesResult(TypedDict):
    repository: IssuesRepository | None


RepoIssues = query(
    "RepoIssues",
    document=DocumentTemplate(
        variables=(Variable("name", "String!"), Variable("after", "String")),
        selections=(
            Selection(
                name="repository",
                body=(
                    '(owner:"Effect-TS",name:$',
                    "name",
                    "){issues(after:$",
                    "after",
                    "){totalCount}}",
                ),
            ),
        ),
    ),
    variables=S.Struct(RepoIssuesVariables),
    result=S.Struct(RepoIssuesResult),
)


class CurrentUser(Tag[str]): ...


class Auth(GraphQLMiddleware[Any, CurrentUser]): ...


def _authorize(
    request: GraphQLRequest, _operation: object
) -> Effect[GraphQLRequest, Any, CurrentUser]:
    return CurrentUser().map(
        lambda tenant: replace(
            request, headers=request.headers.set("authorization", f"Bearer {tenant}")
        )
    )


AUTH_LIVE = layer.succeed(Auth, map_request(_authorize))


class AllGroup(GraphQLGroup):
    repo_nodes = RepoNodes
    search_repos = SearchRepos
    pull_request = PullRequest
    repo_issues = RepoIssues


def sent_variables(request: GraphQLRequest) -> Any:
    return request.variables


def repo(name_with_owner: str) -> dict[str, str]:
    return {"__typename": "Repository", "nameWithOwner": name_with_owner}


def make_client(
    respond: Callable[[Any], object], headers: H.Headers | None = None
) -> Effect[tuple[Any, list[GraphQLRequest]]]:
    """Answers each request with ``respond(variables)`` and records the
    requests."""
    requests: list[GraphQLRequest] = []

    def execute(request: GraphQLRequest) -> Effect[Answer, Any]:
        def answer() -> Answer:
            requests.append(request)
            return Answer(body=respond(request.variables), status=200, headers=headers)

        return effect.sync(answer)

    return (
        client.make(AllGroup)
        .pipe(fx.provide(protocol_layer(execute=execute)))
        .map(lambda api: (api, requests))
    )


def resolve_all(keys: Sequence[Any], get: Callable[[Any], Effect[Any, Any]]) -> Effect[list[Any]]:
    """Requests every key concurrently and returns each lookup's success
    or failure."""

    def one(key: Any) -> Effect[Any]:
        return get(key).result().map(lambda r: r.value if isinstance(r, Ok) else r.error)

    return fx.for_each(keys, one, concurrency="unbounded")


def by_id(api: Any) -> Callable[[str], Effect[Any, Any]]:
    return resolver.request(
        resolver.ordered(
            api.repo_nodes,
            variables=lambda ids: {"ids": list(ids)},
            path=("nodes",),
            typename="Repository",
        )
    )


def by_name(api: Any) -> Callable[[str], Effect[Any, Any]]:
    return resolver.request(
        resolver.find_by_id(
            api.search_repos,
            key=lambda found: found["nameWithOwner"],
            variables=lambda names: {"query": " ".join(f"repo:{name}" for name in names)},
            path=("search", "nodes"),
            typename="Repository",
        )
    )


def search_names(variables: Any) -> list[str]:
    return [term[5:] for term in variables["query"].split(" ")]


def search_result(nodes: Sequence[object], has_next_page: bool = False) -> object:
    return {
        "data": {
            "search": {
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": None},
                "nodes": nodes,
            }
        }
    }


def slices(variables: Any) -> dict[str, dict[str, Any]]:
    """Splits batched variables (``_0_name``, ``_1_name``, ...) into each
    slice's variables, keyed by prefix."""
    out: dict[str, dict[str, Any]] = {}
    for key, value in variables.items():
        found = re.match(r"^(_\d+_)(.+)$", key)
        assert found is not None
        out.setdefault(found[1], {})[found[2]] = value
    return out


def answer_slices(variables: Any, respond: Callable[[Any], object]) -> dict[str, object]:
    """Answers every slice with ``respond(variables)`` under its aliased
    ``repository`` field."""
    return {f"{prefix}repository": respond(each) for prefix, each in slices(variables).items()}


def pull_request(variables: Any) -> dict[str, object]:
    return {"pullRequest": {"title": f"{variables['name']}#{variables['number']}"}}


def get_pull_request(api: Any) -> Callable[[Any], Effect[Any, Any]]:
    return resolver.request(resolver.aliased(api.pull_request))


LOOKUPS: list[PullRequestVariables] = [
    {"name": "effect", "number": 1},
    {"name": "effect", "number": 2},
]


# --- ordered ---------------------------------------------------------------------------


@testing.effect
def test_ordered_batches_concurrent_keys_into_one_call():
    """GraphQLResolver / ordered / batches concurrent keys into one call; a null item or a typename mismatch is a miss"""  # noqa: E501
    store = {"R_1": repo("Effect-TS/effect"), "U_1": {"__typename": "User", "login": "tim"}}
    api, requests = yield from make_client(
        lambda variables: {"data": {"nodes": [store.get(id) for id in variables["ids"]]}}
    )

    results = yield from resolve_all(["R_1", "R_2", "U_1", "R_1"], by_id(api))

    assert len(requests) == 1
    assert sorted(sent_variables(requests[0])["ids"]) == ["R_1", "R_2", "U_1"]
    assert results[0] == repo("Effect-TS/effect")
    assert results[3] == repo("Effect-TS/effect")
    assert isinstance(results[1], NoSuchElementException)
    assert isinstance(results[2], NoSuchElementException)


@testing.effect
def test_ordered_an_error_at_path_i_fails_only_entry_i():
    """GraphQLResolver / ordered / an error at [...path, i] fails only entry i, keeping the response status and headers"""  # noqa: E501

    def respond(variables: Any) -> object:
        failed = variables["ids"].index("R_2")
        return {
            "data": {"nodes": [None if id == "R_2" else repo(id) for id in variables["ids"]]},
            "errors": [{"message": "Could not resolve", "path": ["nodes", failed]}],
        }

    api, _ = yield from make_client(respond, H.from_input({"retry-after": "60"}))

    ok, failed = yield from resolve_all(["R_1", "R_2"], by_id(api))

    assert ok == repo("R_1")
    assert isinstance(failed, GraphQLClientError)
    assert isinstance(failed.reason, ResponseError)
    assert [error["message"] for error in failed.reason.errors] == ["Could not resolve"]
    assert failed.reason.status == 200
    assert failed.reason.headers is not None
    assert failed.reason.headers.get("retry-after") == "60"
    assert failed.is_retryable


@testing.effect
def test_ordered_an_error_at_any_other_path_fails_the_batch():
    """GraphQLResolver / ordered / an error at any other path fails the batch"""
    api, _ = yield from make_client(
        lambda variables: {
            "data": {"nodes": [repo(id) for id in variables["ids"]]},
            "errors": [{"message": "Rate limited", "path": ["rateLimit"]}],
        }
    )

    results = yield from resolve_all(["R_1", "R_2"], by_id(api))

    for result in results:
        assert isinstance(result, GraphQLClientError)
        assert isinstance(result.reason, ResponseError)


class NodesOnly(GraphQLGroup):
    repo_nodes = RepoNodes


def _spanned_client(spans: list[str]) -> Effect[Any]:
    def execute(request: GraphQLRequest) -> Effect[Answer, Any]:
        def answer(span: Any) -> Answer:
            spans.append(span.name)
            return Answer(
                body={"data": {"nodes": [repo(id) for id in sent_variables(request)["ids"]]}}
            )

        return fx.current_span().map(answer).or_die()

    return client.make(NodesOnly).pipe(fx.provide(protocol_layer(execute=execute)))


def _ordered_nodes(api: Any) -> RequestResolver[Any, Any]:
    return resolver.ordered(
        api.repo_nodes, variables=lambda ids: {"ids": list(ids)}, path=("nodes",)
    )


@testing.effect
def test_ordered_a_traced_callers_batch_is_sent_under_the_with_span_span():
    """GraphQLResolver / ordered / a traced caller's batch is sent under the RequestResolver.withSpan span"""  # noqa: E501
    spans: list[str] = []
    api = yield from _spanned_client(spans)
    get = resolver.request(_ordered_nodes(api).with_span("resolver"))

    results = yield from fx.all(get("R_1"), get("R_2"), concurrency="unbounded").with_span("caller")

    assert list(results) == [repo("R_1"), repo("R_2")]
    assert spans == ["resolver"]


@testing.effect
def test_ordered_a_batch_whose_first_caller_was_interrupted():
    """GraphQLResolver / ordered / a batch whose first caller was interrupted is sent under the remaining caller's span"""  # noqa: E501
    spans: list[str] = []
    api = yield from _spanned_client(spans)
    get = resolver.request(_ordered_nodes(api).set_delay("100 millis"))

    # The first caller starts the batch, so the batch fiber inherits its span.
    first = yield from get("R_1").with_span("first").fork()
    yield from fx.yield_now()
    second = yield from get("R_2").with_span("second").fork()
    yield from fx.yield_now()
    yield from first.interrupt()
    yield from testing.adjust("100 millis")

    assert (yield from second.join()) == repo("R_2")
    assert spans == ["second"]


# --- ordered, when an error nulls the whole list ---------------------------------------


RepositoryOnly = TypedDict("RepositoryOnly", {"__typename": str, "nameWithOwner": str})


class NullableNodesResult(TypedDict):
    nodes: Sequence[RepositoryOnly] | None


NullableNodes = query(
    "NullableNodes",
    document="query NullableNodes($ids:[ID!]!){nodes(ids:$ids){__typename ...on Repository{nameWithOwner}}}",  # noqa: E501
    variables=S.Struct(Ids),
    result=S.Struct(NullableNodesResult),
)


class NullableGroup(GraphQLGroup):
    nullable_nodes = NullableNodes


@testing.effect
def test_ordered_when_an_error_nulls_the_whole_list_every_entry_fails():
    """GraphQLResolver / ordered, when an error nulls the whole list / every entry fails with the ResponseError instead of NoSuchElementError"""  # noqa: E501
    body = {
        "data": {"nodes": None},
        "errors": [{"message": "boom", "path": ["nodes", 1, "nameWithOwner"]}],
    }
    protocol = protocol_layer(execute=lambda _: effect.succeed(Answer(body=body, status=200)))
    api = yield from client.make(NullableGroup).pipe(fx.provide(protocol))
    get = resolver.request(
        resolver.ordered(
            api.nullable_nodes, variables=lambda ids: {"ids": list(ids)}, path=("nodes",)
        )
    )
    for failed in (yield from resolve_all(["R_1", "R_2"], get)):
        assert isinstance(failed, GraphQLClientError)
        assert isinstance(failed.reason, ResponseError)


# --- findById --------------------------------------------------------------------------


@testing.effect
def test_find_by_id_matches_out_of_order_results_on_a_nested_path_by_key():
    """GraphQLResolver / findById / matches out-of-order results on a nested path by key; a missing key is a miss"""  # noqa: E501
    api, _ = yield from make_client(
        lambda variables: search_result(
            [repo(name) for name in reversed(search_names(variables)) if name != "a/missing"]
        )
    )

    results = yield from resolve_all(
        ["Effect-TS/effect", "a/missing", "Effect-TS/website"], by_name(api)
    )

    assert results[0] == repo("Effect-TS/effect")
    assert isinstance(results[1], NoSuchElementException)
    assert results[2] == repo("Effect-TS/website")


@testing.effect
def test_find_by_id_has_next_page_true_on_the_lists_parent_fails_the_batch():
    """GraphQLResolver / findById / hasNextPage: true on the list's parent fails the batch"""
    api, _ = yield from make_client(
        lambda variables: search_result([repo(name) for name in search_names(variables)], True)
    )

    results = yield from resolve_all(["Effect-TS/effect", "Effect-TS/website"], by_name(api))

    for result in results:
        assert isinstance(result, GraphQLClientError)
        assert isinstance(result.reason, DecodeError)


# --- batchKey --------------------------------------------------------------------------


class AuthedNodes(GraphQLGroup[Auth]):
    repo_nodes = RepoNodes


@testing.effect
def test_batch_key_applies_batch_n_per_key_for_interleaved_lookups():
    """GraphQLResolver / batchKey / applies batchN per key for interleaved lookups and calls each group with its own services"""  # noqa: E501
    requests: list[GraphQLRequest] = []

    def execute(request: GraphQLRequest) -> Effect[Answer, Any]:
        def answer() -> Answer:
            requests.append(request)
            nodes = [repo(id) for id in sent_variables(request)["ids"]]
            return Answer(body={"data": {"nodes": nodes}}, status=200)

        return effect.sync(answer)

    api = yield from client.make(AuthedNodes).pipe(
        fx.provide(layer.merge(protocol_layer(execute=execute), AUTH_LIVE))
    )
    get = resolver.request(
        resolver.ordered(
            api.repo_nodes,
            variables=lambda ids: {"ids": list(ids)},
            path=("nodes",),
            batch_key=lambda context: context.get_unsafe(CurrentUser),
        ).batch_n(2)
    )

    def get_as(tenant: str, id: str) -> Effect[Any, Any]:
        return get(id).pipe(fx.provide_service(CurrentUser, tenant))

    results = yield from fx.all(
        get_as("a", "R_1"),
        get_as("b", "R_2"),
        get_as("a", "R_3"),
        get_as("b", "R_4"),
        concurrency="unbounded",
    )

    assert list(results) == [repo("R_1"), repo("R_2"), repo("R_3"), repo("R_4")]
    sent = sorted(
        f"{request.headers.get('authorization')}: {','.join(sorted(sent_variables(request)['ids']))}"  # noqa: E501
        for request in requests
    )
    assert sent == ["Bearer a: R_1,R_3", "Bearer b: R_2,R_4"]


# --- url -------------------------------------------------------------------------------


class GitHubHost(Reference[str]):
    @classmethod
    def default(cls) -> str:
        return "api.github.com"


def _nodes_handler(sent: list[str], name: Callable[[str, str], str] = lambda host, id: id) -> Any:
    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        ids = json.loads(body_text or "")["variables"]["ids"]
        sent.append(f"{url.netloc}: {','.join(sorted(ids))}")
        return graphql_response(
            request, {"data": {"nodes": [repo(name(url.netloc, id)) for id in ids]}}
        )

    return handler


def look_up_on_two_hosts(url: Any, limit: int | None = None) -> Effect[list[str]]:
    """Alternates four lookups between two hosts, returning what each
    request sent."""
    sent: list[str] = []
    protocol = layer_http(url=url).pipe(layer.provide(http_client_layer(_nodes_handler(sent))))

    def body():
        api = yield from client.make(NodesOnly).pipe(fx.provide(protocol))
        nodes = _ordered_nodes(api)
        get = resolver.request(nodes if limit is None else nodes.batch_n(limit))
        results = yield from fx.all(
            get("R_1"),
            get("R_2").pipe(fx.provide_service(GitHubHost, "api.acme.ghe.com")),
            get("R_3"),
            get("R_4").pipe(fx.provide_service(GitHubHost, "api.acme.ghe.com")),
            concurrency="unbounded",
        )
        assert list(results) == [repo("R_1"), repo("R_2"), repo("R_3"), repo("R_4")]
        return sorted(sent)

    return effect.gen(body)


def _host_url(options: Any) -> str:
    return f"http://{options.context.get_unsafe(GitHubHost)}/graphql"


def _async_host_url() -> Effect[str]:
    def body():
        yield from fx.yield_now()
        host = yield from GitHubHost()
        return f"http://{host}/graphql"

    return effect.gen(body)


URLS = [("function", _host_url), ("Effect resolved asynchronously", _async_host_url())]


@pytest.mark.parametrize(("form", "url"), URLS, ids=[form for form, _ in URLS])
@testing.effect
def test_url_lookups_whose_urls_differ_go_in_separate_batches(form: str, url: Any):
    """GraphQLResolver / url / ${form}: lookups whose URLs differ go in separate batches; lookups with the same URL share one"""  # noqa: E501
    sent = yield from look_up_on_two_hosts(url)
    assert sent == ["api.acme.ghe.com: R_2,R_4", "api.github.com: R_1,R_3"]


@testing.effect
def test_url_with_cache_separates_the_same_id_by_url():
    """GraphQLResolver / url / withCache separates the same ID by URL and reuses results on the same URL"""  # noqa: E501
    sent: list[str] = []
    protocol = layer_http(url=_host_url).pipe(
        layer.provide(http_client_layer(_nodes_handler(sent, lambda host, id: f"{host}/{id}")))
    )
    api = yield from client.make(NodesOnly).pipe(fx.provide(protocol))
    cached = yield from _ordered_nodes(api).with_cache(capacity=2)
    get = resolver.request(cached)

    first = yield from get("R_1")
    other_host = yield from get("R_1").pipe(fx.provide_service(GitHubHost, "api.acme.ghe.com"))
    again = yield from get("R_1")

    assert [first, other_host, again] == [
        repo("api.github.com/R_1"),
        repo("api.acme.ghe.com/R_1"),
        repo("api.github.com/R_1"),
    ]
    assert sent == ["api.github.com: R_1", "api.acme.ghe.com: R_1"]


@testing.effect
def test_url_applies_batch_n_per_asynchronous_url_and_evaluates_each_url_once():
    """GraphQLResolver / url / applies batchN per asynchronous URL with an implicit default host and evaluates each URL once"""  # noqa: E501
    evaluations = 0

    def counted():
        nonlocal evaluations
        evaluations += 1
        yield from fx.yield_now()
        host = yield from GitHubHost()
        return f"http://{host}/graphql"

    sent = yield from look_up_on_two_hosts(effect.gen(counted), 2)
    # Once per lookup, and not again when each batch is sent.
    assert evaluations == 4
    assert sent == ["api.acme.ghe.com: R_2,R_4", "api.github.com: R_1,R_3"]


class Nested(GraphQLMiddleware): ...


class NestedNodes(GraphQLGroup[Nested]):
    repo_nodes = RepoNodes


@testing.effect
def test_url_a_direct_call_made_while_a_batch_is_sent_resolves_its_own_url():
    """GraphQLResolver / url / a direct call made while a batch is sent resolves its own URL"""
    sent: list[str] = []
    protocol = layer_http(url=GitHubHost().map(lambda host: f"http://{host}/graphql")).pipe(
        layer.provide(http_client_layer(_nodes_handler(sent)))
    )

    # Both clients share one transport. The batched client's middleware
    # calls the same operation directly on another host.
    def clients():
        direct = yield from client.make(NodesOnly)
        other_host = Context.make(GitHubHost, "api.acme.ghe.com")

        def nested(options: Any) -> Effect[Any, Any]:
            call = direct.repo_nodes({"ids": ["R_9"]}, context=other_host).or_die()
            return call.flat_map(lambda _: options.next(options.request))

        from pyfect.graphql import Implementation

        implementation = Implementation(
            execute=nested, subscribe=lambda options: options.next(options.request)
        )
        return (
            yield from client.make(NestedNodes).pipe(fx.provide_service(Nested, implementation))
        )

    batched = yield from effect.gen(clients).pipe(fx.provide(protocol))
    get = resolver.request(_ordered_nodes(batched))

    assert (yield from get("R_1")) == repo("R_1")
    assert sent == ["api.acme.ghe.com: R_9", "api.github.com: R_1"]


# --- aliased ---------------------------------------------------------------------------


class PullRequestGroup(GraphQLGroup):
    pull_request = PullRequest


@testing.effect
def test_aliased_concurrent_lookups_make_one_post():
    """GraphQLResolver / aliased / concurrent lookups make one POST whose document repeats the operation under aliases"""  # noqa: E501
    sent: list[tuple[str, Any]] = []

    def handler(request: HttpClientRequest, body_text: str | None, url: Any) -> Any:
        body = None if body_text is None else json.loads(body_text)
        sent.append((request.method, body))
        variables = {} if body is None else body["variables"]
        return graphql_response(request, {"data": answer_slices(variables, pull_request)})

    # Queries go over GET, but a batch must not.
    protocol = layer_http(url="http://localhost/graphql", query_method="GET").pipe(
        layer.provide(http_client_layer(handler))
    )
    api = yield from client.make(PullRequestGroup).pipe(fx.provide(protocol))
    keys: list[PullRequestVariables] = [{"name": "effect", "number": n} for n in (1, 2, 3)]

    results = yield from fx.for_each(
        keys, resolver.request(resolver.aliased(api.pull_request)), concurrency="unbounded"
    )

    assert results == [{"repository": pull_request(key)} for key in keys]
    assert len(sent) == 1
    assert sent[0][0] == "POST"
    assert sent[0][1]["query"] == (
        "query PullRequest($_0_name:String!$_0_number:Int!$_1_name:String!$_1_number:Int!"
        "$_2_name:String!$_2_number:Int!){"
        '_0_repository:repository(owner:"Effect-TS",name:$_0_name){pullRequest(number:$_0_number){title}}'
        '_1_repository:repository(owner:"Effect-TS",name:$_1_name){pullRequest(number:$_1_number){title}}'
        '_2_repository:repository(owner:"Effect-TS",name:$_2_name){pullRequest(number:$_2_number){title}}'
        "}"
    )
    numbers = sorted(each["number"] for each in slices(sent[0][1]["variables"]).values())
    assert numbers == [1, 2, 3]


@testing.effect
def test_aliased_an_error_at_path_0_fails_only_its_slice():
    """GraphQLResolver / aliased / an error at path[0] fails only its slice, with the path un-prefixed"""  # noqa: E501

    def respond(variables: Any) -> object:
        prefix = next(p for p, each in slices(variables).items() if each["number"] == 2)
        return {
            "data": answer_slices(
                variables,
                lambda each: {"pullRequest": None} if each["number"] == 2 else pull_request(each),
            ),
            "errors": [
                {"message": "Could not resolve", "path": [f"{prefix}repository", "pullRequest"]}
            ],
        }

    api, _ = yield from make_client(respond)

    ok, failed = yield from resolve_all(LOOKUPS, get_pull_request(api))

    assert ok == {"repository": pull_request(LOOKUPS[0])}
    assert isinstance(failed, GraphQLClientError)
    assert isinstance(failed.reason, ResponseError)
    assert [error.get("path") for error in failed.reason.errors] == [["repository", "pullRequest"]]


TypenameResult = TypedDict("TypenameResult", {"__typename": str})


RootSpread = query(
    "RootSpread",
    document=DocumentTemplate(selections=(Selection(body=("...on Query{__typename}",)),)),
    result=S.Struct(TypenameResult),
)


class RootSpreadGroup(GraphQLGroup):
    root_spread = RootSpread


@testing.effect
def test_aliased_rejects_a_template_it_cant_slice_when_the_resolver_is_built():
    """GraphQLResolver / aliased / rejects a template it can't slice when the resolver is built, not on the first lookup"""  # noqa: E501
    protocol = protocol_layer(execute=lambda _: effect.die(AssertionError("not sent")))
    api = yield from client.make(RootSpreadGroup).pipe(fx.provide(protocol))
    with pytest.raises(ValueError, match="fragment spread or inline fragment at the root"):
        resolver.aliased(api.root_spread)


@testing.effect
def test_aliased_an_error_without_a_path_fails_the_batch():
    """GraphQLResolver / aliased / an error without a path fails the batch"""
    api, _ = yield from make_client(
        lambda variables: {
            "data": answer_slices(variables, pull_request),
            "errors": [{"message": "Rate limited"}],
        }
    )

    results = yield from resolve_all(LOOKUPS, get_pull_request(api))

    for result in results:
        assert isinstance(result, GraphQLClientError)
        assert isinstance(result.reason, ResponseError)


@testing.effect
def test_aliased_lookups_whose_encoded_variables_are_equal_share_one_slice():
    """GraphQLResolver / aliased / lookups whose encoded variables are equal share one slice"""
    issues = {"totalCount": 1}
    api, requests = yield from make_client(
        lambda variables: {"data": answer_slices(variables, lambda _: {"issues": issues})}
    )

    # Two separate lookups (Python has no undefined field, so Effect's
    # ``{ name, after: undefined }`` becomes the same keys in another order).
    results = yield from resolve_all(
        [{"name": "effect", "after": "c"}, {"after": "c", "name": "effect"}],
        resolver.request(resolver.aliased(api.repo_issues)),
    )

    assert results == [{"repository": {"issues": issues}}, {"repository": {"issues": issues}}]
    assert len(requests) == 1
    assert list(slices(sent_variables(requests[0]))) == ["_0_"]


@testing.effect
def test_aliased_over_a_make_test_client_the_handler_is_called_once_per_slice():
    """GraphQLResolver / aliased / over a makeTest client, the handler is called once per slice"""
    received: list[Any] = []

    def handler(variables: Any, _options: Any) -> Effect[Any]:
        received.append(variables)
        return effect.succeed({"repository": pull_request(variables)})

    api = client.make_test(PullRequestGroup, pull_request=handler)

    results = yield from fx.for_each(
        LOOKUPS, resolver.request(resolver.aliased(api.pull_request)), concurrency="unbounded"
    )

    assert results == [{"repository": pull_request(key)} for key in LOOKUPS]
    assert sorted(each["number"] for each in received) == [1, 2]
