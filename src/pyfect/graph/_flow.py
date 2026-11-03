"""Maximum flow and minimum cut (Edmonds-Karp on a residual graph)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyfect.graph._compact import Compact, view
from pyfect.graph._errors import fail, missing_node
from pyfect.graph._records import MaximumFlowResult, MinimumCutResult
from pyfect.graph._store import Store


@dataclass(slots=True)
class _Arc:
    origin: int
    to: int
    capacity: float
    flow: float = 0.0


@dataclass(frozen=True, slots=True)
class _Solution:
    flow: MaximumFlowResult
    source_side: list[bool]
    node_ids: list[int]


def _source_side(size: int, source: int, residual: _Residual) -> list[bool]:
    """The nodes the source reaches on residual capacity."""
    arcs, adjacency = residual.arcs, residual.adjacency
    side = [False] * size
    side[source] = True
    queue = deque([source])
    while queue:
        for index in adjacency[queue.popleft()]:
            arc = arcs[index]
            if arc.capacity - arc.flow > 0 and not side[arc.to]:
                side[arc.to] = True
                queue.append(arc.to)
    return side


@dataclass(slots=True)
class _Residual:
    """Each edge as a forward arc (``forward[edge]``, -1 for a self-loop)
    paired with a reverse arc at the next index."""

    arcs: list[_Arc]
    adjacency: list[list[int]]
    forward: list[int]


def _residual(store: Store, compact: Compact, capacity: Callable[[Any], float]) -> _Residual:
    sources, targets = compact.endpoints
    residual = _Residual([], [[] for _ in range(len(compact))], [-1] * len(sources))
    arcs, adjacency = residual.arcs, residual.adjacency

    def build() -> None:
        for edge, data in enumerate(e.data for e in compact.edges):
            amount = float(capacity(data))
            if not math.isfinite(amount) or amount < 0:
                fail(f"Edge {compact.edge_ids[edge]} capacity must be a finite non-negative number")
            origin, to = sources[edge], targets[edge]
            if origin == to:
                continue
            residual.forward[edge] = len(arcs)
            adjacency[origin].append(len(arcs))
            arcs.append(_Arc(origin, to, amount))
            adjacency[to].append(len(arcs))
            arcs.append(_Arc(to, origin, 0.0))

    store.guarded(build)
    return residual


def _solve(
    store: Store, source_id: int, target_id: int, capacity: Callable[[Any], float]
) -> _Solution:
    if store.kind == "undirected":
        fail("Cannot compute flow of undirected graph")
    compact = view(store)
    source = compact.index_of(source_id)
    if source is None:
        raise missing_node(source_id)
    target = compact.index_of(target_id)
    if target is None:
        raise missing_node(target_id)
    if source == target:
        fail("Flow source and target must be different nodes")
    residual = _residual(store, compact, capacity)
    arcs = residual.arcs
    value = 0.0
    while (parent := _augmenting(len(compact), source, target, residual)) is not None:
        path: list[_Arc] = []
        node = target
        while node != source:
            path.append(arcs[parent[node]])
            node = arcs[parent[node]].origin
        amount = min(arc.capacity - arc.flow for arc in path)
        if not math.isfinite(value + amount):
            fail("Maximum flow exceeds the finite number range")
        node = target
        while node != source:
            arcs[parent[node]].flow += amount
            arcs[parent[node] ^ 1].flow -= amount
            node = arcs[parent[node]].origin
        value += amount
    edge_ids = compact.edge_ids
    sources, targets = compact.endpoints
    flows = {
        edge_ids[edge]: 0.0 if arc == -1 else arcs[arc].flow
        for edge, arc in enumerate(residual.forward)
    }
    side = _source_side(len(compact), source, residual)
    cut = tuple(
        edge_ids[edge]
        for edge in range(len(edge_ids))
        if sources[edge] != targets[edge] and side[sources[edge]] and not side[targets[edge]]
    )
    return _Solution(MaximumFlowResult(value, flows, cut), side, compact.node_ids)


def _augmenting(size: int, source: int, target: int, residual: _Residual) -> list[int] | None:
    """Parent arcs of a shortest augmenting path, the search stopping as
    soon as it reaches ``target``."""
    arcs, adjacency = residual.arcs, residual.adjacency
    parent = [-1] * size
    visited = [False] * size
    visited[source] = True
    queue = deque([source])
    while queue and not visited[target]:
        node = queue.popleft()
        for index in adjacency[node]:
            arc = arcs[index]
            if arc.capacity - arc.flow > 0 and not visited[arc.to]:
                visited[arc.to] = True
                parent[arc.to] = index
                queue.append(arc.to)
                if arc.to == target:
                    break
    return parent if visited[target] else None


def maximum_flow(
    store: Store, source: int, target: int, capacity: Callable[[Any], float]
) -> MaximumFlowResult:
    return _solve(store, source, target, capacity).flow


def minimum_cut(
    store: Store, source: int, target: int, capacity: Callable[[Any], float]
) -> MinimumCutResult:
    solution = _solve(store, source, target, capacity)
    ids = solution.node_ids
    return MinimumCutResult(
        solution.flow.value,
        solution.flow.cut,
        tuple(ids[n] for n, inside in enumerate(solution.source_side) if inside),
        tuple(ids[n] for n, inside in enumerate(solution.source_side) if not inside),
    )
