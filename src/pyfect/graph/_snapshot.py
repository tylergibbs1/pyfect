"""Snapshots: a graph as plain records, validated on the way in."""

from __future__ import annotations

from typing import Any

from pyfect.graph._errors import fail, is_safe_index
from pyfect.graph._records import IndexedEdge, IndexedNode, Kind, Snapshot
from pyfect.graph._store import Store, hydrate


def to_snapshot(store: Store) -> Snapshot[Any, Any, Kind]:
    return Snapshot(
        store.kind,
        tuple(IndexedNode(index, data) for index, data in store.nodes.items()),
        tuple(IndexedEdge(i, e.source, e.target, e.data) for i, e in store.edges.items()),
    )


def from_snapshot(snapshot: Snapshot[Any, Any, Kind]) -> Store:
    """The immutable store of ``snapshot``, which may come from anywhere
    (JSON, another process): every record is checked first."""
    if snapshot.type not in ("directed", "undirected"):
        fail("Snapshot type must be directed or undirected")
    previous = -1
    indexes: set[int] = set()
    for i, node in enumerate(snapshot.nodes):
        if node is None:  # pyright: ignore[reportUnnecessaryComparison]
            fail(f"Node at position {i} must be defined")
        if not is_safe_index(node.index):
            fail(f"Node index at position {i} must be a non-negative safe integer")
        if node.index <= previous:
            fail("Node indexes must be strictly increasing")
        previous = node.index
        indexes.add(node.index)
    previous = -1
    for i, edge in enumerate(snapshot.edges):
        if edge is None:  # pyright: ignore[reportUnnecessaryComparison]
            fail(f"Edge at position {i} must be defined")
        if not is_safe_index(edge.index):
            fail(f"Edge index at position {i} must be a non-negative safe integer")
        if edge.index <= previous:
            fail("Edge indexes must be strictly increasing")
        previous = edge.index
        for end, value in (("source", edge.source), ("target", edge.target)):
            if not is_safe_index(value):
                fail(f"Edge {end} at position {i} must be a non-negative safe integer")
            if value not in indexes:
                fail(f"Edge {end} {value} does not reference a node")
    return hydrate(snapshot)
