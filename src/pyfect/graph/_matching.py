"""Maximum bipartite matching (Hopcroft-Karp), in Effect's order: the
left side is color 0 of the breadth-first two-coloring, each left node
tries its right neighbors in first-edge order, and a parallel edge after
the first is never used."""

from __future__ import annotations

from collections import deque

from pyfect.graph._cycles import two_coloring
from pyfect.graph._errors import fail
from pyfect.graph._records import BipartiteMatch
from pyfect.graph._store import Store

_UNMATCHED = -1
_FAR = 0x7FFFFFFF


def maximum_bipartite_matching(store: Store) -> list[BipartiteMatch]:  # noqa: PLR0915
    colored = two_coloring(store, "find bipartite matching")
    if colored is None:
        fail("Cannot find bipartite matching of non-bipartite graph")
    compact, colors = colored
    size = len(compact)
    sources, targets = compact.endpoints
    # arcs[left]: (right, edge) for each distinct right neighbor.
    arcs: list[list[tuple[int, int]]] = [[] for _ in range(size)]
    seen: list[set[int]] = [set() for _ in range(size)]
    for edge, (source, target) in enumerate(zip(sources, targets, strict=True)):
        left, right = (source, target) if colors[source] == 0 else (target, source)
        if right not in seen[left]:
            seen[left].add(right)
            arcs[left].append((right, edge))

    match_left = [_UNMATCHED] * size
    match_right = [_UNMATCHED] * size
    match_edge = [_UNMATCHED] * size
    distance = [0] * size
    shortest = _FAR
    lefts = [node for node in range(size) if colors[node] == 0]

    def has_layer() -> bool:
        nonlocal shortest
        shortest = _FAR
        queue: deque[int] = deque()
        for left in lefts:
            if match_left[left] == _UNMATCHED:
                distance[left] = 0
                queue.append(left)
            else:
                distance[left] = _FAR
        while queue:
            left = queue.popleft()
            if distance[left] >= shortest:
                continue
            for right, _ in arcs[left]:
                following = match_right[right]
                if following == _UNMATCHED:
                    shortest = distance[left] + 1
                elif distance[following] == _FAR:
                    distance[following] = distance[left] + 1
                    queue.append(following)
        return shortest != _FAR

    def augment(start: int) -> None:
        # A frame: [left, next arc, the right node and edge it was reached by].
        stack = [[start, 0, _UNMATCHED, _UNMATCHED]]
        while stack:
            frame = stack[-1]
            left = frame[0]
            if frame[1] >= len(arcs[left]):
                distance[left] = _FAR
                stack.pop()
                continue
            right, edge = arcs[left][frame[1]]
            frame[1] += 1
            following = match_right[right]
            if following == _UNMATCHED and distance[left] + 1 == shortest:
                match_left[left], match_right[right], match_edge[left] = right, left, edge
                for child, parent in zip(stack[:0:-1], stack[-2::-1], strict=True):
                    match_left[parent[0]] = child[2]
                    match_right[child[2]] = parent[0]
                    match_edge[parent[0]] = child[3]
                return
            if following != _UNMATCHED and distance[following] == distance[left] + 1:
                stack.append([following, 0, right, edge])

    while has_layer():
        for left in lefts:
            if match_left[left] == _UNMATCHED:
                augment(left)

    return [
        BipartiteMatch(
            compact.node_ids[left],
            compact.node_ids[match_left[left]],
            compact.edge_ids[match_edge[left]],
        )
        for left in range(size)
        if match_left[left] != _UNMATCHED
    ]
