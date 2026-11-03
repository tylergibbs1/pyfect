"""The storage behind a graph and its mutable handle.

Nodes and edges are dicts in insertion order (Effect's ``Map``s, so every
iteration order matches). ``adjacency[n]`` lists the edges leaving ``n``
and ``reverse[n]`` those entering it; an undirected edge is in both lists
of both endpoints, twice for a self-loop.

Indexes only grow, so both dicts are also in ascending key order.

A store is mutable until its handle is finalized; ``transforming`` is set
while a user callback runs on a mutable store, and every mutation checks
it, so a callback cannot change the graph it is reading. ``compact`` is the
cached ``Compact`` view, dropped by every mutation.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pyfect.graph._errors import fail
from pyfect.graph._records import Edge, Kind, Snapshot

if TYPE_CHECKING:
    from pyfect.graph._compact import Compact


class Store:
    __slots__ = (
        "acyclic",
        "adjacency",
        "compact",
        "edges",
        "kind",
        "mutable",
        "next_edge",
        "next_node",
        "nodes",
        "reverse",
        "transforming",
        "version",
    )

    kind: Kind
    mutable: bool
    transforming: bool
    nodes: dict[int, Any]
    edges: dict[int, Edge[Any]]
    adjacency: dict[int, list[int]]
    reverse: dict[int, list[int]]
    next_node: int
    next_edge: int
    acyclic: bool | None
    """``True`` / ``False`` once known; ``None`` after a change that may
    have made or broken a cycle."""
    compact: Compact | None
    version: int
    """Counts mutations, for the live ``nodes`` / ``edges`` iterators."""

    def __init__(self, kind: Kind, mutable: bool) -> None:
        self.kind = kind
        self.mutable = mutable
        self.transforming = False
        self.nodes = {}
        self.edges = {}
        self.adjacency = {}
        self.reverse = {}
        self.next_node = 0
        self.next_edge = 0
        self.acyclic = True
        self.compact = None
        self.version = 0

    def clone(self, mutable: bool) -> Store:
        out = Store(self.kind, mutable)
        out.nodes = dict(self.nodes)
        out.edges = dict(self.edges)
        out.adjacency = {n: list(es) for n, es in self.adjacency.items()}
        out.reverse = {n: list(es) for n, es in self.reverse.items()}
        out.next_node = self.next_node
        out.next_edge = self.next_edge
        out.acyclic = self.acyclic
        return out

    @contextmanager
    def transformation(self) -> Generator[None]:
        previous = self.transforming
        self.transforming = True
        try:
            yield
        finally:
            self.transforming = previous

    def guarded[A](self, evaluate: Callable[[], A]) -> A:
        """Run a user callback; on a mutable store it may not mutate it."""
        if not self.mutable:
            return evaluate()
        with self.transformation():
            return evaluate()

    def for_mutation(self) -> Store:
        """This store, checked writable, with its cached view dropped."""
        self.check_writable()
        self.compact = None
        self.version += 1
        return self

    def check_writable(self) -> None:
        if not self.mutable:
            fail("Graph is not mutable")
        if self.transforming:
            fail("Cannot mutate graph during a transformation")


def hydrate(snapshot: Snapshot[Any, Any, Kind]) -> Store:
    """The immutable store of a validated snapshot. Indexes are made
    ``int``s: validation accepts an integral float, as JavaScript does."""
    store = Store(snapshot.type, False)
    for node in snapshot.nodes:
        index = int(node.index)
        store.nodes[index] = node.data
        store.adjacency[index] = []
        store.reverse[index] = []
    for edge in snapshot.edges:
        index, source, target = int(edge.index), int(edge.source), int(edge.target)
        store.edges[index] = Edge(source, target, edge.data)
        store.adjacency[source].append(index)
        store.reverse[target].append(index)
        if snapshot.type == "undirected":
            store.adjacency[target].append(index)
            store.reverse[source].append(index)
    store.next_node = int(snapshot.nodes[-1].index) + 1 if snapshot.nodes else 0
    store.next_edge = int(snapshot.edges[-1].index) + 1 if snapshot.edges else 0
    store.acyclic = None
    return store
