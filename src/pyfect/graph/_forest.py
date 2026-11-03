"""Minimum spanning forests and transitive reductions: subgraphs that keep
every node and index."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from typing import Any

from pyfect.graph._cycles import is_acyclic
from pyfect.graph._errors import fail
from pyfect.graph._records import IndexedEdge, IndexedNode, Kind, Snapshot
from pyfect.graph._snapshot import from_snapshot
from pyfect.graph._store import Store


def _keeping(store: Store, kind: Kind, kept: set[int]) -> Store:
    return from_snapshot(
        Snapshot(
            kind,
            [IndexedNode(index, data) for index, data in store.nodes.items()],
            [
                IndexedEdge(index, edge.source, edge.target, edge.data)
                for index, edge in store.edges.items()
                if index in kept
            ],
        )
    )


def minimum_spanning_forest(store: Store, cost: Callable[[Any], float]) -> Store:
    """Kruskal: edges by weight, ties in edge order; an infinite weight is
    no edge."""
    if store.kind == "directed":
        fail("Cannot find minimum spanning forest of directed graph")
    position = {node: i for i, node in enumerate(store.nodes)}

    def weigh() -> list[tuple[float, int]]:
        weighted: list[tuple[float, int]] = []
        for index, edge in store.edges.items():
            weight = float(cost(edge.data))
            if math.isnan(weight) or weight == -math.inf:
                fail("Minimum spanning forest does not support NaN or -Infinity edge weights")
            if weight != math.inf:
                weighted.append((weight, index))
        return weighted

    weighted = sorted(store.guarded(weigh), key=lambda pair: pair[0])
    parents = list(range(len(position)))
    ranks = [0] * len(position)

    def find(node: int) -> int:
        root = node
        while parents[root] != root:
            root = parents[root]
        while parents[node] != node:
            parents[node], node = root, parents[node]
        return root

    selected: set[int] = set()
    for _, index in weighted:
        edge = store.edges[index]
        a, b = find(position[edge.source]), find(position[edge.target])
        if a == b:
            continue
        selected.add(index)
        if ranks[a] < ranks[b]:
            a, b = b, a
        parents[b] = a
        if ranks[a] == ranks[b]:
            ranks[a] += 1
    return _keeping(store, "undirected", selected)


def transitive_reduction(store: Store) -> Store:
    """Keeps the first edge from each source to each target that no other
    path reaches."""
    if store.kind == "undirected":
        fail("Cannot transitively reduce undirected graph")
    if not is_acyclic(store):
        fail("Cannot transitively reduce cyclic graph")
    first: dict[int, dict[int, int]] = {}
    for index, edge in store.edges.items():
        first.setdefault(edge.source, {}).setdefault(edge.target, index)
    retained: set[int] = set()
    for source, targets in first.items():
        for target, index in targets.items():
            if not _reaches_otherwise(store, source, target):
                retained.add(index)
    return _keeping(store, "directed", retained)


def _reaches_otherwise(store: Store, source: int, target: int) -> bool:
    """Whether ``target`` is reachable from ``source`` without a direct edge."""
    visited = {source}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for index in store.adjacency[current]:
            reached = store.edges[index].target
            if current == source and reached == target:
                continue
            if reached == target:
                return True
            if reached not in visited:
                visited.add(reached)
                queue.append(reached)
    return False
