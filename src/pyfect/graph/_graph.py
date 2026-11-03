"""``Graph`` (immutable, compared by structure) and ``MutableGraph`` (a
mutation handle, compared by identity), and the constructors."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal, Never, TypeIs

from pyfect._equal import equal_key, equals
from pyfect.graph import _combine, _mutate
from pyfect.graph._errors import fail
from pyfect.graph._records import Directed, Edge, Kind, Snapshot, TraversalDirection, Undirected
from pyfect.graph._snapshot import from_snapshot as _from_snapshot
from pyfect.graph._store import Store
from pyfect.graph._view import GraphView
from pyfect.option import Option


class Graph[N, E, K: Kind = Literal["directed"]](GraphView[N, E, K]):
    """An immutable graph of nodes ``N`` and edges ``E``. Change one with
    ``mutate`` (or ``begin_mutation`` / ``end_mutation``), which returns a
    new graph. Two graphs are ``==`` when they have the same kind and the
    same nodes and edges at the same indexes (payloads compared as Effect's
    ``Equal`` does; an undirected edge either way round)."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Graph):
            return NotImplemented
        a, b = self._store, other._store
        if a is b:
            return True
        if a.kind != b.kind or len(a.nodes) != len(b.nodes) or len(a.edges) != len(b.edges):
            return False
        for index, data in a.nodes.items():
            if index not in b.nodes or not equals(data, b.nodes[index]):
                return False
        for index, edge in a.edges.items():
            found = b.edges.get(index)
            if found is None or not _same_edge(a.kind, edge, found):
                return False
        return True

    def __hash__(self) -> int:
        store = self._store
        return hash(
            (
                store.kind,
                tuple((index, equal_key(data)) for index, data in store.nodes.items()),
                tuple(
                    (index, _ends_key(store.kind, edge), equal_key(edge.data))
                    for index, edge in store.edges.items()
                ),
            )
        )

    # --- mutation -------------------------------------------------------------------

    def begin_mutation[N2, E2, K2: Kind](self: Graph[N2, E2, K2]) -> MutableGraph[N2, E2, K2]:
        """A mutable copy; this graph never changes."""
        return MutableGraph(self._store.clone(True))

    def mutate[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2], f: Callable[[MutableGraph[N2, E2, K2]], object]
    ) -> Graph[N2, E2, K2]:
        """The graph ``f`` makes of a mutable copy of this one. The handle is
        finalized afterwards, also when ``f`` raises."""
        return _scoped(self.begin_mutation(), f)

    # --- combinations ---------------------------------------------------------------

    def compose[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2],
        that: Graph[N2, E2, K2],
        *,
        node_identity: Callable[[N2], object] | None = None,
        edge_identity: Callable[[E2], object] | None = None,
    ) -> Graph[N2, E2, K2]:
        """The union of both graphs, nodes and edges matched by identity
        (default: their data); ``that``'s payloads win."""
        return Graph(_combine.compose(self._store, that._store, node_identity, edge_identity))

    def intersection[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2],
        that: Graph[N2, E2, K2],
        *,
        node_identity: Callable[[N2], object] | None = None,
        edge_identity: Callable[[E2], object] | None = None,
    ) -> Graph[N2, E2, K2]:
        """The nodes (this graph's payloads) and edges (``that``'s) in both."""
        return Graph(_combine.intersection(self._store, that._store, node_identity, edge_identity))

    def difference[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2],
        that: Graph[N2, E2, K2],
        *,
        node_identity: Callable[[N2], object] | None = None,
        edge_identity: Callable[[E2], object] | None = None,
    ) -> Graph[N2, E2, K2]:
        """Every node of this graph, and its edges ``that`` lacks."""
        return Graph(_combine.difference(self._store, that._store, node_identity, edge_identity))

    def symmetric_difference[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2],
        that: Graph[N2, E2, K2],
        *,
        node_identity: Callable[[N2], object] | None = None,
        edge_identity: Callable[[E2], object] | None = None,
    ) -> Graph[N2, E2, K2]:
        """Every node of both, and the edges in exactly one."""
        return Graph(
            _combine.symmetric_difference(self._store, that._store, node_identity, edge_identity)
        )

    def complement[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2], create_edge: Callable[[N2, N2], E2]
    ) -> Graph[N2, E2, K2]:
        """The same nodes, with an edge (from ``create_edge(source, target)``)
        wherever this graph has none; no self-loops."""
        return Graph(_combine.complement(self._store, create_edge))

    def neighborhood(
        self,
        node: int,
        *,
        radius: float | None = None,
        direction: TraversalDirection = "outgoing",
    ) -> Graph[N, E, K]:
        """The subgraph of the nodes within ``radius`` (default 1) edges of
        ``node``, re-indexed in breadth-first order."""
        return Graph(_combine.neighborhood(self._store, node, radius, direction))

    def induced_subgraph(self, nodes: Iterable[int]) -> Graph[N, E, K]:
        """The given nodes and the edges among them, indexes kept."""
        return Graph(_combine.induced_subgraph(self._store, nodes))

    def sum[N2, E2, K2: Kind](
        self: Graph[N2, E2, K2], that: Graph[N2, E2, K2]
    ) -> Graph[N2, E2, K2]:
        """This graph and ``that`` side by side, ``that`` re-indexed after it."""
        return Graph(_combine.disjoint_sum(self._store, that._store))


