"""A compact view is the graph as it was when the view was made.

Every algorithm and iterator in ``pyfect.graph`` works on one view, and the
view builds its projections (rows, edge lists, endpoints) on first use. A
projection first read after a mutation must still describe the old graph,
or an iterator that reads one late would mix two versions of the graph.
"""

from __future__ import annotations

from pyfect.graph._compact import Compact
from pyfect.graph._mutate import add_edge, add_node, remove_edge, remove_node
from pyfect.graph._store import Store


def _store() -> Store:
    store = Store("directed", True)
    for name in "ABC":
        add_node(store, name)
    add_edge(store, 0, 1, "ab")
    add_edge(store, 1, 2, "bc")
    return store


def test_projections_read_after_a_mutation_describe_the_graph_the_view_was_made_of() -> None:
    store = _store()
    compact = Compact(store)
    remove_edge(store, 0)
    add_edge(store, 2, 0, "ca")
    remove_node(store, 1)
    assert compact.node_ids == [0, 1, 2]
    assert compact.outgoing == [[1], [2], []]
    assert compact.incoming == [[], [0], [1]]
    assert compact.edge_ids == [0, 1]
    assert [edge.data for edge in compact.edges] == ["ab", "bc"]
    assert compact.edge_rows == [[0], [1], []]
    assert compact.endpoints == ([0, 1], [1, 2])
