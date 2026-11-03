"""What every graph reads: lookups, queries, rendering, algorithms and
walkers, shared by ``Graph`` and ``MutableGraph``.

A method that only makes sense for one kind of graph takes ``self`` typed
with that kind, so pyright rejects ``degree`` on a directed graph; called
anyway, it raises ``GraphError`` as Effect's does.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, Self, cast

from pyfect.graph import (
    _all_pairs,
    _components,
    _cycles,
    _enumerate,
    _flow,
    _forest,
    _matching,
    _query,
    _render,
    _shortest,
    _snapshot,
    _traverse,
)
from pyfect.graph._lowlink import analyze
from pyfect.graph._records import (
    AllPairsResult,
    BipartiteMatch,
    CycleResult,
    Directed,
    Direction,
    Edge,
    Kind,
    MaximumFlowResult,
    MermaidDiagramType,
    MermaidDirection,
    MermaidNodeShape,
    MinimumCutResult,
    PathResult,
    Snapshot,
    TraversalDirection,
    Undirected,
)
from pyfect.graph._store import Store
from pyfect.graph._walker import Walker
from pyfect.option import Option, Some

if TYPE_CHECKING:
    from pyfect.graph._graph import Graph


def _graph(store: Store) -> Graph[Any, Any, Any]:
    from pyfect.graph._graph import Graph

    return Graph(store)


class GraphView[N, E, K: Kind]:
    """The reads of a graph or a mutable graph."""

    __slots__ = ("_store",)

    _store: Store

    def __init__(self, store: Store) -> None:
        self._store = store

    @property
    def type(self) -> K:
        """``"directed"`` or ``"undirected"``."""
        return cast("K", self._store.kind)

    @property
    def mutable(self) -> bool:
        """``True`` for a mutable graph until it is finalized."""
        return self._store.mutable

    def __iter__(self) -> Iterator[tuple[int, N]]:
        """``(index, data)`` for each node, in index order (live, as ``nodes``)."""
        return _traverse.live(self._store, self._store.nodes)

    def __str__(self) -> str:
        store = self._store
        return f"Graph({store.kind}, {len(store.nodes)}, {len(store.edges)})"

    __repr__ = __str__

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def to_snapshot(self) -> Snapshot[N, E, K]:
        return cast("Snapshot[N, E, K]", _snapshot.to_snapshot(self._store))

    # --- nodes and edges ------------------------------------------------------------

    def get_node(self, index: int) -> Option[N]:
        nodes = self._store.nodes
        return Some(nodes[index]) if index in nodes else None

    def has_node(self, index: int) -> bool:
        return index in self._store.nodes

    def node_count(self) -> int:
        return len(self._store.nodes)

    def find_node(self, predicate: Callable[[N], bool]) -> int | None:
        """The first node, in index order, whose data matches."""
        return _query.find_node(self._store, predicate)

    def find_nodes(self, predicate: Callable[[N], bool]) -> list[int]:
        return _query.find_nodes(self._store, predicate)

    def find_edge(self, predicate: Callable[[E, int, int], bool]) -> int | None:
        """The first edge whose ``(data, source, target)`` matches (the
        stored orientation, also for an undirected edge)."""
        return _query.find_edge(self._store, predicate)

    def find_edges(self, predicate: Callable[[E, int, int], bool]) -> list[int]:
        return _query.find_edges(self._store, predicate)

    def get_edge(self, index: int) -> Edge[E] | None:
        return self._store.edges.get(index)

    def has_edge(self, source: int, target: int) -> bool:
        """Whether an edge leads from ``source`` to ``target`` (either way
        for an undirected graph)."""
        return _query.has_edge(self._store, source, target)

    def edge_count(self) -> int:
        return len(self._store.edges)

    def incident_edges(self, node: int) -> list[int]:
        """Every edge touching ``node``, in index order, a self-loop once."""
        return _query.incident_edges(self._store, node)

    def outgoing_edges(self: GraphView[Any, Any, Directed], node: int) -> list[int]:
        return _query.directed_edges(self._store, node, "outgoing")

    def incoming_edges(self: GraphView[Any, Any, Directed], node: int) -> list[int]:
        return _query.directed_edges(self._store, node, "incoming")

    def edges_between(self, source: int, target: int) -> list[int]:
        return _query.edges_between(self._store, source, target)

    def degree(self: GraphView[Any, Any, Undirected], node: int) -> int:
        """The edges at ``node``, a self-loop counting twice."""
        return _query.degree(self._store, node)

    def out_degree(self: GraphView[Any, Any, Directed], node: int) -> int:
        return _query.directed_degree(self._store, node, "outgoing")

    def in_degree(self: GraphView[Any, Any, Directed], node: int) -> int:
        return _query.directed_degree(self._store, node, "incoming")

    def neighbors(self, node: int) -> list[int]:
        """Distinct neighbors (successors for a directed graph), in the
        order of the first edge reaching each."""
        return _query.neighbors(self._store, node)

    def successors(self: GraphView[Any, Any, Directed], node: int) -> list[int]:
        return _query.kind_neighbors(self._store, node, "outgoing", "successors")

    def predecessors(self: GraphView[Any, Any, Directed], node: int) -> list[int]:
        return _query.kind_neighbors(self._store, node, "incoming", "predecessors")

    def neighbors_directed(
        self: GraphView[Any, Any, Directed], node: int, direction: Direction
    ) -> list[int]:
        return _query.kind_neighbors(self._store, node, direction, "directed neighbors")

    # --- text -----------------------------------------------------------------------

    def to_graph_viz(
        self,
        *,
        node_label: Callable[[N], str] | None = None,
        edge_label: Callable[[E], str] | None = None,
        graph_name: str = "G",
    ) -> str:
        """GraphViz DOT; labels default to JavaScript's ``String(data)``."""
        return _render.to_graph_viz(self._store, node_label, edge_label, graph_name)

    def to_mermaid(
        self,
        *,
        node_label: Callable[[N], str] | None = None,
        edge_label: Callable[[E], str] | None = None,
        diagram_type: MermaidDiagramType | None = None,
        direction: MermaidDirection = "TD",
        node_shape: Callable[[N], MermaidNodeShape] | None = None,
    ) -> str:
        """A Mermaid ``flowchart`` (directed) or ``graph`` (undirected)."""
        return _render.to_mermaid(
            self._store,
            node_label=node_label,
            edge_label=edge_label,
            diagram_type=diagram_type,
            direction=direction,
            node_shape=node_shape,
        )

    # --- structure ------------------------------------------------------------------

    def find_cycle(self) -> CycleResult | None:
        return _cycles.find_cycle(self._store)

    def is_acyclic(self) -> bool:
        return _cycles.is_acyclic(self._store)

    def is_bipartite(self: GraphView[Any, Any, Undirected]) -> bool:
        return _cycles.is_bipartite(self._store)

    def maximum_bipartite_matching(
        self: GraphView[Any, Any, Undirected],
    ) -> list[BipartiteMatch]:
        """A maximum matching; raises ``GraphError`` for a graph that is not bipartite."""
        return _matching.maximum_bipartite_matching(self._store)

    def unweighted_distances(
        self, source: int, *, direction: TraversalDirection = "outgoing"
    ) -> dict[int, int]:
        """Edges from ``source`` to each node it reaches, in node order."""
        return _components.unweighted_distances(self._store, source, direction)

    def has_path(
        self, source: int, target: int, *, direction: TraversalDirection = "outgoing"
    ) -> bool:
        return _components.has_path(self._store, source, target, direction)

    def connected_components(self: GraphView[Any, Any, Undirected]) -> list[list[int]]:
        return _components.connected_components(self._store)

    def bridges(self: GraphView[Any, Any, Undirected]) -> list[int]:
        return analyze(self._store).bridges

    def articulation_points(self: GraphView[Any, Any, Undirected]) -> list[int]:
        return analyze(self._store).articulation_points

    def biconnected_components(self: GraphView[Any, Any, Undirected]) -> list[list[int]]:
        """Each sorted, sorted; a self-loop is a component of its own."""
        return analyze(self._store).biconnected_components

    def maximum_flow[E2](
        self: GraphView[Any, E2, Directed],
        *,
        source: int,
        target: int,
        capacity: Callable[[E2], float],
    ) -> MaximumFlowResult:
        return _flow.maximum_flow(self._store, source, target, capacity)

    def minimum_cut[E2](
        self: GraphView[Any, E2, Directed],
        *,
        source: int,
        target: int,
        capacity: Callable[[E2], float],
    ) -> MinimumCutResult:
        return _flow.minimum_cut(self._store, source, target, capacity)

    def weakly_connected_components(self: GraphView[Any, Any, Directed]) -> list[list[int]]:
        return _components.weakly_connected_components(self._store)

    def strongly_connected_components(self: GraphView[Any, Any, Directed]) -> list[list[int]]:
        return _components.strongly_connected_components(self._store)

    def is_connected(self: GraphView[Any, Any, Undirected]) -> bool:
        return _components.is_connected(self._store)

    def is_weakly_connected(self: GraphView[Any, Any, Directed]) -> bool:
        return _components.is_weakly_connected(self._store)

    def is_strongly_connected(self: GraphView[Any, Any, Directed]) -> bool:
        return _components.is_strongly_connected(self._store)

    def is_tree(self: GraphView[Any, Any, Undirected]) -> bool:
        return _components.is_tree(self._store)

    def minimum_spanning_forest[N2, E2](
        self: GraphView[N2, E2, Undirected], cost: Callable[[E2], float]
    ) -> Graph[N2, E2, Undirected]:
        """Every node, and the edges of a minimum spanning tree of each component."""
        return _graph(_forest.minimum_spanning_forest(self._store, cost))

    def transitive_reduction[N2, E2](
        self: GraphView[N2, E2, Directed],
    ) -> Graph[N2, E2, Directed]:
        return _graph(_forest.transitive_reduction(self._store))

    # --- paths ----------------------------------------------------------------------

    def dijkstra(
        self, *, source: int, target: int, cost: Callable[[E], float]
    ) -> PathResult[E] | None:
        """A cheapest path, or ``None`` when ``target`` is unreachable."""
        return _shortest.dijkstra(self._store, source, target, cost)

    def astar(
        self,
        *,
        source: int,
        target: int,
        cost: Callable[[E], float],
        heuristic: Callable[[N, N], float],
    ) -> PathResult[E] | None:
        """``heuristic(node, target)`` estimates the cost left."""
        return _shortest.astar(self._store, source, target, cost, heuristic)

    def bellman_ford(
        self, *, source: int, target: int, cost: Callable[[E], float]
    ) -> PathResult[E] | None:
        """Allows negative weights; a negative cycle the path could use raises."""
        return _shortest.bellman_ford(self._store, source, target, cost)

    def floyd_warshall(self, cost: Callable[[E], float]) -> AllPairsResult[E]:
        return _all_pairs.floyd_warshall(self._store, cost)

    def simple_paths(
        self, *, source: int, target: int, limit: float | None = None
    ) -> Iterable[PathResult[E]]:
        """Every path visiting no node twice, lazily, depth-first in edge
        order; ``limit`` caps how many."""
        return _enumerate.simple_paths(self._store, source, target, limit)

    def all_shortest_paths(
        self,
        *,
        source: int,
        target: int,
        cost: Callable[[E], float],
        limit: float | None = None,
    ) -> Iterable[PathResult[E]]:
        return _enumerate.all_shortest_paths(self._store, source, target, cost, limit)

    # --- walkers --------------------------------------------------------------------

    def dfs(
        self,
        *,
        start: Sequence[int] | None = None,
        direction: TraversalDirection = "outgoing",
        radius: float | None = None,
    ) -> Walker[int, N]:
        """Depth-first from each of ``start`` in turn (none: nothing)."""
        return _traverse.dfs(self._store, start, direction, radius)

    def bfs(
        self,
        *,
        start: Sequence[int] | None = None,
        direction: TraversalDirection = "outgoing",
        radius: float | None = None,
    ) -> Walker[int, N]:
        return _traverse.bfs(self._store, start, direction, radius)

    def dfs_post_order(
        self,
        *,
        start: Sequence[int] | None = None,
        direction: TraversalDirection = "outgoing",
        radius: float | None = None,
    ) -> Walker[int, N]:
        return _traverse.dfs_post_order(self._store, start, direction, radius)

    def topo[N2](
        self: GraphView[N2, Any, Directed], *, initials: Sequence[int] | None = None
    ) -> Walker[int, N2]:
        """Topological order (Kahn), ``initials`` first, then the other
        sources in index order."""
        return _traverse.topo(self._store, initials)

    def nodes(self) -> Walker[int, N]:
        """The nodes, live: a running iteration sees nodes added later."""
        return _traverse.nodes(self._store)

    def edges(self) -> Walker[int, Edge[E]]:
        return _traverse.edges(self._store)

    def externals(self, *, direction: Direction = "outgoing") -> Walker[int, N]:
        """Nodes without outgoing edges (sinks), or incoming ones (sources)."""
        return _traverse.externals(self._store, direction)
