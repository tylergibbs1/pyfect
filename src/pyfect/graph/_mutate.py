"""Mutations of a mutable store. Each checks the store is writable (not
finalized, not inside a callback) and drops its cached view first; user
callbacks run with the store marked as transforming."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pyfect.graph._errors import MAX_SAFE_INDEX, fail, missing_node
from pyfect.graph._records import Edge
from pyfect.graph._store import Store
from pyfect.option import Option, Some


def add_node(store: Store, data: object) -> int:
    store.for_mutation()
    index = store.next_node
    if index > MAX_SAFE_INDEX:
        fail("Graph has exhausted safe node indexes")
    store.nodes[index] = data
    store.adjacency[index] = []
    store.reverse[index] = []
    store.next_node = index + 1
    return index


def add_edge(store: Store, source: int, target: int, data: object) -> int:
    store.for_mutation()
    if source not in store.nodes:
        raise missing_node(source)
    if target not in store.nodes:
        raise missing_node(target)
    index = store.next_edge
    if index > MAX_SAFE_INDEX:
        fail("Graph has exhausted safe edge indexes")
    store.edges[index] = Edge(source, target, data)
    store.adjacency[source].append(index)
    store.reverse[target].append(index)
    if store.kind == "undirected":
        store.adjacency[target].append(index)
        store.reverse[source].append(index)
    store.next_edge = index + 1
    if store.acyclic is True:
        store.acyclic = None
    return index


def _removed(store: Store) -> None:
    if store.acyclic is False:
        store.acyclic = None


def _remove_node(store: Store, node: int) -> bool:
    if node not in store.nodes:
        return False
    incident = dict.fromkeys(store.adjacency[node])
    incident.update(dict.fromkeys(store.reverse[node]))
    for index in incident:
        edge = store.edges[index]
        if edge.source != node:
            store.adjacency[edge.source].remove(index)
            if store.kind == "undirected":
                store.reverse[edge.source].remove(index)
        if edge.target != node:
            store.reverse[edge.target].remove(index)
            if store.kind == "undirected":
                store.adjacency[edge.target].remove(index)
        del store.edges[index]
    del store.nodes[node]
    del store.adjacency[node]
    del store.reverse[node]
    return True


def _drop(lists: dict[int, list[int]], node: int, index: int) -> None:
    edges = lists.get(node)
    if edges is not None and index in edges:
        edges.remove(index)


def _remove_edge(store: Store, index: int) -> bool:
    edge = store.edges.get(index)
    if edge is None:
        return False
    _drop(store.adjacency, edge.source, index)
    _drop(store.reverse, edge.target, index)
    if store.kind == "undirected":
        _drop(store.adjacency, edge.target, index)
        _drop(store.reverse, edge.source, index)
    del store.edges[index]
    return True


def remove_node(store: Store, node: int) -> None:
    store.for_mutation()
    if _remove_node(store, node):
        _removed(store)


def remove_edge(store: Store, index: int) -> None:
    store.for_mutation()
    if _remove_edge(store, index):
        _removed(store)


def _collect(store: Store, indices: Iterable[int]) -> list[int]:
    """The indices, read before anything is removed (they may be a walker
    over this very graph); reading them may not mutate it."""
    store.check_writable()
    with store.transformation():
        collected = list(indices)
    store.for_mutation()
    return collected


def remove_nodes(store: Store, nodes: Iterable[int]) -> None:
    removed = [_remove_node(store, node) for node in _collect(store, nodes)]
    if any(removed):
        _removed(store)


def remove_edges(store: Store, edges: Iterable[int]) -> None:
    removed = [_remove_edge(store, edge) for edge in _collect(store, edges)]
    if any(removed):
        _removed(store)


def update_node(store: Store, node: int, f: Callable[[Any], object]) -> None:
    store.for_mutation()
    with store.transformation():
        if node in store.nodes:
            store.nodes[node] = f(store.nodes[node])


def update_edge(store: Store, index: int, f: Callable[[Any], object]) -> None:
    store.for_mutation()
    with store.transformation():
        edge = store.edges.get(index)
        if edge is not None:
            store.edges[index] = Edge(edge.source, edge.target, f(edge.data))


def map_nodes(store: Store, f: Callable[[Any], object]) -> None:
    store.for_mutation()
    with store.transformation():
        for node, data in store.nodes.items():
            store.nodes[node] = f(data)


def map_edges(store: Store, f: Callable[[Any], object]) -> None:
    store.for_mutation()
    with store.transformation():
        for index, edge in store.edges.items():
            store.edges[index] = Edge(edge.source, edge.target, f(edge.data))


def filter_map_nodes(store: Store, f: Callable[[Any], Option[object]]) -> None:
    store.for_mutation()
    remove: list[int] = []
    with store.transformation():
        for node, data in store.nodes.items():
            match f(data):
                case Some(value):
                    store.nodes[node] = value
                case None:
                    remove.append(node)
    remove_nodes(store, remove)


def filter_map_edges(store: Store, f: Callable[[Any], Option[object]]) -> None:
    store.for_mutation()
    remove: list[int] = []
    with store.transformation():
        for index, edge in store.edges.items():
            match f(edge.data):
                case Some(value):
                    store.edges[index] = Edge(edge.source, edge.target, value)
                case None:
                    remove.append(index)
    remove_edges(store, remove)


def filter_nodes(store: Store, predicate: Callable[[Any], bool]) -> None:
    store.for_mutation()
    with store.transformation():
        remove = [node for node, data in store.nodes.items() if not predicate(data)]
    remove_nodes(store, remove)


def filter_edges(store: Store, predicate: Callable[[Any], bool]) -> None:
    store.for_mutation()
    with store.transformation():
        remove = [index for index, edge in store.edges.items() if not predicate(edge.data)]
    remove_edges(store, remove)


def reverse(store: Store) -> None:
    store.for_mutation()
    if store.kind == "undirected":
        return
    for index, edge in store.edges.items():
        store.edges[index] = Edge(edge.target, edge.source, edge.data)
    store.adjacency, store.reverse = store.reverse, store.adjacency
    store.acyclic = None


def end_mutation(store: Store) -> None:
    store.check_writable()
    store.compact = None
    store.mutable = False
