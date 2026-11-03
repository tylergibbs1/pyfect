"""Single-source shortest paths: Dijkstra, A* and Bellman-Ford.

Weights are floats (JavaScript numbers): ``math.inf`` is an impassable
edge, and a sum that leaves the finite range is an error. Ties go to the
node queued first, so equal-cost paths come out in edge order.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable
from typing import Any

from pyfect.graph._compact import Compact, view
from pyfect.graph._errors import fail, missing_node
from pyfect.graph._records import PathResult
from pyfect.graph._store import Store

type Cost = Callable[[Any], float]


def require_endpoints(store: Store, source: int, target: int) -> None:
    for node in (source, target):
        if node not in store.nodes:
            raise missing_node(node)


def edge_weights(
    store: Store, compact: Compact, cost: Cost, valid: Callable[[float], bool], message: str
) -> list[float]:
    """Every edge's weight, in compact edge order, checked with ``valid``."""

    def weigh() -> list[float]:
        weights: list[float] = []
        for edge in compact.edges:
            weight = float(cost(edge.data))
            if not valid(weight):
                fail(message)
            weights.append(weight)
        return weights

    return store.guarded(weigh)


def non_negative(weight: float) -> bool:
    return not math.isnan(weight) and weight >= 0


def not_nan_or_minus_infinity(weight: float) -> bool:
    return not math.isnan(weight) and weight != -math.inf


def same_node(node: int) -> PathResult[Any]:
    return PathResult((node,), (), 0, ())


def _path(
    compact: Compact,
    target: int,
    previous_node: list[int],
    previous_edge: list[int],
    distance: float,
) -> PathResult[Any]:
    path: list[int] = []
    edges: list[int] = []
    costs: list[Any] = []
    current = target
    while current != -1:
        path.append(compact.node_ids[current])
        edge = previous_edge[current]
        if edge != -1:
            edges.append(compact.edge_ids[edge])
            costs.append(compact.edges[edge].data)
        current = previous_node[current]
    return PathResult(
        tuple(reversed(path)), tuple(reversed(edges)), distance, tuple(reversed(costs))
    )


def dijkstra(store: Store, source_id: int, target_id: int, cost: Cost) -> PathResult[Any] | None:
    require_endpoints(store, source_id, target_id)
    compact = view(store)
    neighbors, edge_rows = compact.outgoing, compact.edge_rows
    weights = edge_weights(
        store,
        compact,
        cost,
        non_negative,
        "Dijkstra's algorithm requires non-negative edge weights",
    )
    if source_id == target_id:
        return same_node(source_id)
    source, target = compact.index_of(source_id), compact.index_of(target_id)
    assert source is not None and target is not None
    size = len(compact)
    distances = [math.inf] * size
    distances[source] = 0
    previous_node = [-1] * size
    previous_edge = [-1] * size
    visited = [False] * size
    queue: list[tuple[float, int, int]] = [(0, 0, source)]
    sequence = 1
    while queue:
        distance, _, current = heapq.heappop(queue)
        if visited[current]:
            continue
        visited[current] = True
        if current == target:
            break
        for neighbor, edge in zip(neighbors[current], edge_rows[current], strict=True):
            following = distance + weights[edge]
            if weights[edge] != math.inf and not math.isfinite(following):
                fail("Dijkstra distance calculation exceeded the finite number range")
            if following < distances[neighbor]:
                distances[neighbor] = following
                previous_node[neighbor] = current
                previous_edge[neighbor] = edge
                if not visited[neighbor]:
                    heapq.heappush(queue, (following, sequence, neighbor))
                    sequence += 1
    if distances[target] == math.inf:
        return None
    return _path(compact, target, previous_node, previous_edge, distances[target])


