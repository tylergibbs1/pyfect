"""A compact view of a store for the algorithms (Effect's internal CSR).

Nodes get positions ``0..n-1`` in insertion order and edges ``0..m-1``;
``rows`` / ``edge_rows`` give each position's neighbors and the edges
reaching them, in adjacency order. The view copies the nodes, edges and
adjacency lists when it is made and keeps no reference to the store, so a
projection built later (on first use) still describes that graph, and an
iterator holding a view never sees a later mutation.

``view(store)`` reuses the store's cached view, except while a callback
runs on a mutable store: then the graph may be part-way through a bulk
update, so the view is made fresh and not kept.
"""

from __future__ import annotations

from typing import Any

from pyfect.graph._records import Edge, TraversalDirection
from pyfect.graph._store import Store

type Rows = list[list[int]]


class Compact:
    __slots__ = (
        "_adjacency",
        "_edge_rows",
        "_edges",
        "_endpoints",
        "_incoming",
        "_outgoing",
        "_reverse",
        "edge_ids",
        "edges",
        "kind",
        "node_data",
        "node_ids",
        "position",
    )

    def __init__(self, store: Store) -> None:
        self.kind = store.kind
        self.node_ids: list[int] = list(store.nodes)
        self.node_data: list[Any] = list(store.nodes.values())
        self.edge_ids: list[int] = list(store.edges)
        """The edges' ids in insertion order: compact edge ``i`` is ``edge_ids[i]``."""
        self.edges: list[Edge[Any]] = list(store.edges.values())
        self._edges = dict(store.edges)
        self._adjacency = [tuple(store.adjacency[node]) for node in self.node_ids]
        self._reverse = [tuple(store.reverse[node]) for node in self.node_ids]
        dense = all(node == i for i, node in enumerate(self.node_ids))
        self.position: dict[int, int] | None = (
            None if dense else {node: i for i, node in enumerate(self.node_ids)}
        )
        self._outgoing: Rows | None = None
        self._incoming: Rows | None = None
        self._edge_rows: Rows | None = None
        self._endpoints: tuple[list[int], list[int]] | None = None

    def __len__(self) -> int:
        return len(self.node_ids)

    def index_of(self, node: object) -> int | None:
        """The position of a node id, ``None`` when it is not a node."""
        if self.position is None:
            if isinstance(node, bool) or not isinstance(node, (int, float)):
                return None
            whole = float(node).is_integer() and 0 <= node < len(self.node_ids)
            return int(node) if whole else None
        return self.position.get(node)  # pyright: ignore[reportArgumentType]

    def _at(self, node: int) -> int:
        return node if self.position is None else self.position[node]

    def _rows(self, incoming: bool) -> Rows:
        out: Rows = []
        for node, edge_ids in zip(
            self.node_ids, self._reverse if incoming else self._adjacency, strict=True
        ):
            row: list[int] = []
            for edge_id in edge_ids:
                edge = self._edges[edge_id]
                if self.kind == "undirected":
                    neighbor = edge.target if edge.source == node else edge.source
                else:
                    neighbor = edge.source if incoming else edge.target
                row.append(self._at(neighbor))
            out.append(row)
        return out

    @property
    def outgoing(self) -> Rows:
        if self._outgoing is None:
            self._outgoing = self._rows(False)
        return self._outgoing

    @property
    def incoming(self) -> Rows:
        if self._incoming is None:
            self._incoming = self._rows(True)
        return self._incoming

    @property
    def edge_rows(self) -> Rows:
        """Parallel to ``outgoing``: the compact edge behind each neighbor."""
        if self._edge_rows is None:
            ids = self.edge_ids
            dense = all(edge == i for i, edge in enumerate(ids))
            positions = None if dense else {edge: i for i, edge in enumerate(ids)}
            self._edge_rows = [
                [edge if positions is None else positions[edge] for edge in edge_ids]
                for edge_ids in self._adjacency
            ]
        return self._edge_rows

    @property
    def endpoints(self) -> tuple[list[int], list[int]]:
        """Per compact edge, the positions of its source and target."""
        if self._endpoints is None:
            edges = self.edges
            self._endpoints = (
                [self._at(edge.source) for edge in edges],
                [self._at(edge.target) for edge in edges],
            )
        return self._endpoints

    def adjacencies(self, direction: TraversalDirection) -> tuple[Rows, Rows | None]:
        """The rows to follow for a traversal direction; a directed graph
        followed without direction needs both."""
        if self.kind == "directed" and direction == "incoming":
            return self.incoming, None
        if self.kind == "directed" and direction == "undirected":
            return self.outgoing, self.incoming
        return self.outgoing, None


def view(store: Store) -> Compact:
    if store.transforming:
        return Compact(store)
    if store.compact is None:
        store.compact = Compact(store)
    return store.compact
