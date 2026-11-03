"""Lazy path enumerations: every simple path, and every shortest path.

Endpoints and the limit are checked when the enumeration is made; each
``iter`` starts over on the graph as it is then (checking the endpoints
again), and an iterator already running keeps the graph it started on.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterator
from typing import Any

from pyfect.graph._compact import Compact, view
from pyfect.graph._errors import bound, fail, missing_node
from pyfect.graph._records import PathResult
from pyfect.graph._shortest import Cost, edge_weights, non_negative, require_endpoints
from pyfect.graph._store import Store
from pyfect.graph._walker import Fresh

LIMIT = "Path enumeration limit must be a non-negative integer or Infinity"


def _ends(compact: Compact, source: int, target: int) -> tuple[int, int]:
    start = compact.index_of(source)
    if start is None:
        raise missing_node(source)
    goal = compact.index_of(target)
    if goal is None:
        raise missing_node(target)
    return start, goal


def _simple(
    rows: list[list[tuple[int, int]]], start: int, goal: int, most: float
) -> Iterator[tuple[list[int], list[int]]]:
    """Up to ``most`` paths from ``start`` to ``goal`` visiting no node
    twice, depth-first along ``rows`` (each node's ``(neighbor, edge)``
    pairs, in order), as compact nodes and edges."""
    nodes = [start]
    hops: list[int] = []
    visited = [False] * len(rows)
    visited[start] = True
    stack = [[start, 0]]
    emitted = 0

    def backtrack() -> None:
        node = stack.pop()[0]
        if stack:
            visited[node] = False
            nodes.pop()
            hops.pop()

    while stack and emitted < most:
        frame = stack[-1]
        node = frame[0]
        if node == goal:
            emitted += 1
            yield nodes, hops
            backtrack()
            continue
        if frame[1] >= len(rows[node]):
            backtrack()
            continue
        neighbor, edge = rows[node][frame[1]]
        frame[1] += 1
        if not visited[neighbor]:
            visited[neighbor] = True
            nodes.append(neighbor)
            hops.append(edge)
            stack.append([neighbor, 0])


def simple_paths(
    store: Store, source: int, target: int, limit: float | None
) -> Fresh[PathResult[Any]]:
    """Depth-first in edge order; a path's distance is its edge count."""
    require_endpoints(store, source, target)
    most = bound(limit, math.inf, LIMIT)

    def walk() -> Iterator[PathResult[Any]]:
        compact = view(store)
        start, goal = _ends(compact, source, target)
        if most == 0:
            return
        rows = [
            list(zip(neighbors, edges, strict=True))
            for neighbors, edges in zip(compact.outgoing, compact.edge_rows, strict=True)
        ]
        for nodes, hops in _simple(rows, start, goal, most):
            yield PathResult(
                tuple(compact.node_ids[n] for n in nodes),
                tuple(compact.edge_ids[e] for e in hops),
                len(hops),
                tuple(compact.edges[e].data for e in hops),
            )

    return Fresh(walk)


def _tied_predecessors(
    compact: Compact, start: int, weights: list[float]
) -> tuple[list[float], list[list[tuple[int, int]]]]:
    """Dijkstra from ``start``, keeping every predecessor ``(node, edge)``
    on a shortest path, in the order they were found."""
    size = len(compact)
    neighbors, edge_rows = compact.outgoing, compact.edge_rows
    distances = [math.inf] * size
    distances[start] = 0
    previous: list[list[tuple[int, int]]] = [[] for _ in range(size)]
    queue: list[tuple[float, int, int]] = [(0, 0, start)]
    sequence = 1
    while queue:
        current_distance, _, current = heapq.heappop(queue)
        if current_distance != distances[current]:
            continue
        for neighbor, edge in zip(neighbors[current], edge_rows[current], strict=True):
            following = current_distance + weights[edge]
            if weights[edge] != math.inf and not math.isfinite(following):
                fail("All shortest paths distance calculation exceeded the finite number range")
            if following < distances[neighbor]:
                distances[neighbor] = following
                previous[neighbor] = [(current, edge)]
                heapq.heappush(queue, (following, sequence, neighbor))
                sequence += 1
            elif following == distances[neighbor] and following != math.inf:
                previous[neighbor].append((current, edge))
    return distances, previous


def all_shortest_paths(
    store: Store, source: int, target: int, cost: Cost, limit: float | None
) -> Fresh[PathResult[Any]]:
    """Every simple path of least total cost, found by walking back from
    ``target`` through each node's tied predecessors in edge order. Costs
    are read when iteration starts."""
    require_endpoints(store, source, target)
    most = bound(limit, math.inf, LIMIT)

    def walk() -> Iterator[PathResult[Any]]:
        compact = view(store)
        start, goal = _ends(compact, source, target)
        weights = edge_weights(
            store,
            compact,
            cost,
            non_negative,
            "All shortest paths requires non-negative edge weights",
        )
        if most == 0:
            return
        distances, previous = _tied_predecessors(compact, start, weights)
        distance = distances[goal]
        if distance == math.inf:
            return
        if start == goal:
            yield PathResult((source,), (), 0, ())
            return
        for nodes, hops in _simple(previous, goal, start, most):
            yield PathResult(
                tuple(compact.node_ids[n] for n in reversed(nodes)),
                tuple(compact.edge_ids[e] for e in reversed(hops)),
                distance,
                tuple(compact.edges[e].data for e in reversed(hops)),
            )

    return Fresh(walk)
