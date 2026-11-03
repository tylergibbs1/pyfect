"""Graphs made from graphs: set operations by node and edge identity,
complements, neighborhoods, induced subgraphs and disjoint sums.

Identities compare as Effect's ``Equal`` does (``pyfect._equal``). Nodes
with one identity become one node holding the last payload; an edge's
identity is its own identity with its endpoints' (in either orientation
for an undirected graph), so equal parallel edges are one set member.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Any

from pyfect._equal import equal_key
from pyfect.graph import _mutate
from pyfect.graph._compact import view
from pyfect.graph._errors import bound, fail, missing_node
from pyfect.graph._records import IndexedEdge, IndexedNode, Kind, Snapshot, TraversalDirection
from pyfect.graph._snapshot import from_snapshot
from pyfect.graph._store import Store
from pyfect.graph._traverse import RADIUS, bfs

type Identity = Callable[[Any], object]


def build(kind: Kind, fill: Callable[[Store], None]) -> Store:
    """A new immutable store, filled through the mutation functions."""
    store = Store(kind, True)
    fill(store)
    _mutate.end_mutation(store)
    return store


@dataclass(slots=True)
class _Edge:
    """An edge set member: its endpoints' identity keys (as first stored)
    and its payload (as last stored)."""

    source: Hashable
    target: Hashable
    data: Any


@dataclass(frozen=True, slots=True)
class _Nodes:
    by_identity: dict[Hashable, Any]
    """identity key -> payload, in first-seen order."""
    by_index: dict[int, Hashable]


def _nodes(store: Store, identity: Identity) -> _Nodes:
    by_identity: dict[Hashable, Any] = {}
    by_index: dict[int, Hashable] = {}
    for index, data in store.nodes.items():
        key = equal_key(identity(data))
        by_identity[key] = data
        by_index[index] = key
    return _Nodes(by_identity, by_index)


def _edge_key(kind: Kind, source: Hashable, target: Hashable, identity: Hashable) -> Hashable:
    if kind == "directed":
        return (identity, source, target)
    ends = {(source, 2)} if source == target else {(source, 1), (target, 1)}
    return (identity, frozenset(ends))


def _put(edges: dict[Hashable, _Edge], key: Hashable, edge: _Edge) -> None:
    if key in edges:
        edges[key].data = edge.data
    else:
        edges[key] = edge


def _edges(store: Store, nodes: _Nodes, identity: Identity) -> dict[Hashable, _Edge]:
    out: dict[Hashable, _Edge] = {}
    for edge in store.edges.values():
        member = _Edge(nodes.by_index[edge.source], nodes.by_index[edge.target], edge.data)
        _put(out, _member_key(store.kind, member, identity), member)
    return out


def _member_key(kind: Kind, member: _Edge, identity: Identity) -> Hashable:
    return _edge_key(kind, member.source, member.target, equal_key(identity(member.data)))


def _add_nodes(store: Store, nodes: dict[Hashable, Any]) -> dict[Hashable, int]:
    return {key: _mutate.add_node(store, data) for key, data in nodes.items()}


def _add_edge(store: Store, index_of: dict[Hashable, int], member: _Edge) -> None:
    source, target = index_of.get(member.source), index_of.get(member.target)
    if source is not None and target is not None:
        _mutate.add_edge(store, source, target, member.data)


def _same_kind(self: Store, that: Store) -> None:
    if self.kind != that.kind:
        fail(f"Cannot combine {self.kind} and {that.kind} graphs")


def _identities(node: Identity | None, edge: Identity | None) -> tuple[Identity, Identity]:
    return (node or _itself, edge or _itself)


def _itself(value: object) -> object:
    return value


def compose(self: Store, that: Store, node: Identity | None, edge: Identity | None) -> Store:
    """Both graphs' nodes and edges; ``that``'s payloads win."""
    _same_kind(self, that)
    node_identity, edge_identity = _identities(node, edge)
    mine, theirs = _nodes(self, node_identity), _nodes(that, node_identity)
    nodes = {**mine.by_identity, **theirs.by_identity}
    edges = _edges(self, mine, edge_identity)
    for key, member in _edges(that, theirs, edge_identity).items():
        _put(edges, key, member)

    def fill(store: Store) -> None:
        index_of = _add_nodes(store, nodes)
        for member in edges.values():
            _add_edge(store, index_of, member)

    return build(self.kind, fill)


def intersection(self: Store, that: Store, node: Identity | None, edge: Identity | None) -> Store:
    """The nodes in both (``self``'s payloads) and the edges in both
    (``that``'s payloads)."""
    _same_kind(self, that)
    node_identity, edge_identity = _identities(node, edge)
    mine, theirs = _nodes(self, node_identity), _nodes(that, node_identity)
    nodes = {key: data for key, data in mine.by_identity.items() if key in theirs.by_identity}
    my_edges = _edges(self, mine, edge_identity)
    their_edges: dict[Hashable, _Edge] = {}
    for e in that.edges.values():
        member = _Edge(theirs.by_index[e.source], theirs.by_index[e.target], e.data)
        if member.source in nodes and member.target in nodes:
            _put(their_edges, _member_key(that.kind, member, edge_identity), member)

    def fill(store: Store) -> None:
        index_of = _add_nodes(store, nodes)
        for key, member in their_edges.items():
            if key in my_edges:
                _add_edge(store, index_of, member)

    return build(self.kind, fill)


def difference(self: Store, that: Store, node: Identity | None, edge: Identity | None) -> Store:
    """``self``'s nodes, and each of its edges (parallel ones too) that
    ``that`` lacks."""
    _same_kind(self, that)
    node_identity, edge_identity = _identities(node, edge)
    mine, theirs = _nodes(self, node_identity), _nodes(that, node_identity)
    their_edges = _edges(that, theirs, edge_identity)

    def fill(store: Store) -> None:
        index_of = _add_nodes(store, mine.by_identity)
        for e in self.edges.values():
            member = _Edge(mine.by_index[e.source], mine.by_index[e.target], e.data)
            if _member_key(self.kind, member, edge_identity) not in their_edges:
                _add_edge(store, index_of, member)

    return build(self.kind, fill)


def symmetric_difference(
    self: Store, that: Store, node: Identity | None, edge: Identity | None
) -> Store:
    """Both graphs' nodes, and the edges in exactly one of them."""
    _same_kind(self, that)
    node_identity, edge_identity = _identities(node, edge)
    mine, theirs = _nodes(self, node_identity), _nodes(that, node_identity)
    nodes = {**mine.by_identity, **theirs.by_identity}
    my_edges, their_edges = _edges(self, mine, edge_identity), _edges(that, theirs, edge_identity)

    def fill(store: Store) -> None:
        index_of = _add_nodes(store, nodes)
        for key, member in my_edges.items():
            if key not in their_edges:
                _add_edge(store, index_of, member)
        for key, member in their_edges.items():
            if key not in my_edges:
                _add_edge(store, index_of, member)

    return build(self.kind, fill)


def complement(self: Store, create_edge: Callable[[Any, Any], object]) -> Store:
    """The same nodes, joined where ``self`` has no edge; never a self-loop."""
    compact = view(self)
    outgoing = compact.outgoing
    size = len(compact)

    def fill(store: Store) -> None:
        added = [_mutate.add_node(store, data) for data in compact.node_data]
        for i in range(size):
            joined = set(outgoing[i])
            for j in range(i + 1 if self.kind == "undirected" else 0, size):
                if i != j and j not in joined:
                    data = create_edge(compact.node_data[i], compact.node_data[j])
                    _mutate.add_edge(store, added[i], added[j], data)

    return build(self.kind, fill)


def neighborhood(
    self: Store, node: int, radius: float | None, direction: TraversalDirection
) -> Store:
    """The subgraph induced by the nodes within ``radius`` edges of
    ``node``, re-indexed in breadth-first order."""
    within = bound(radius, 1, RADIUS)
    reached = list(bfs(self, [node], direction, within).indices())
    chosen = set(reached)

    def fill(store: Store) -> None:
        index_of = {old: _mutate.add_node(store, self.nodes[old]) for old in reached}
        for e in self.edges.values():
            if e.source in chosen and e.target in chosen:
                _mutate.add_edge(store, index_of[e.source], index_of[e.target], e.data)

    return build(self.kind, fill)


def induced_subgraph(self: Store, nodes: Iterable[int]) -> Store:
    """The given nodes and the edges between them, indexes kept."""
    selected: set[int] = set()
    for node in nodes:
        if node not in self.nodes:
            raise missing_node(node)
        selected.add(node)
    return from_snapshot(
        Snapshot(
            self.kind,
            [IndexedNode(i, data) for i, data in self.nodes.items() if i in selected],
            [
                IndexedEdge(i, e.source, e.target, e.data)
                for i, e in self.edges.items()
                if e.source in selected and e.target in selected
            ],
        )
    )


def disjoint_sum(self: Store, that: Store) -> Store:
    """``self`` then ``that``, side by side, re-indexed."""
    _same_kind(self, that)

    def fill(store: Store) -> None:
        for part in (self, that):
            index_of = {old: _mutate.add_node(store, data) for old, data in part.nodes.items()}
            for e in part.edges.values():
                _mutate.add_edge(store, index_of[e.source], index_of[e.target], e.data)

    return build(self.kind, fill)
