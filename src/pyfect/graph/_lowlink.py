"""Bridges, articulation points and biconnected components of an
undirected graph, from one iterative low-link depth-first search."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.graph._compact import view
from pyfect.graph._errors import fail
from pyfect.graph._store import Store


@dataclass(frozen=True, slots=True)
class LowLinks:
    bridges: list[int]
    articulation_points: list[int]
    biconnected_components: list[list[int]]


def analyze(store: Store) -> LowLinks:  # noqa: PLR0912, PLR0915
    if store.kind == "directed":
        fail("Cannot analyze undirected connectivity of directed graph")
    compact = view(store)
    neighbors, edge_rows = compact.outgoing, compact.edge_rows
    sources, targets = compact.endpoints
    size = len(compact)
    discovered = [-1] * size
    low = [0] * size
    parent_node = [-1] * size
    parent_edge = [-1] * size
    children = [0] * size
    bridge = [False] * len(compact.edge_ids)
    articulation = [False] * size
    edge_stack: list[int] = []
    components: list[list[int]] = []
    loops: dict[int, None] = {}
    time = 0

    def pop_component(stop: int) -> None:
        nodes: set[int] = set()
        while edge_stack:
            edge = edge_stack.pop()
            nodes.update((sources[edge], targets[edge]))
            if edge == stop:
                break
        if nodes:
            components.append(sorted(nodes))

    for start in range(size):
        if discovered[start] != -1:
            continue
        discovered[start] = low[start] = time
        time += 1
        stack = [[start, 0]]
        while stack:
            frame = stack[-1]
            node = frame[0]
            if frame[1] < len(neighbors[node]):
                neighbor, edge = neighbors[node][frame[1]], edge_rows[node][frame[1]]
                frame[1] += 1
                if neighbor == node:
                    loops[node] = None
                elif edge == parent_edge[node]:
                    pass
                elif discovered[neighbor] == -1:
                    children[node] += 1
                    parent_node[neighbor] = node
                    parent_edge[neighbor] = edge
                    discovered[neighbor] = low[neighbor] = time
                    time += 1
                    edge_stack.append(edge)
                    stack.append([neighbor, 0])
                elif discovered[neighbor] < discovered[node]:
                    low[node] = min(low[node], discovered[neighbor])
                    edge_stack.append(edge)
                continue
            stack.pop()
            parent = parent_node[node]
            if parent == -1:
                if children[node] > 1:
                    articulation[node] = True
                continue
            low[parent] = min(low[parent], low[node])
            if low[node] > discovered[parent]:
                bridge[parent_edge[node]] = True
            if low[node] >= discovered[parent]:
                if parent_node[parent] != -1:
                    articulation[parent] = True
                pop_component(parent_edge[node])

    components += [[node] for node in loops]
    components.sort()
    ids = compact.node_ids
    return LowLinks(
        [compact.edge_ids[e] for e, marked in enumerate(bridge) if marked],
        [ids[n] for n, marked in enumerate(articulation) if marked],
        [[ids[n] for n in component] for component in components],
    )
