"""Directed and undirected graphs with stable node and edge indexes, and
the algorithms Effect's ``Graph`` module has::

    from pyfect import graph

    def build(m: graph.MutableGraph[str, int]) -> None:
        a, b, c = m.add_node("A"), m.add_node("B"), m.add_node("C")
        m.add_edge(a, b, 1)
        m.add_edge(b, c, 2)

    g = graph.directed(build)
    list(g.bfs(start=[0]).values())   # ["A", "B", "C"]
    g.dijkstra(source=0, target=2, cost=lambda w: w).distance  # 3

A ``Graph`` is immutable and compared by structure; ``mutate`` (or
``begin_mutation`` / ``end_mutation``) changes a private ``MutableGraph``
copy and returns a new graph. Indexes are allocated in order and never
reused, and every iteration follows them, so results are deterministic.
A method for one kind of graph (``degree``, ``topo``) takes ``self`` typed
with that kind. Effect's dual (data-first / data-last) functions are
methods here, and its config objects keyword arguments.
"""

from pyfect._public import publish
from pyfect.graph._errors import GraphError
from pyfect.graph._graph import (
    Graph,
    MutableGraph,
    directed,
    from_snapshot,
    is_graph,
    make,
    undirected,
)
from pyfect.graph._records import (
    AllPairsResult,
    BipartiteMatch,
    CycleResult,
    Directed,
    Direction,
    Edge,
    IndexedEdge,
    IndexedNode,
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
from pyfect.graph._view import GraphView
from pyfect.graph._walker import EdgeWalker, NodeWalker, Visit, Walker

type DirectedGraph[N, E] = Graph[N, E, Directed]
type UndirectedGraph[N, E] = Graph[N, E, Undirected]
type MutableDirectedGraph[N, E] = MutableGraph[N, E, Directed]
type MutableUndirectedGraph[N, E] = MutableGraph[N, E, Undirected]

__all__ = [
    "AllPairsResult",
    "BipartiteMatch",
    "CycleResult",
    "Directed",
    "DirectedGraph",
    "Direction",
    "Edge",
    "EdgeWalker",
    "Graph",
    "GraphError",
    "GraphView",
    "IndexedEdge",
    "IndexedNode",
    "Kind",
    "MaximumFlowResult",
    "MermaidDiagramType",
    "MermaidDirection",
    "MermaidNodeShape",
    "MinimumCutResult",
    "MutableDirectedGraph",
    "MutableGraph",
    "MutableUndirectedGraph",
    "NodeWalker",
    "PathResult",
    "Snapshot",
    "TraversalDirection",
    "Undirected",
    "UndirectedGraph",
    "Visit",
    "Walker",
    "directed",
    "from_snapshot",
    "is_graph",
    "make",
    "undirected",
]

publish(globals())