def _same_edge(kind: Kind, a: Edge[Any], b: Edge[Any]) -> bool:
    ends = (a.source == b.source and a.target == b.target) or (
        kind == "undirected" and a.source == b.target and a.target == b.source
    )
    return ends and equals(a.data, b.data)


def _ends_key(kind: Kind, edge: Edge[Any]) -> object:
    if kind == "directed":
        return (edge.source, edge.target)
    return (min(edge.source, edge.target), max(edge.source, edge.target))


class MutableGraph[N, E, K: Kind = Literal["directed"]](GraphView[N, E, K]):
    """A mutation handle: a private copy changed in place until
    ``end_mutation`` turns it into a ``Graph``. After that every mutation
    raises ``GraphError``; so does one made from inside a callback the
    graph is running (a ``map_nodes`` function, a ``cost``, a walker's
    ``visit``)."""

    __slots__ = ()

    def add_node(self, data: N) -> int:
        """The new node's index: one past the highest ever allocated."""
        return _mutate.add_node(self._store, data)

    def add_edge(self, source: int, target: int, data: E) -> int:
        return _mutate.add_edge(self._store, source, target, data)

    def remove_node(self, node: int) -> None:
        """Removes the node and its edges; a missing node is ignored."""
        _mutate.remove_node(self._store, node)

    def remove_nodes(self, nodes: Iterable[int]) -> None:
        """``nodes`` is read in full first, so it may be a walker over this graph."""
        _mutate.remove_nodes(self._store, nodes)

    def remove_edge(self, edge: int) -> None:
        _mutate.remove_edge(self._store, edge)

    def remove_edges(self, edges: Iterable[int]) -> None:
        _mutate.remove_edges(self._store, edges)

    def update_node(self, node: int, f: Callable[[N], N]) -> None:
        """Replaces the data of ``node`` with ``f(data)``; a missing node is ignored."""
        _mutate.update_node(self._store, node, f)

    def update_edge(self, edge: int, f: Callable[[E], E]) -> None:
        _mutate.update_edge(self._store, edge, f)

    def map_nodes(self, f: Callable[[N], N]) -> None:
        _mutate.map_nodes(self._store, f)

    def map_edges(self, f: Callable[[E], E]) -> None:
        _mutate.map_edges(self._store, f)

    def filter_map_nodes(self, f: Callable[[N], Option[N]]) -> None:
        """Keeps ``Some`` results as the new data; removes the node (and
        its edges) for ``None``."""
        _mutate.filter_map_nodes(self._store, f)

    def filter_map_edges(self, f: Callable[[E], Option[E]]) -> None:
        _mutate.filter_map_edges(self._store, f)

    def filter_nodes(self, predicate: Callable[[N], bool]) -> None:
        _mutate.filter_nodes(self._store, predicate)

    def filter_edges(self, predicate: Callable[[E], bool]) -> None:
        _mutate.filter_edges(self._store, predicate)

    def reverse(self) -> None:
        """Turns every directed edge around; an undirected graph is unchanged."""
        _mutate.reverse(self._store)

    def end_mutation(self) -> Graph[N, E, K]:
        """The finished graph; this handle stays readable but no longer mutable."""
        _mutate.end_mutation(self._store)
        return Graph(self._store)


def _scoped[N, E, K: Kind](
    mutable: MutableGraph[N, E, K], f: Callable[[MutableGraph[N, E, K]], object]
) -> Graph[N, E, K]:
    try:
        f(mutable)
    except BaseException:
        if mutable.mutable:
            mutable.end_mutation()
        raise
    return mutable.end_mutation()


def make[K: Kind, N = Never, E = Never](
    kind: K, build: Callable[[MutableGraph[N, E, K]], object] | None = None
) -> Graph[N, E, K]:
    """An empty graph of ``kind``, or the graph ``build`` makes of one."""
    if kind not in ("directed", "undirected"):
        fail("Graph type must be directed or undirected")
    if build is None:
        return Graph(Store(kind, False))
    return _scoped(MutableGraph(Store(kind, True)), build)


def directed[N = Never, E = Never](
    build: Callable[[MutableGraph[N, E, Directed]], object] | None = None,
) -> Graph[N, E, Directed]:
    """``make("directed", build)``."""
    return make("directed", build)


def undirected[N = Never, E = Never](
    build: Callable[[MutableGraph[N, E, Undirected]], object] | None = None,
) -> Graph[N, E, Undirected]:
    """``make("undirected", build)``."""
    return make("undirected", build)


def from_snapshot[N, E, K: Kind](snapshot: Snapshot[N, E, K]) -> Graph[N, E, K]:
    """The graph of a snapshot, its indexes kept; raises ``GraphError``
    for a malformed one. New nodes and edges get indexes past the highest."""
    return Graph(_from_snapshot(snapshot))


def is_graph(value: object) -> TypeIs[Graph[Any, Any, Kind] | MutableGraph[Any, Any, Kind]]:
    return isinstance(value, GraphView)
