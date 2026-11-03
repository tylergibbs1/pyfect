"""Lookups, finders, incidence, degrees and neighbors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect.graph._errors import fail, missing_node
from pyfect.graph._records import Direction, Edge
from pyfect.graph._store import Store


def find_node(store: Store, predicate: Callable[[Any], bool]) -> int | None:
    return store.guarded(
        lambda: next((node for node, data in store.nodes.items() if predicate(data)), None)
    )


def find_nodes(store: Store, predicate: Callable[[Any], bool]) -> list[int]:
    return store.guarded(lambda: [node for node, data in store.nodes.items() if predicate(data)])


def find_edge(store: Store, predicate: Callable[[Any, int, int], bool]) -> int | None:
    return store.guarded(
        lambda: next(
            (i for i, e in store.edges.items() if predicate(e.data, e.source, e.target)), None
        )
    )


def find_edges(store: Store, predicate: Callable[[Any, int, int], bool]) -> list[int]:
    return store.guarded(
        lambda: [i for i, e in store.edges.items() if predicate(e.data, e.source, e.target)]
    )


def far_end(store: Store, node: int, edge: Edge[Any]) -> int:
    """Where following ``edge`` from ``node`` leads: an undirected edge is
    followed against its stored orientation too."""
    return edge.source if store.kind == "undirected" and edge.target == node else edge.target


def has_edge(store: Store, source: int, target: int) -> bool:
    edges = store.adjacency.get(source)
    return edges is not None and any(
        far_end(store, source, store.edges[index]) == target for index in edges
    )


def _require(store: Store, *nodes: int) -> None:
    for node in nodes:
        if node not in store.nodes:
            raise missing_node(node)


def _without_repeats(edges: list[int]) -> list[int]:
    """An undirected self-loop is listed twice in a row; keep it once."""
    return [index for i, index in enumerate(edges) if i == 0 or edges[i - 1] != index]


def incident_edges(store: Store, node: int) -> list[int]:
    _require(store, node)
    outgoing = store.adjacency[node]
    if store.kind == "undirected":
        return _without_repeats(outgoing)
    incoming = store.reverse[node]
    # Both lists are in index order: merge them, a self-loop once.
    out: list[int] = []
    i = j = 0
    while i < len(outgoing) and j < len(incoming):
        if outgoing[i] < incoming[j]:
            out.append(outgoing[i])
            i += 1
        elif incoming[j] < outgoing[i]:
            out.append(incoming[j])
            j += 1
        else:
            out.append(outgoing[i])
            i += 1
            j += 1
    return [*out, *outgoing[i:], *incoming[j:]]


def directed_edges(store: Store, node: int, direction: Direction) -> list[int]:
    if store.kind == "undirected":
        fail(f"Cannot get {direction} edges of undirected graph")
    _require(store, node)
    return list(store.reverse[node] if direction == "incoming" else store.adjacency[node])


def edges_between(store: Store, source: int, target: int) -> list[int]:
    _require(store, source, target)
    return [
        index
        for index in _without_repeats(store.adjacency[source])
        if far_end(store, source, store.edges[index]) == target
    ]


def degree(store: Store, node: int) -> int:
    if store.kind == "directed":
        fail("Cannot get degree of directed graph")
    _require(store, node)
    return len(store.adjacency[node])


def directed_degree(store: Store, node: int, direction: Direction) -> int:
    return len(directed_edges(store, node, direction))


def directed_neighbors(store: Store, node: int, direction: Direction) -> list[int]:
    """Distinct neighbors in the order of the first edge reaching each."""
    lists = store.reverse if direction == "incoming" else store.adjacency
    ends = (
        store.edges[index].source if direction == "incoming" else store.edges[index].target
        for index in lists.get(node, ())
    )
    return list(dict.fromkeys(ends))


def undirected_neighbors(store: Store, node: int) -> list[int]:
    ends = (
        edge.target if edge.source == node else edge.source
        for edge in (store.edges[index] for index in store.adjacency.get(node, ()))
    )
    return list(dict.fromkeys(ends))


def neighbors(store: Store, node: int) -> list[int]:
    if store.kind == "undirected":
        return undirected_neighbors(store, node)
    return directed_neighbors(store, node, "outgoing")


def kind_neighbors(store: Store, node: int, direction: Direction, what: str) -> list[int]:
    if store.kind == "undirected":
        fail(f"Cannot get {what} of undirected graph")
    return directed_neighbors(store, node, direction)
