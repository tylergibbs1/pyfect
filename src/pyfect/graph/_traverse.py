"""Walkers: depth-first, breadth-first, post-order, topological order, and
the live ``nodes`` / ``edges`` / ``externals`` iterations.

A traversal walker checks its start nodes when it is made and again at
each ``iter`` (the graph may have changed); each iterator works on the
compact view of that moment. A ``radius`` bounds the walk to the nodes
within that many edges of a start, by shortest distance.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from typing import Any

from pyfect.graph._compact import Compact, Rows, view
from pyfect.graph._cycles import is_acyclic
from pyfect.graph._errors import bound, fail, missing_node
from pyfect.graph._records import Direction, TraversalDirection
from pyfect.graph._store import Store
from pyfect.graph._walker import Fresh, Walker

type Visitor = Callable[[int, Any], Any]
type MakeIterator = Callable[[Compact, Visitor], Iterator[Any]]

RADIUS = "Traversal radius must be a non-negative integer or Infinity"


def _compact_walker(store: Store, make: MakeIterator) -> Walker[int, Any]:
    def visit(f: Visitor) -> Fresh[Any]:
        def guarded(index: int, data: Any) -> Any:
            return store.guarded(partial(f, index, data))

        return Fresh(lambda: make(view(store), guarded))

    return Walker(visit)


def _starts(store: Store, start: Sequence[int] | None) -> list[int]:
    starts = list(start or ())
    for node in starts:
        if node not in store.nodes:
            raise missing_node(node)
    return starts


def _positions(compact: Compact, starts: list[int]) -> list[int]:
    out: list[int] = []
    for node in starts:
        position = compact.index_of(node)
        if position is None:
            raise missing_node(node)
        out.append(position)
    return out


def _rows_of(primary: Rows, secondary: Rows | None, node: int) -> list[int]:
    return primary[node] if secondary is None else [*primary[node], *secondary[node]]


def _within(
    size: int, starts: list[int], primary: Rows, secondary: Rows | None, radius: float
) -> list[bool]:
    """The nodes at most ``radius`` edges from a start."""
    reached = [False] * size
    queue: deque[tuple[int, int]] = deque()
    for position in starts:
        if not reached[position]:
            reached[position] = True
            queue.append((position, 0))
    while queue:
        current, depth = queue.popleft()
        if depth < radius:
            for neighbor in _rows_of(primary, secondary, current):
                if not reached[neighbor]:
                    reached[neighbor] = True
                    queue.append((neighbor, depth + 1))
    return reached


def dfs(
    store: Store, start: Sequence[int] | None, direction: TraversalDirection, radius: float | None
) -> Walker[int, Any]:
    limit = bound(radius, math.inf, RADIUS)
    starts = _starts(store, start)

    def make(compact: Compact, f: Visitor) -> Iterator[Any]:
        positions = _positions(compact, starts)
        primary, secondary = compact.adjacencies(direction)
        reached = (
            None
            if limit == math.inf
            else _within(len(compact), positions, primary, secondary, limit)
        )
        yielded = [False] * len(compact)
        stack = positions[::-1]

        def push(row: list[int]) -> None:
            stack.extend(
                n for n in reversed(row) if (reached is None or reached[n]) and not yielded[n]
            )

        def walk() -> Iterator[Any]:
            while stack:
                current = stack.pop()
                if yielded[current]:
                    continue
                if secondary is not None:
                    push(secondary[current])
                push(primary[current])
                yielded[current] = True
                yield f(compact.node_ids[current], compact.node_data[current])

        return walk()

    return _compact_walker(store, make)


def bfs(
    store: Store, start: Sequence[int] | None, direction: TraversalDirection, radius: float | None
) -> Walker[int, Any]:
    limit = bound(radius, math.inf, RADIUS)
    starts = _starts(store, start)

    def make(compact: Compact, f: Visitor) -> Iterator[Any]:
        positions = _positions(compact, starts)
        primary, secondary = compact.adjacencies(direction)
        discovered = [False] * len(compact)
        queue: deque[tuple[int, int]] = deque()
        for position in positions:
            if not discovered[position]:
                discovered[position] = True
                queue.append((position, 0))

        def walk() -> Iterator[Any]:
            while queue:
                current, depth = queue.popleft()
                if depth < limit:
                    for neighbor in _rows_of(primary, secondary, current):
                        if not discovered[neighbor]:
                            discovered[neighbor] = True
                            queue.append((neighbor, depth + 1))
                yield f(compact.node_ids[current], compact.node_data[current])

        return walk()

    return _compact_walker(store, make)


def dfs_post_order(
    store: Store, start: Sequence[int] | None, direction: TraversalDirection, radius: float | None
) -> Walker[int, Any]:
    limit = bound(radius, math.inf, RADIUS)
    starts = _starts(store, start)

    def make(compact: Compact, f: Visitor) -> Iterator[Any]:
        positions = _positions(compact, starts)
        primary, secondary = compact.adjacencies(direction)
        reached = (
            None
            if limit == math.inf
            else _within(len(compact), positions, primary, secondary, limit)
        )
        discovered = [False] * len(compact)
        # A frame: the node and how far it has read its primary and secondary rows.
        stack: list[list[int]] = []

        def push(node: int) -> None:
            if (reached is None or reached[node]) and not discovered[node]:
                discovered[node] = True
                stack.append([node, 0, 0])

        def walk() -> Iterator[Any]:
            for root in positions:
                push(root)
                while stack:
                    frame = stack[-1]
                    node = frame[0]
                    if frame[1] < len(primary[node]):
                        frame[1] += 1
                        push(primary[node][frame[1] - 1])
                        continue
                    if secondary is not None and frame[2] < len(secondary[node]):
                        frame[2] += 1
                        push(secondary[node][frame[2] - 1])
                        continue
                    stack.pop()
                    yield f(compact.node_ids[node], compact.node_data[node])

        return walk()

    return _compact_walker(store, make)


def topo(store: Store, initials: Sequence[int] | None) -> Walker[int, Any]:
    if store.kind == "undirected":
        fail("Cannot perform topological sort on undirected graph")
    if not is_acyclic(store):
        fail("Cannot perform topological sort on cyclic graph")
    firsts = _starts(store, initials)

    def make(compact: Compact, f: Visitor) -> Iterator[Any]:
        outgoing, incoming = compact.outgoing, compact.incoming
        in_degree = [len(row) for row in incoming]
        remaining = [True] * len(compact)
        chosen = [False] * len(compact)
        queue: list[int] = []
        for initial in firsts:
            node = compact.index_of(initial)
            if node is None:
                raise missing_node(initial)
            if in_degree[node] != 0:
                fail(f"Initial node {initial} has incoming edges")
            chosen[node] = True
            queue.append(node)
        queue += [n for n in range(len(compact)) if in_degree[n] == 0 and not chosen[n]]

        def walk() -> Iterator[Any]:
            left = len(compact)
            head = 0
            while head < len(queue):
                current = queue[head]
                head += 1
                if not remaining[current]:
                    continue
                remaining[current] = False
                left -= 1
                for neighbor in outgoing[current]:
                    if remaining[neighbor]:
                        in_degree[neighbor] -= 1
                        if in_degree[neighbor] == 0:
                            queue.append(neighbor)
                yield f(compact.node_ids[current], compact.node_data[current])
            if left > 0:
                fail("Cannot perform topological sort on cyclic graph")

        return walk()

    return _compact_walker(store, make)


def live(store: Store, table: dict[int, Any]) -> Iterator[tuple[int, Any]]:
    """``table``'s items as a JavaScript ``Map`` iterator gives them: items
    added while iterating are reached, removed ones are not. Keys are in
    ascending order (indexes only grow), so after a change the walk resumes
    past the last key it gave."""
    version = store.version
    keys = list(table)
    position = 0
    last = -1
    while True:
        if store.version != version:
            version = store.version
            keys = [key for key in table if key > last]
            position = 0
        if position >= len(keys):
            return
        last = keys[position]
        position += 1
        yield last, table[last]


def _live_walker(store: Store, items: Callable[[], Iterator[tuple[int, Any]]]) -> Walker[int, Any]:
    def visit(f: Visitor) -> Fresh[Any]:
        def start() -> Iterator[Any]:
            pairs = items()
            return (store.guarded(partial(f, index, data)) for index, data in pairs)

        return Fresh(start)

    return Walker(visit)


def nodes(store: Store) -> Walker[int, Any]:
    return _live_walker(store, lambda: live(store, store.nodes))


def edges(store: Store) -> Walker[int, Any]:
    return _live_walker(store, lambda: live(store, store.edges))


def externals(store: Store, direction: Direction) -> Walker[int, Any]:
    def items() -> Iterator[tuple[int, Any]]:
        lists = store.reverse if direction == "incoming" else store.adjacency
        return ((node, data) for node, data in live(store, store.nodes) if not lists.get(node))

    return _live_walker(store, items)
