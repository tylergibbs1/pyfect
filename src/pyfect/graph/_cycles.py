"""Cycles and two-colorings."""

from __future__ import annotations

from collections import deque

from pyfect.graph._compact import Compact, view
from pyfect.graph._errors import fail
from pyfect.graph._query import far_end
from pyfect.graph._records import CycleResult
from pyfect.graph._store import Store

_NEW, _OPEN, _DONE = 0, 1, 2


def find_cycle(store: Store) -> CycleResult | None:
    """The first cycle a depth-first search from each node in order finds;
    an undirected search does not go back along the edge it came by."""
    colors: dict[int, int] = {}
    parent_node: dict[int, int] = {}
    parent_edge: dict[int, int] = {}

    def cycle(ancestor: int, current: int, closing: int) -> CycleResult:
        path = [current]
        edges: list[int] = []
        cursor = current
        while cursor != ancestor:
            edges.append(parent_edge[cursor])
            cursor = parent_node[cursor]
            path.append(cursor)
        return CycleResult((*reversed(path), ancestor), (*reversed(edges), closing))

    for start in store.nodes:
        if colors.get(start, _NEW) != _NEW:
            continue
        colors[start] = _OPEN
        stack = [[start, 0]]
        while stack:
            frame = stack[-1]
            node = frame[0]
            adjacency = store.adjacency[node]
            if frame[1] >= len(adjacency):
                colors[node] = _DONE
                stack.pop()
                continue
            index = adjacency[frame[1]]
            frame[1] += 1
            if store.kind == "undirected" and parent_edge.get(node) == index:
                continue
            neighbor = far_end(store, node, store.edges[index])
            color = colors.get(neighbor, _NEW)
            if color == _OPEN:
                return cycle(neighbor, node, index)
            if color == _NEW:
                colors[neighbor] = _OPEN
                parent_node[neighbor] = node
                parent_edge[neighbor] = index
                stack.append([neighbor, 0])
    return None


def _undirected_acyclic(compact: Compact) -> bool:
    neighbors, edges = compact.outgoing, compact.edge_rows
    visited = [False] * len(compact)
    for start in range(len(compact)):
        if visited[start]:
            continue
        visited[start] = True
        stack = [(start, -1)]
        while stack:
            node, came_by = stack.pop()
            for neighbor, edge in zip(neighbors[node], edges[node], strict=True):
                if edge == came_by:
                    continue
                if visited[neighbor]:
                    return False
                visited[neighbor] = True
                stack.append((neighbor, edge))
    return True


def _directed_acyclic(compact: Compact) -> bool:
    outgoing = compact.outgoing
    colors = [_NEW] * len(compact)
    for start in range(len(compact)):
        if colors[start] != _NEW:
            continue
        colors[start] = _OPEN
        stack = [[start, 0]]
        while stack:
            frame = stack[-1]
            node = frame[0]
            if frame[1] < len(outgoing[node]):
                neighbor = outgoing[node][frame[1]]
                frame[1] += 1
                if colors[neighbor] == _OPEN:
                    return False
                if colors[neighbor] == _NEW:
                    colors[neighbor] = _OPEN
                    stack.append([neighbor, 0])
            else:
                colors[node] = _DONE
                stack.pop()
    return True


def is_acyclic(store: Store) -> bool:
    """Remembered on the store until a change could make or break a cycle."""
    if store.acyclic is None:
        compact = view(store)
        store.acyclic = (
            _undirected_acyclic(compact)
            if store.kind == "undirected"
            else _directed_acyclic(compact)
        )
    return store.acyclic


def two_coloring(store: Store, operation: str) -> tuple[Compact, list[int]] | None:
    """Each node's side (0 or 1) by breadth-first search from each
    uncolored node in order, or ``None`` when an edge joins one side."""
    if store.kind == "directed":
        fail(f"Cannot {operation} of directed graph")
    compact = view(store)
    outgoing = compact.outgoing
    colors = [-1] * len(compact)
    for start in range(len(compact)):
        if colors[start] != -1:
            continue
        colors[start] = 0
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in outgoing[node]:
                if colors[neighbor] == -1:
                    colors[neighbor] = 1 - colors[node]
                    queue.append(neighbor)
                elif colors[neighbor] == colors[node]:
                    return None
    return compact, colors


def is_bipartite(store: Store) -> bool:
    return two_coloring(store, "determine bipartite status") is not None
