"""``resolver.ordered`` / ``find_by_id`` given ``items``, a typed function
picking the list out of the result, in place of a ``path`` (DOGFOOD atlas #6).
Not an Effect port: Effect takes a path only."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import pytest

from pyfect import testing
from pyfect.errors import NoSuchElementException
from pyfect.graphql import resolver
from pyfect.graphql.client_error import GraphQLClientError

from .test_graphql_resolver import (
    Nodes,
    SearchResult,
    make_client,
    repo,
    resolve_all,
    search_names,
    search_result,
)


def nodes(data: Nodes) -> Any:
    return data["nodes"]


def search_nodes(data: SearchResult) -> Any:
    return data["search"]["nodes"]


@testing.effect
def test_ordered_finds_the_list_items_picks_and_fails_only_the_entry_an_error_is_at():
    def respond(variables: Any) -> object:
        failed = variables["ids"].index("R_2")
        return {
            "data": {"nodes": [None if id == "R_2" else repo(id) for id in variables["ids"]]},
            "errors": [{"message": "Could not resolve", "path": ["nodes", failed]}],
        }

    api, requests = yield from make_client(respond)
    get = resolver.request(
        resolver.ordered(api.repo_nodes, variables=lambda ids: {"ids": list(ids)}, items=nodes)
    )
    results = yield from resolve_all(["R_1", "R_2"], get)
    assert len(requests) == 1
    assert results[0] == repo("R_1")
    assert isinstance(results[1], GraphQLClientError)


@testing.effect
def test_find_by_id_finds_the_list_items_picks_and_sees_a_truncated_page():
    def respond(variables: Any) -> object:
        return search_result([repo(name) for name in search_names(variables) if name != "b"])

    api, _ = yield from make_client(respond)
    get = resolver.request(
        resolver.find_by_id(
            api.search_repos,
            variables=lambda names: {"query": " ".join(f"repo:{name}" for name in names)},
            items=search_nodes,
            key=lambda found: found["nameWithOwner"],
        )
    )
    results = yield from resolve_all(["a", "b"], get)
    assert results[0] == repo("a")
    assert isinstance(results[1], NoSuchElementException)

    truncated, _ = yield from make_client(lambda _: search_result([], has_next_page=True))
    get = resolver.request(
        resolver.find_by_id(
            truncated.search_repos,
            variables=lambda names: {"query": " ".join(names)},
            items=search_nodes,
            key=lambda found: found["nameWithOwner"],
        )
    )
    (result,) = yield from resolve_all(["a"], get)
    assert "pageInfo.hasNextPage is true next to search.nodes" in str(result)


@testing.effect
def test_items_that_do_more_than_index_fields_are_rejected_when_the_resolver_is_made():
    api, _ = yield from make_client(lambda _: {})
    for items in (lambda data: data.get("nodes"), lambda data: data, lambda data: data[0]):
        with pytest.raises(ValueError, match="items must only index the result's fields"):
            resolver.ordered(api.repo_nodes, variables=lambda ids: {"ids": ids}, items=items)
    with pytest.raises(TypeError, match="one of items or path"):
        resolver.ordered(  # pyright: ignore[reportCallIssue]
            api.repo_nodes, variables=lambda ids: {"ids": ids}, items=nodes, path=("nodes",)
        )