def astar(
    store: Store,
    source_id: int,
    target_id: int,
    cost: Cost,
    heuristic: Callable[[Any, Any], float],
) -> PathResult[Any] | None:
    require_endpoints(store, source_id, target_id)
    compact = view(store)
    neighbors, edge_rows = compact.outgoing, compact.edge_rows
    source, target = compact.index_of(source_id), compact.index_of(target_id)
    assert source is not None and target is not None
    goal = compact.node_data[target]
    weights = edge_weights(
        store, compact, cost, non_negative, "A* algorithm requires non-negative edge weights"
    )

    def estimate(data: Any) -> float:
        value = float(heuristic(data, goal))
        if not math.isfinite(value):
            fail("A* algorithm requires finite heuristic values")
        return value

    if source_id == target_id:
        store.guarded(lambda: estimate(compact.node_data[source]))
        return same_node(source_id)
    size = len(compact)
    scores = [math.inf] * size
    scores[source] = 0
    previous_node = [-1] * size
    previous_edge = [-1] * size
    visited = [False] * size

    def search() -> None:
        queue: list[tuple[float, int, int]] = [(estimate(compact.node_data[source]), 0, source)]
        sequence = 1
        while queue:
            _, _, current = heapq.heappop(queue)
            if visited[current]:
                continue
            visited[current] = True
            if current == target:
                return
            for neighbor, edge in zip(neighbors[current], edge_rows[current], strict=True):
                if visited[neighbor]:
                    continue
                tentative = scores[current] + weights[edge]
                if weights[edge] != math.inf and not math.isfinite(tentative):
                    fail("A* distance calculation exceeded the finite number range")
                if tentative < scores[neighbor]:
                    scores[neighbor] = tentative
                    previous_node[neighbor] = current
                    previous_edge[neighbor] = edge
                    priority = tentative + estimate(compact.node_data[neighbor])
                    if not math.isfinite(priority):
                        fail("A* priority calculation exceeded the finite number range")
                    heapq.heappush(queue, (priority, sequence, neighbor))
                    sequence += 1

    store.guarded(search)
    if scores[target] == math.inf:
        return None
    return _path(compact, target, previous_node, previous_edge, scores[target])


def _add(distance: float, weight: float) -> float:
    if math.inf in (distance, weight):
        return math.inf
    total = distance + weight
    if not math.isfinite(total):
        fail("Bellman-Ford distance calculation exceeded the finite number range")
    return total


def bellman_ford(  # noqa: PLR0912
    store: Store, source_id: int, target_id: int, cost: Cost
) -> PathResult[Any] | None:
    require_endpoints(store, source_id, target_id)
    compact = view(store)
    sources, targets = compact.endpoints
    weights = edge_weights(
        store,
        compact,
        cost,
        not_nan_or_minus_infinity,
        "Bellman-Ford algorithm does not support NaN or -Infinity edge weights",
    )
    source, target = compact.index_of(source_id), compact.index_of(target_id)
    assert source is not None and target is not None
    undirected = store.kind == "undirected"
    size = len(compact)
    distances = [math.inf] * size
    distances[source] = 0
    previous_node = [-1] * size
    previous_edge = [-1] * size

    def relax(edge: int, origin: int, to: int) -> bool:
        candidate = _add(distances[origin], weights[edge])
        if candidate < distances[to]:
            distances[to] = candidate
            previous_node[to] = origin
            previous_edge[to] = edge
            return True
        return False

    for _ in range(size - 1):
        updated = False
        for edge, (origin, to) in enumerate(zip(sources, targets, strict=True)):
            updated = relax(edge, origin, to) or updated
            if undirected and origin != to:
                updated = relax(edge, to, origin) or updated
        if not updated:
            break

    # Nodes a negative cycle can still improve, and everything they reach.
    affected = [False] * size
    queue: deque[int] = deque()

    def mark(node: int) -> None:
        if not affected[node]:
            affected[node] = True
            queue.append(node)

    for edge, (origin, to) in enumerate(zip(sources, targets, strict=True)):
        if _add(distances[origin], weights[edge]) < distances[to]:
            mark(to)
        if undirected and origin != to and _add(distances[to], weights[edge]) < distances[origin]:
            mark(origin)
    neighbors, edge_rows = compact.outgoing, compact.edge_rows
    while queue:
        node = queue.popleft()
        for neighbor, edge in zip(neighbors[node], edge_rows[node], strict=True):
            if weights[edge] != math.inf:
                mark(neighbor)
    negative = f"Negative cycle affects path to node {target_id}"
    if affected[target]:
        fail(negative)
    if distances[target] == math.inf:
        return None
    hops = 0
    node = target
    while node != -1:
        hops += 1
        if hops > size:
            fail(negative)
        node = previous_node[node]
    return _path(compact, target, previous_node, previous_edge, distances[target])
