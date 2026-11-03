"""``from_snapshot`` is a boundary: its input may come from JSON, so it
is validated as Effect validates it, and what it returns is the typed
graph the rest of the module works on."""

from __future__ import annotations

import pytest

from pyfect import graph
from pyfect.graph import IndexedEdge, IndexedNode, Snapshot


def test_a_cyclic_snapshot_is_not_assumed_acyclic() -> None:
    g = graph.from_snapshot(
        Snapshot(
            "directed",
            (IndexedNode(0, "a"), IndexedNode(1, "b")),
            (IndexedEdge(0, 0, 1, None), IndexedEdge(1, 1, 0, None)),
        )
    )
    assert not g.is_acyclic()
    with pytest.raises(graph.GraphError, match="Cannot perform topological sort on cyclic graph"):
        list(g.topo())


def test_integral_float_indexes_become_ints() -> None:
    # JavaScript has one number type, so Effect accepts ``1.0`` as index 1;
    # Python must not hand floats back as node or edge indexes.
    snapshot = Snapshot(
        "directed",
        (IndexedNode(0.0, "a"), IndexedNode(1.0, "b")),  # pyright: ignore[reportArgumentType]
        (IndexedEdge(0.0, 0.0, 1.0, "ab"),),  # pyright: ignore[reportArgumentType]
    )

    def grow(m: graph.MutableGraph[str, str]) -> None:
        c = m.add_node("c")
        m.add_edge(1, c, "bc")

    g = graph.from_snapshot(snapshot).mutate(grow)
    out = g.to_snapshot()
    indexes = [n.index for n in out.nodes] + [
        x for e in out.edges for x in (e.index, e.source, e.target)
    ]
    assert indexes == [0, 1, 2, 0, 0, 1, 1, 1, 2]
    assert all(type(i) is int for i in indexes)
