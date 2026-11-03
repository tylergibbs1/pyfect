"""The values graphs take and return: edges, snapshots and algorithm results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

type Kind = Literal["directed", "undirected"]
type Directed = Literal["directed"]
type Undirected = Literal["undirected"]
type Direction = Literal["outgoing", "incoming"]
type TraversalDirection = Literal["outgoing", "incoming", "undirected"]
type MermaidNodeShape = Literal[
    "rectangle", "rounded", "circle", "diamond", "hexagon", "stadium", "subroutine", "cylindrical"
]
type MermaidDirection = Literal["TB", "TD", "BT", "RL", "LR"]
type MermaidDiagramType = Literal["flowchart", "graph"]

# Explicitly covariant: a frozen dataclass's synthesized ``__replace__``
# takes its fields as parameters, so PEP 695 inference makes it invariant.
N_co = TypeVar("N_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
K_co = TypeVar("K_co", bound=Kind, covariant=True)


@dataclass(frozen=True, slots=True)
class Edge(Generic[E_co]):
    """An edge as stored: an undirected edge keeps the orientation it was
    added with."""

    source: int
    target: int
    data: E_co


@dataclass(frozen=True, slots=True)
class IndexedNode(Generic[N_co]):
    index: int
    data: N_co


@dataclass(frozen=True, slots=True)
class IndexedEdge(Generic[E_co]):
    index: int
    source: int
    target: int
    data: E_co


@dataclass(frozen=True, slots=True)
class Snapshot(Generic[N_co, E_co, K_co]):
    """A graph as plain records, nodes and edges in index order
    (``Graph.to_snapshot``, ``graph.from_snapshot``)."""

    type: K_co
    nodes: Sequence[IndexedNode[N_co]] = field(default=())
    edges: Sequence[IndexedEdge[E_co]] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))


@dataclass(frozen=True, slots=True)
class CycleResult:
    """A cycle: ``path`` starts and ends at the same node; ``edges[i]``
    joins ``path[i]`` and ``path[i + 1]``."""

    path: tuple[int, ...]
    edges: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PathResult(Generic[E_co]):
    """A path from ``path[0]`` to ``path[-1]``: ``edges[i]`` (with data
    ``costs[i]``) joins ``path[i]`` and ``path[i + 1]``."""

    path: tuple[int, ...]
    edges: tuple[int, ...]
    distance: float
    costs: tuple[E_co, ...]


@dataclass(frozen=True, slots=True)
class AllPairsResult(Generic[E_co]):
    """``floyd_warshall``'s answer, keyed by source then target. An
    unreachable pair has distance ``math.inf``, path ``None`` and no
    edges."""

    distances: Mapping[int, Mapping[int, float]]
    paths: Mapping[int, Mapping[int, tuple[int, ...] | None]]
    edges: Mapping[int, Mapping[int, tuple[int, ...]]]
    costs: Mapping[int, Mapping[int, tuple[E_co, ...]]]


@dataclass(frozen=True, slots=True)
class BipartiteMatch:
    left: int
    right: int
    edge: int


@dataclass(frozen=True, slots=True)
class MaximumFlowResult:
    """The flow's value, the flow on every edge, and the saturated edges
    leaving the source side of a minimum cut."""

    value: float
    flows: Mapping[int, float]
    cut: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MinimumCutResult:
    value: float
    edges: tuple[int, ...]
    source: tuple[int, ...]
    target: tuple[int, ...]
