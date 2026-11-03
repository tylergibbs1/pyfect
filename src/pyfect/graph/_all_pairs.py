"""All-pairs shortest paths (Floyd-Warshall).

Each improved distance keeps a witness: the edge it came from, or the two
witnesses it joined. A path is read back from its witness, and when it
would revisit a node (possible through a zero-cost cycle) the loop is cut
out, so every path is simple.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from pyfect.graph._compact import Compact, view
from pyfect.graph._errors import fail
from pyfect.graph._records import AllPairsResult
from pyfect.graph._shortest import Cost, edge_weights, not_nan_or_minus_infinity
from pyfect.graph._store import Store


@dataclass(frozen=True, slots=True)
class _Hop:
    target: int
    edge: int


@dataclass(frozen=True, slots=True)
class _Join:
    target: int
    left: _Hop | _Join
    right: _Hop | _Join


type _Witness = _Hop | _Join


type _Matrix = list[list[float]]
type _Witnesses = list[list[_Witness | None]]


def floyd_warshall(store: Store, cost: Cost) -> AllPairsResult[Any]:
    compact = view(store)
    weights = edge_weights(
        store,
        compact,
        cost,
        not_nan_or_minus_infinity,
        "Floyd-Warshall algorithm does not support NaN or -Infinity edge weights",
    )
    distance, witness = _shortest(compact, weights, undirected=store.kind == "undirected")
    for i, row in enumerate(distance):
        if row[i] < 0:
            fail(f"Negative cycle detected involving node {compact.node_ids[i]}")

    all_distances: dict[int, dict[int, float]] = {}
    all_paths: dict[int, dict[int, tuple[int, ...] | None]] = {}
    all_edges: dict[int, dict[int, tuple[int, ...]]] = {}
    all_costs: dict[int, dict[int, tuple[Any, ...]]] = {}
    for i, source in enumerate(compact.node_ids):
        distances = all_distances[source] = {}
        paths = all_paths[source] = {}
        edges = all_edges[source] = {}
        costs = all_costs[source] = {}
        for j, target in enumerate(compact.node_ids):
            distances[target] = distance[i][j]
            found = witness[i][j]
            if i == j:
                paths[target], edges[target], costs[target] = (source,), (), ()
            elif distance[i][j] == math.inf:
                paths[target], edges[target], costs[target] = None, (), ()
            else:
                assert found is not None  # every finite distance came from a witness
                path, hops = _read(i, found)
                paths[target] = tuple(compact.node_ids[n] for n in path)
                edges[target] = tuple(compact.edge_ids[e] for e in hops)
                costs[target] = tuple(compact.edges[e].data for e in hops)
    return AllPairsResult(all_distances, all_paths, all_edges, all_costs)


def _shortest(
    compact: Compact, weights: list[float], *, undirected: bool
) -> tuple[_Matrix, _Witnesses]:
    """The distance matrix and its witnesses, by compact position."""
    sources, targets = compact.endpoints
    size = len(compact)
    distance = [[math.inf] * size for _ in range(size)]
    witness: _Witnesses = [[None] * size for _ in range(size)]
    for i in range(size):
        distance[i][i] = 0
    for edge, weight in enumerate(weights):
        source, target = sources[edge], targets[edge]
        if weight < distance[source][target]:
            distance[source][target] = weight
            witness[source][target] = _Hop(target, edge)
        if undirected and weight < distance[target][source]:
            distance[target][source] = weight
            witness[target][source] = _Hop(source, edge)
    for k in range(size):
        for i in range(size):
            if distance[i][k] != math.inf:
                _through(k, distance[i], witness[i], distance[k], witness[k])
    return distance, witness


def _through(
    k: int,
    row: list[float],
    row_witness: list[_Witness | None],
    through: list[float],
    through_witness: list[_Witness | None],
) -> None:
    """Improve one row with the paths through ``k``."""
    to_k = row[k]
    left = row_witness[k]
    for j, from_k in enumerate(through):
        if from_k == math.inf:
            continue
        candidate = to_k + from_k
        if not math.isfinite(candidate):
            fail("Floyd-Warshall distance calculation exceeded the finite number range")
        if candidate < row[j]:
            row[j] = candidate
            right = through_witness[j]
            row_witness[j] = (
                right if left is None else left if right is None else _Join(j, left, right)
            )


def _read(start: int, found: _Witness) -> tuple[list[int], list[int]]:
    """The nodes and edges of a witness from ``start``, loops cut out."""
    nodes = [start]
    hops: list[int] = []
    position = {start: 0}
    pending: list[_Witness] = [found]
    while pending:
        step = pending.pop()
        at = position.get(step.target)
        if at is not None:
            for node in nodes[at + 1 :]:
                del position[node]
            del nodes[at + 1 :]
            del hops[at:]
        elif isinstance(step, _Hop):
            position[step.target] = len(nodes)
            nodes.append(step.target)
            hops.append(step.edge)
        else:
            pending += (step.right, step.left)
    return nodes, hops
