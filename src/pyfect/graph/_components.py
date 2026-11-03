"""Reachability and connected components."""

from __future__ import annotations

from collections import deque

from pyfect.graph._compact import Rows, view
from pyfect.graph._errors import fail, missing_node
from pyfect.graph._records import TraversalDirection
from pyfect.graph._store import Store


def _follow(store: Store, direction: TraversalDirection) -> TraversalDirection:
    """An undirected graph's rows already hold both ends of every edge."""
    return "outgoing" if store.kind == "undirected" else direction


def unweighted_distances(
    store: Store, source: int, direction: TraversalDirection
) -> dict[int, int]:
    """The number of edges from ``source`` to each node it reaches, in node order."""
    if source not in store.nodes:
        raise missing_node(source)
    compact = view(store)
    primary, secondary = compact.adjacencies(_follow(store, direction))
    start = compact.index_of(source)
    assert start is not None
    distances = [-1] * len(compact)
    distances[start] = 0
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for rows in (primary, secondary):
            if rows is None:
                continue
            for neighbor in rows[current]:
                if distances[neighbor] == -1:
                    distances[neighbor] = distances[current] + 1
                    queue.append(neighbor)
    return {compact.node_ids[i]: d for i, d in enumerate(distances) if d != -1}


def has_path(store: Store, source: int, target: int, direction: TraversalDirection) -> bool:
    for node in (source, target):
        if node not in store.nodes:
            raise missing_node(node)
    if source == target:
        return True
    compact = view(store)
    primary, secondary = compact.adjacencies(_follow(store, direction))
    start, goal = compact.index_of(source), compact.index_of(target)
    assert start is not None
    visited = [False] * len(compact)
    visited[start] = True
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for rows in (primary, secondary):
            if rows is None:
                continue
            for neighbor in rows[current]:
                if neighbor == goal:
                    return True
                if not visited[neighbor]:
                    visited[neighbor] = True
                    queue.append(neighbor)
    return False


def _require(store: Store, kind: str, message: str) -> None:
    if store.kind != kind:
        fail(message)


def connected_components(store: Store) -> list[list[int]]:
    _require(store, "undirected", "Cannot find connected components of directed graph")
    compact = view(store)
    return _components(compact.node_ids, compact.outgoing, None, distinct=True)


def weakly_connected_components(store: Store) -> list[list[int]]:
    _require(store, "directed", "Cannot find weakly connected components of undirected graph")
    compact = view(store)
    primary, secondary = compact.adjacencies("undirected")
    return _components(compact.node_ids, primary, secondary, distinct=False)


def _components(
    node_ids: list[int], primary: Rows, secondary: Rows | None, *, distinct: bool
) -> list[list[int]]:
    """Depth-first from each unvisited node in order, each component in
    visiting order; ``distinct`` pushes a repeated neighbor once (Effect's
    ``connectedComponents`` does, ``weaklyConnectedComponents`` does not)."""
    visited = [False] * len(node_ids)
    components: list[list[int]] = []
    for start in range(len(node_ids)):
        if visited[start]:
            continue
        component: list[int] = []
        stack = [start]
        while stack:
            current = stack.pop()
            if visited[current]:
                continue
            visited[current] = True
            component.append(node_ids[current])
            unvisited = [n for n in primary[current] if not visited[n]]
            stack += dict.fromkeys(unvisited) if distinct else unvisited
            if secondary is not None:
                stack += [n for n in secondary[current] if not visited[n]]
        components.append(component)
    return components


def strongly_connected_components(store: Store) -> list[list[int]]:
    """Kosaraju: finish order on the edges, then components on the reversed edges."""
    _require(store, "directed", "Cannot find strongly connected components of undirected graph")
    compact = view(store)
    outgoing, incoming = compact.outgoing, compact.incoming
    visited = [False] * len(compact)
    finished: list[int] = []
    for start in range(len(compact)):
        if visited[start]:
            continue
        visited[start] = True
        stack = [[start, 0]]
        while stack:
            frame = stack[-1]
            node = frame[0]
            if frame[1] < len(outgoing[node]):
                neighbor = outgoing[node][frame[1]]
                frame[1] += 1
                if not visited[neighbor]:
                    visited[neighbor] = True
                    stack.append([neighbor, 0])
            else:
                finished.append(node)
                stack.pop()
    visited = [False] * len(compact)
    components: list[list[int]] = []
    for start in reversed(finished):
        if visited[start]:
            continue
        component: list[int] = []
        pending = [start]
        while pending:
            node = pending.pop()
            if visited[node]:
                continue
            visited[node] = True
            component.append(compact.node_ids[node])
            pending += [n for n in incoming[node] if not visited[n]]
        components.append(component)
    return components


def _reaches_all(size: int, primary: Rows, secondary: Rows | None = None) -> bool:
    if size == 0:
        return True
    visited = [False] * size
    visited[0] = True
    queue = deque([0])
    reached = 1
    while queue:
        current = queue.popleft()
        for rows in (primary, secondary):
            if rows is None:
                continue
            for neighbor in rows[current]:
                if not visited[neighbor]:
                    visited[neighbor] = True
                    reached += 1
                    queue.append(neighbor)
    return reached == size


def is_connected(store: Store) -> bool:
    _require(store, "undirected", "Cannot find connected components of directed graph")
    compact = view(store)
    return _reaches_all(len(compact), compact.outgoing)


def is_weakly_connected(store: Store) -> bool:
    _require(store, "directed", "Cannot find weakly connected components of undirected graph")
    compact = view(store)
    return _reaches_all(len(compact), *compact.adjacencies("undirected"))


def is_strongly_connected(store: Store) -> bool:
    _require(store, "directed", "Cannot find strongly connected components of undirected graph")
    compact = view(store)
    return _reaches_all(len(compact), compact.outgoing) and _reaches_all(
        len(compact), compact.incoming
    )


def is_tree(store: Store) -> bool:
    _require(store, "undirected", "Cannot determine tree status of directed graph")
    count = len(store.nodes)
    return count > 0 and len(store.edges) == count - 1 and is_connected(store)
