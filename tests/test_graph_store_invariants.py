"""After any sequence of mutations a graph's adjacency agrees with its
edges, read through the public queries.

A naive model (the list of live edges) gives every node's incident,
outgoing and incoming edges. Removals are where adjacency goes stale: an
edge index left behind in one endpoint's list shows up in a query or
breaks a later removal.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect import graph
from pyfect.graph import Kind, MutableGraph

type Op = (
    tuple[Literal["node"]]
    | tuple[Literal["edge"], int, int]
    | tuple[Literal["remove_node"], int]
    | tuple[Literal["remove_edge"], int]
    | tuple[Literal["reverse"]]
)

_index = st.integers(0, 9)
_ops: st.SearchStrategy[list[Op]] = st.lists(
    st.one_of(
        st.just(("node",)),
        st.tuples(st.just("edge"), _index, _index),
        st.tuples(st.just("edge"), _index, _index),
        st.tuples(st.just("remove_node"), _index),
        st.tuples(st.just("remove_edge"), _index),
        st.just(("reverse",)),
    ),
    max_size=40,
)


def _apply(m: MutableGraph[None, None, Any], op: Op) -> None:
    match op:
        case ("node",):
            m.add_node(None)
        case ("edge", source, target):
            if m.has_node(source) and m.has_node(target):
                m.add_edge(source, target, None)
        case ("remove_node", node):
            m.remove_node(node)
        case ("remove_edge", edge):
            m.remove_edge(edge)
        case ("reverse",):
            m.reverse()


def _check(m: MutableGraph[None, None, Any], kind: Kind) -> None:
    edges = {index: (e.source, e.target) for index, e in m.edges()}
    for node in m.nodes().indices():
        touching = [i for i, ends in edges.items() if node in ends]
        assert m.incident_edges(node) == touching
        if kind == "directed":
            d: Any = m
            assert d.outgoing_edges(node) == [i for i, (s, _) in edges.items() if s == node]
            assert d.incoming_edges(node) == [i for i, (_, t) in edges.items() if t == node]
        else:
            u: Any = m
            assert u.degree(node) == sum((s == node) + (t == node) for s, t in edges.values())


@pytest.mark.parametrize("kind", ["directed", "undirected"])
@settings(max_examples=300, deadline=None)
@given(ops=_ops)
def test_adjacency_matches_the_edges_after_any_mutations(kind: Kind, ops: list[Op]) -> None:
    empty: graph.Graph[None, None, Kind] = graph.make(kind)
    m: MutableGraph[None, None, Any] = empty.begin_mutation()
    for op in ops:
        _apply(m, op)
        _check(m, kind)
    # Removing everything leaves nothing behind.
    m.remove_nodes(list(m.nodes().indices()))
    assert m.node_count() == 0
    assert m.edge_count() == 0
