"""Ports of Effect's ``test/Graph.test.ts``.

Each test's docstring is the Effect test title. Effect's functions are
methods here (``Graph.addNode(m, x)`` is ``m.add_node(x)``), so a
"data-first and data-last" title checks the method and ``pipe``.
``Option.some(path)`` results are plain values (``None`` for none),
``Equal.equals`` / ``Hash.hash`` are ``==`` / ``hash``, and JavaScript's
``undefined`` payloads are ``None``.
"""

from __future__ import annotations

import itertools
import math
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast

import pytest

from pyfect import graph
from pyfect.graph import (
    BipartiteMatch,
    CycleResult,
    Edge,
    Graph,
    GraphError,
    IndexedEdge,
    IndexedNode,
    Kind,
    MaximumFlowResult,
    MinimumCutResult,
    MutableGraph,
    PathResult,
    Snapshot,
    Walker,
)
from pyfect.option import Some

MAX_SAFE = 2**53 - 1

type EdgeSpec[E] = tuple[int, int, E]


def directed(
    nodes: Sequence[Any], edges: Sequence[EdgeSpec[Any]] = ()
) -> graph.DirectedGraph[Any, Any]:
    """A directed graph of ``nodes`` (indexes 0, 1, ...) and ``edges``."""

    def build(m: graph.MutableDirectedGraph[Any, Any]) -> None:
        for node in nodes:
            m.add_node(node)
        for source, target, data in edges:
            m.add_edge(source, target, data)

    return graph.directed(build)


def undirected(
    nodes: Sequence[Any], edges: Sequence[EdgeSpec[Any]] = ()
) -> graph.UndirectedGraph[Any, Any]:
    def build(m: graph.MutableUndirectedGraph[Any, Any]) -> None:
        for node in nodes:
            m.add_node(node)
        for source, target, data in edges:
            m.add_edge(source, target, data)

    return graph.undirected(build)


def assert_graph_error(thunk: Callable[[], object], message: str) -> None:
    with pytest.raises(GraphError) as raised:
        thunk()
    assert raised.value.message == message


def snapshot[K: Kind](
    kind: K, nodes: Iterable[tuple[int, Any]], edges: Iterable[tuple[int, int, int, Any]] = ()
) -> Snapshot[Any, Any, K]:
    return Snapshot(
        kind,
        [IndexedNode(i, data) for i, data in nodes],
        [IndexedEdge(i, s, t, data) for i, s, t, data in edges],
    )


def assert_snapshot(
    g: graph.GraphView[Any, Any, Any],
    kind: Kind,
    nodes: Iterable[tuple[int, object]],
    edges: Iterable[tuple[int, int, int, object]] = (),
) -> None:
    assert g.to_snapshot() == snapshot(kind, nodes, edges)


def path[E](
    nodes: Sequence[int], edges: Sequence[int], distance: float, costs: Sequence[E]
) -> PathResult[E]:
    return PathResult(tuple(nodes), tuple(edges), distance, tuple(costs))


def canonical(components: Iterable[Iterable[int]]) -> list[list[int]]:
    return sorted((sorted(c) for c in components), key=lambda c: c[0])


def indices(walker: Walker[int, Any]) -> list[int]:
    return list(walker.indices())


def identity[A](value: A) -> A:
    return value


# --- construction and protocols -----------------------------------------------------


def test_constructs_directed_and_undirected_graphs() -> None:
    """constructs directed and undirected graphs"""
    directed_graph = graph.make("directed")
    undirected_graph = graph.undirected()
    assert directed_graph.type == "directed"
    assert undirected_graph.type == "undirected"
    assert directed_graph.mutable is False
    assert directed_graph.node_count() == 0
    assert undirected_graph.edge_count() == 0


def test_rejects_invalid_runtime_graph_kinds() -> None:
    """rejects invalid runtime graph kinds"""
    assert_graph_error(
        lambda: graph.make(cast("Kind", "invalid")),
        "Graph type must be directed or undirected",
    )


def test_recognizes_immutable_and_mutable_graphs_only() -> None:
    """recognizes immutable and mutable graphs only"""
    assert graph.is_graph(graph.directed())
    assert graph.is_graph(graph.undirected().begin_mutation())
    values: list[object] = [{}, None, "graph", 1, []]
    for value in values:
        assert not graph.is_graph(value)


def test_supports_stringification_piping_and_node_iteration_in_graph_order() -> None:
    """supports stringification, piping, and node iteration in graph order"""
    g = directed(["A", "B"], [(0, 1, 1)])
    assert str(g) == "Graph(directed, 2, 1)"
    assert g.pipe(lambda x: x.node_count()) == 2
    assert list(g) == [(0, "A"), (1, "B")]
    iterator = iter(g)
    assert next(iterator) == (0, "A")
    assert next(iterator) == (1, "B")
    assert next(iterator, None) is None


# --- snapshots ----------------------------------------------------------------------


def test_round_trips_sparse_indexes_parallel_edges_self_loops_and_stored_orientation() -> None:
    """round-trips sparse indexes, parallel edges, self-loops, and stored orientation"""
    snap = snapshot(
        "undirected",
        [(2, "A"), (5, "B")],
        [(3, 5, 2, "first"), (7, 5, 2, "parallel"), (11, 5, 5, "loop")],
    )
    g = graph.from_snapshot(snap)
    assert g.to_snapshot() == snap
    assert g.neighbors(2) == [5]
    assert g.neighbors(5) == [2, 5]
    assert graph.from_snapshot(g.to_snapshot()) == g


def test_snapshots_mutable_state_without_exposing_stored_records() -> None:
    """snapshots mutable state without exposing stored records"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()
    mutable.update_node(0, lambda _: "updated")
    snap = mutable.to_snapshot()
    with pytest.raises(AttributeError):
        snap.nodes[0].index = 1  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(AttributeError):
        snap.edges[0].source = 1  # pyright: ignore[reportAttributeAccessIssue]
    assert_snapshot(mutable, "directed", [(0, "updated"), (1, "B")], [(0, 0, 1, 1)])


def test_continues_allocation_after_the_highest_active_snapshot_indexes() -> None:
    """continues allocation after the highest active snapshot indexes"""
    mutable = graph.from_snapshot(
        snapshot("directed", [(2, "A"), (5, "B")], [(4, 2, 5, 1)])
    ).begin_mutation()
    assert mutable.add_node("C") == 6
    assert mutable.add_edge(2, 5, 2) == 5


def test_rejects_malformed_snapshot_records_and_indexes() -> None:
    """rejects malformed snapshot records and indexes"""
    a = [IndexedNode(0, "A")]
    cases: list[tuple[Snapshot[Any, Any, Any], str]] = [
        (Snapshot("invalid", [], []), "Snapshot type must be directed or undirected"),  # pyright: ignore[reportArgumentType]
        (Snapshot("directed", [None], []), "Node at position 0 must be defined"),  # pyright: ignore[reportArgumentType]
        (
            snapshot("directed", [(-1, "A")]),
            "Node index at position 0 must be a non-negative safe integer",
        ),
        (
            snapshot("directed", [(MAX_SAFE + 1, "A")]),
            "Node index at position 0 must be a non-negative safe integer",
        ),
        (
            snapshot("directed", [(1, "A"), (1, "B")]),
            "Node indexes must be strictly increasing",
        ),
        (Snapshot("directed", a, [None]), "Edge at position 0 must be defined"),  # pyright: ignore[reportArgumentType]
        (
            Snapshot("directed", a, [IndexedEdge(0.5, 0, 0, 1)]),  # pyright: ignore[reportArgumentType]
            "Edge index at position 0 must be a non-negative safe integer",
        ),
        (
            snapshot("directed", [(0, "A")], [(1, 0, 0, 1), (1, 0, 0, 2)]),
            "Edge indexes must be strictly increasing",
        ),
        (
            snapshot("directed", [(0, "A")], [(0, -1, 0, 1)]),
            "Edge source at position 0 must be a non-negative safe integer",
        ),
        (
            Snapshot("directed", a, [IndexedEdge(0, 0, 0.5, 1)]),  # pyright: ignore[reportArgumentType]
            "Edge target at position 0 must be a non-negative safe integer",
        ),
        (
            snapshot("directed", [(1, "A")], [(0, 0, 1, 1)]),
            "Edge source 0 does not reference a node",
        ),
        (
            snapshot("directed", [(1, "A")], [(0, 1, 2, 1)]),
            "Edge target 2 does not reference a node",
        ),
    ]
    for snap, message in cases:
        assert_graph_error(lambda snap=snap: graph.from_snapshot(snap), message)


def test_rejects_allocation_after_safe_indexes_are_exhausted() -> None:
    """rejects allocation after safe indexes are exhausted"""
    nodes = graph.from_snapshot(snapshot("directed", [(MAX_SAFE, "A")])).begin_mutation()
    edges = graph.from_snapshot(
        snapshot("directed", [(0, "A")], [(MAX_SAFE, 0, 0, 1)])
    ).begin_mutation()
    assert_graph_error(lambda: nodes.add_node("B"), "Graph has exhausted safe node indexes")
    assert_graph_error(lambda: edges.add_edge(0, 0, 2), "Graph has exhausted safe edge indexes")


# --- equality and hashing -----------------------------------------------------------


def test_gives_equal_immutable_graphs_equal_hashes() -> None:
    """gives equal immutable graphs equal hashes"""
    left = undirected(["A", "B"], [(0, 1, "first"), (0, 1, "second"), (0, 0, "loop")])
    right = undirected(["A", "B"], [(1, 0, "first"), (1, 0, "second"), (0, 0, "loop")])
    assert left == right
    assert hash(left) == hash(right)


def test_distinguishes_undirected_self_loops_on_different_nodes() -> None:
    """distinguishes undirected self-loops on different nodes"""
    on_a = undirected(["A", "B"], [(0, 0, "loop")])
    on_b = undirected(["A", "B"], [(1, 1, "loop")])
    assert on_a != on_b
    assert hash(on_a) != hash(on_b)


def test_distinguishes_node_payload_edge_payload_missing_edge_kind_and_sparse_indexes() -> None:
    """distinguishes node payload, edge payload, missing edge, kind, and sparse indexes"""
    base = directed(["A", "B"], [(0, 1, "edge")])
    cases: list[Graph[Any, Any, Any]] = [
        directed(["changed", "B"], [(0, 1, "edge")]),
        directed(["A", "B"], [(0, 1, "changed")]),
        directed(["A", "B"], []),
        undirected(["A", "B"], [(0, 1, "edge")]),
        graph.from_snapshot(snapshot("directed", [(2, "A"), (5, "B")], [(3, 2, 5, "edge")])),
    ]
    for candidate in cases:
        assert base != candidate
        assert candidate != base


def test_keeps_directed_endpoints_and_parallel_edge_index_pairing_ordered() -> None:
    """keeps directed endpoints and parallel-edge index pairing ordered"""
    assert directed(["A", "B"], [(0, 1, "edge")]) != directed(["A", "B"], [(1, 0, "edge")])
    parallel = undirected(["A", "B"], [(0, 1, "first"), (0, 1, "second")])
    reordered = undirected(["A", "B"], [(1, 0, "second"), (1, 0, "first")])
    assert parallel != reordered


def test_ignores_removed_trailing_allocator_history_while_preserving_future_allocation() -> None:
    """ignores removed trailing allocator history while preserving future allocation"""
    left = directed(["A", "B"], [(0, 1, "edge")])

    def build(m: MutableGraph[str, str]) -> None:
        m.add_node("A")
        m.add_node("B")
        m.add_edge(0, 1, "edge")
        node = m.add_node("removed")
        edge = m.add_edge(0, 1, "removed")
        m.remove_node(node)
        m.remove_edge(edge)

    right = graph.directed(build)
    assert left == right
    assert hash(left) == hash(right)
    for g, expected in ((left, 2), (right, 3)):
        g.mutate(lambda m, expected=expected: _expect(m.add_node("next"), expected))
    for g, expected in ((left, 1), (right, 2)):
        g.mutate(lambda m, expected=expected: _expect(m.add_edge(0, 1, "next"), expected))


def _expect(actual: object, expected: object) -> None:
    assert actual == expected


def test_uses_reference_equality_for_mutable_graphs_and_structural_equality_after_finalization() -> (  # noqa: E501
    None
):
    """uses reference equality for mutable graphs and structural equality after finalization"""
    g = directed(["A", "B"], [(0, 1, "edge")])
    left, right = g.begin_mutation(), g.begin_mutation()
    hashed = hash(left)
    assert left != right
    left.add_node("C")
    assert hash(left) == hashed
    assert left.end_mutation() == directed(["A", "B", "C"], [(0, 1, "edge")])


def test_supports_undefined_node_and_edge_payloads_structurally() -> None:
    """supports undefined node and edge payloads structurally"""

    def make() -> Graph[None, None]:
        return directed([None, None], [(0, 1, None)])

    assert make() == make()
    assert hash(make()) == hash(make())


# --- mutation lifecycle -------------------------------------------------------------


def test_isolates_mutable_changes_from_the_source_and_finalizes_to_a_new_immutable_graph() -> None:
    """isolates mutable changes from the source and finalizes to a new immutable graph"""
    source = directed(["A", "B"], [(0, 1, 1)])
    mutable = source.begin_mutation()
    mutable.add_node("C")
    result = mutable.end_mutation()
    assert source.node_count() == 2
    assert result.node_count() == 3
    assert result is not source
    assert result.mutable is False


def test_supports_data_first_and_data_last_scoped_mutation() -> None:
    """supports data-first and data-last scoped mutation"""
    g: Graph[str, int] = graph.directed()
    first = g.mutate(lambda m: _ignore(m.add_node("A")))
    last = g.pipe(lambda x: x.mutate(lambda m: _ignore(m.add_node("A"))))
    assert_snapshot(first, "directed", [(0, "A")])
    assert_snapshot(last, "directed", [(0, "A")])


def _ignore(_: object) -> None:
    return None


def test_finalizes_retained_handles_when_callbacks_return_or_throw() -> None:
    """finalizes retained handles when callbacks return or throw"""
    kept: list[MutableGraph[str, int]] = []
    graph.directed(kept.append)
    assert_graph_error(lambda: kept[0].add_node("late"), "Graph is not mutable")

    cause = RuntimeError("boom")

    def throw(m: MutableGraph[str, int]) -> None:
        kept.append(m)
        raise cause

    empty: Graph[str, int] = graph.directed()
    with pytest.raises(RuntimeError) as raised:
        empty.mutate(throw)
    assert raised.value is cause
    assert_graph_error(lambda: kept[1].add_node("late"), "Graph is not mutable")


def test_rejects_normal_callback_return_after_manual_finalization() -> None:
    """rejects normal callback return after manual finalization"""
    empty: Graph[str, int] = graph.directed()
    assert_graph_error(
        lambda: graph.directed(lambda m: _ignore(m.end_mutation())), "Graph is not mutable"
    )
    assert_graph_error(
        lambda: empty.mutate(lambda m: _ignore(m.end_mutation())), "Graph is not mutable"
    )


def test_preserves_callback_errors_after_manual_finalization() -> None:
    """preserves callback errors after manual finalization"""
    cause = RuntimeError("callback failure")

    def end_then_throw(m: MutableGraph[str, int]) -> None:
        m.end_mutation()
        raise cause

    empty: Graph[str, int] = graph.directed()
    for run in (lambda: graph.directed(end_then_throw), lambda: empty.mutate(end_then_throw)):
        with pytest.raises(RuntimeError) as raised:
            run()
        assert raised.value is cause


def _mutations(m: MutableGraph[str, int]) -> list[Callable[[], object]]:
    return [
        lambda: m.add_node("C"),
        lambda: m.add_edge(1, 0, 2),
        lambda: m.update_node(0, lambda _: "updated"),
        lambda: m.update_edge(0, lambda _: 2),
        lambda: m.remove_node(0),
        lambda: m.remove_nodes([0]),
        lambda: m.remove_edge(0),
        lambda: m.remove_edges([0]),
        lambda: m.map_nodes(identity),
        lambda: m.map_edges(identity),
        lambda: m.filter_map_nodes(Some),
        lambda: m.filter_map_edges(Some),
        lambda: m.filter_nodes(lambda _: True),
        lambda: m.filter_edges(lambda _: True),
        m.reverse,
        m.end_mutation,
    ]


def test_rejects_every_mutation_entry_point_on_a_finalized_handle() -> None:
    """rejects every mutation entry point on a finalized handle"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()
    mutable.end_mutation()
    for mutation in _mutations(mutable):
        assert_graph_error(mutation, "Graph is not mutable")


def test_rejects_nested_mutation_or_finalization_from_transformation_callbacks() -> None:
    """rejects nested mutation or finalization from transformation callbacks"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def nested(mutation: Callable[[], object]) -> Callable[[str], str]:
        def update(node: str) -> str:
            mutation()
            return node

        return update

    for mutation in _mutations(mutable):
        assert_graph_error(
            lambda mutation=mutation: mutable.update_node(0, nested(mutation)),
            "Cannot mutate graph during a transformation",
        )
    assert_snapshot(mutable, "directed", [(0, "A"), (1, "B")], [(0, 0, 1, 1)])


def test_guards_every_transformation_callback_against_nested_mutation() -> None:
    """guards every transformation callback against nested mutation"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def then[A](value: A) -> A:
        mutable.add_node("C")
        return value

    transformations: list[Callable[[], object]] = [
        lambda: mutable.update_node(0, then),
        lambda: mutable.update_edge(0, then),
        lambda: mutable.map_nodes(then),
        lambda: mutable.map_edges(then),
        lambda: mutable.filter_map_nodes(lambda n: Some(then(n))),
        lambda: mutable.filter_map_edges(lambda e: Some(then(e))),
        lambda: mutable.filter_nodes(lambda _: then(True)),
        lambda: mutable.filter_edges(lambda _: then(True)),
    ]
    for transformation in transformations:
        assert_graph_error(transformation, "Cannot mutate graph during a transformation")


def test_guards_read_callbacks_against_nested_mutation() -> None:
    """guards read callbacks against nested mutation"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def then[A](value: A) -> A:
        mutable.add_node("C")
        return value

    def find_nested(_: str) -> bool:
        mutable.find_node(lambda _: False)
        return then(False)

    operations: list[Callable[[], object]] = [
        lambda: mutable.find_node(find_nested),
        lambda: mutable.find_nodes(lambda _: then(False)),
        lambda: mutable.find_edge(lambda _d, _s, _t: then(False)),
        lambda: mutable.find_edges(lambda _d, _s, _t: then(False)),
        lambda: mutable.to_graph_viz(edge_label=lambda e: then(str(e))),
        lambda: mutable.to_mermaid(node_shape=lambda _: then("rectangle")),
        lambda: mutable.maximum_flow(source=0, target=1, capacity=then),
        lambda: mutable.minimum_cut(source=0, target=1, capacity=then),
        lambda: mutable.dijkstra(source=0, target=1, cost=then),
        lambda: mutable.floyd_warshall(then),
        lambda: mutable.astar(source=0, target=1, cost=then, heuristic=zero),
        lambda: mutable.astar(source=0, target=1, cost=identity, heuristic=lambda _n, _t: then(0)),
        lambda: mutable.bellman_ford(source=0, target=1, cost=then),
        lambda: list(mutable.all_shortest_paths(source=0, target=1, cost=then)),
        lambda: list(mutable.dfs(start=[0]).visit(lambda _i, _v: then(None))),
        lambda: list(mutable.nodes().visit(lambda _i, _v: then(None))),
        lambda: list(mutable.edges().visit(lambda _i, _v: then(None))),
        lambda: list(mutable.externals().visit(lambda _i, _v: then(None))),
    ]
    for operation in operations:
        assert_graph_error(operation, "Cannot mutate graph during a transformation")

    undirected_mutable = undirected(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def cost(edge: int) -> int:
        undirected_mutable.add_node("C")
        return edge

    assert_graph_error(
        lambda: undirected_mutable.minimum_spanning_forest(cost),
        "Cannot mutate graph during a transformation",
    )


# --- node operations ----------------------------------------------------------------


def test_allocates_stable_indexes_and_supports_lookup_membership_and_count() -> None:
    """allocates stable indexes and supports lookup, membership, and count"""
    empty: Graph[str | None, Any] = graph.directed()
    mutable = empty.begin_mutation()
    assert mutable.add_node(None) == 0
    assert mutable.add_node("B") == 1
    assert mutable.node_count() == 2
    assert mutable.has_node(0)
    assert not mutable.has_node(2)
    assert mutable.get_node(0) == Some(None)
    assert mutable.pipe(lambda m: m.get_node(0)) == Some(None)
    assert mutable.get_node(2) is None


def test_updates_existing_payloads_and_ignores_missing_indexes() -> None:
    """updates existing payloads and ignores missing indexes"""
    mutable = directed([None, "B"]).begin_mutation()
    mutable.update_node(0, lambda _: "A")
    mutable.update_node(1, lambda _: None)
    mutable.update_node(99, lambda _: "missing")
    assert list(mutable) == [(0, "A"), (1, None)]


def test_finds_the_first_and_all_matching_nodes_in_graph_order() -> None:
    """finds the first and all matching nodes in graph order"""
    g = directed([None, "B", None])
    assert g.find_node(lambda node: node is None) == 0
    assert g.pipe(lambda x: x.find_node(lambda node: node == "missing")) is None
    assert g.find_nodes(lambda node: node is None) == [0, 2]


# --- edge operations ----------------------------------------------------------------


def test_allocates_parallel_edges_and_self_loops_with_exact_stored_orientation() -> None:
    """allocates parallel edges and self-loops with exact stored orientation"""

    def build(m: graph.MutableUndirectedGraph[str, str]) -> None:
        m.add_node("A")
        m.add_node("B")
        assert m.add_edge(1, 0, "first") == 0
        assert m.add_edge(1, 0, "parallel") == 1
        assert m.add_edge(0, 0, "loop") == 2

    assert_snapshot(
        graph.undirected(build),
        "undirected",
        [(0, "A"), (1, "B")],
        [(0, 1, 0, "first"), (1, 1, 0, "parallel"), (2, 0, 0, "loop")],
    )


def test_rejects_missing_edge_endpoints() -> None:
    """rejects missing edge endpoints"""
    mutable = directed(["A"], list[EdgeSpec[int]]()).begin_mutation()
    assert_graph_error(lambda: mutable.add_edge(1, 0, 1), "Node 1 does not exist")
    assert_graph_error(lambda: mutable.add_edge(0, 1, 1), "Node 1 does not exist")


def test_gets_and_updates_undefined_edge_data_without_exposing_stored_records() -> None:
    """gets and updates undefined edge data without exposing stored records"""
    edges: list[EdgeSpec[int | None]] = [(0, 1, None)]
    mutable = directed(["A", "B"], edges).begin_mutation()
    from_getter = mutable.get_edge(0)
    assert from_getter is not None
    from_walker = next(iter(mutable.edges().values()))
    with pytest.raises(AttributeError):
        from_getter.source = 1  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(AttributeError):
        from_walker.data = 1  # pyright: ignore[reportAttributeAccessIssue]
    assert mutable.get_edge(0) == Edge(0, 1, None)
    assert_snapshot(mutable, "directed", [(0, "A"), (1, "B")], [(0, 0, 1, None)])
    assert mutable.neighbors(0) == [1]
    assert mutable.neighbors(1) == []

    mutable.update_edge(0, lambda _: 2)
    mutable.update_edge(99, lambda _: 3)
    assert mutable.get_edge(0) == Edge(0, 1, 2)
    assert mutable.pipe(lambda m: m.get_edge(99)) is None
    assert_snapshot(mutable, "directed", [(0, "A"), (1, "B")], [(0, 0, 1, 2)])
    assert mutable.neighbors(0) == [1]


def test_removes_parallel_undirected_edges_and_self_loops_independently() -> None:
    """removes parallel undirected edges and self-loops independently"""
    mutable = undirected(
        ["A", "B"], [(1, 0, "first"), (0, 1, "second"), (1, 1, "loop")]
    ).begin_mutation()
    mutable.remove_edge(0)
    mutable.remove_edge(2)
    mutable.remove_edge(99)
    assert_snapshot(mutable, "undirected", [(0, "A"), (1, "B")], [(1, 0, 1, "second")])
    assert mutable.neighbors(0) == [1]
    assert mutable.neighbors(1) == [0]


def test_removes_undirected_nodes_with_reversed_edges_parallel_edges_and_self_loops() -> None:
    """removes undirected nodes with reversed edges, parallel edges, and self-loops"""
    mutable = undirected(
        ["A", "B", "C"],
        [(1, 0, "reverse"), (0, 1, "parallel"), (1, 1, "loop"), (2, 0, "keep")],
    ).begin_mutation()
    mutable.remove_node(1)
    assert_snapshot(mutable, "undirected", [(0, "A"), (2, "C")], [(3, 2, 0, "keep")])


def test_collects_graph_backed_iterables_before_bulk_removal() -> None:
    """collects graph-backed iterables before bulk removal"""
    edges = directed(["A", "B"], [(0, 1, 1), (1, 0, 2)]).begin_mutation()
    edges.remove_edges(edges.edges().indices())
    assert edges.edge_count() == 0
    nodes = directed(["A", "B"]).begin_mutation()
    nodes.remove_nodes(nodes.nodes().indices())
    assert nodes.node_count() == 0


def test_keeps_caches_fresh_when_bulk_removal_iterables_query_the_graph() -> None:
    """keeps caches fresh when bulk-removal iterables query the graph"""
    edges = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def edge_ids() -> Iterable[int]:
        assert edges.has_path(0, 1)
        yield 0

    edges.remove_edges(edge_ids())
    assert not edges.has_path(0, 1)

    nodes = directed(["A", "B"], [(0, 1, 1), (1, 0, 2)]).begin_mutation()

    def node_ids() -> Iterable[int]:
        assert not nodes.is_acyclic()
        yield 1

    nodes.remove_nodes(node_ids())
    assert nodes.is_acyclic()


def test_rejects_finalization_from_bulk_removal_iterables() -> None:
    """rejects finalization from bulk-removal iterables"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()

    def ending() -> Iterable[int]:
        mutable.end_mutation()
        yield 0

    assert_graph_error(
        lambda: mutable.remove_edges(ending()), "Cannot mutate graph during a transformation"
    )
    assert mutable.mutable
    assert mutable.edge_count() == 1


# --- transformations ----------------------------------------------------------------


def test_maps_nodes_and_edges_while_preserving_indexes_and_structure() -> None:
    """maps nodes and edges while preserving indexes and structure"""
    mutable = directed(["a", "b"], [(0, 1, 2)]).begin_mutation()
    mutable.map_nodes(str.upper)
    mutable.map_edges(lambda edge: edge * 3)
    assert_snapshot(mutable, "directed", [(0, "A"), (1, "B")], [(0, 0, 1, 6)])


def test_filter_maps_nodes_and_removes_incident_edges() -> None:
    """filter-maps nodes and removes incident edges"""
    mutable = directed(
        [1, 2, 3], [(0, 1, "remove"), (1, 2, "remove"), (0, 2, "keep")]
    ).begin_mutation()
    mutable.filter_map_nodes(lambda node: None if node == 2 else Some(node * 10))
    assert_snapshot(mutable, "directed", [(0, 10), (2, 30)], [(2, 0, 2, "keep")])


def test_filter_maps_edges_without_removing_nodes() -> None:
    """filter-maps edges without removing nodes"""
    mutable = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2), (2, 0, 3)]).begin_mutation()
    mutable.filter_map_edges(lambda edge: None if edge % 2 == 0 else Some(edge * 10))
    assert_snapshot(
        mutable, "directed", [(0, "A"), (1, "B"), (2, "C")], [(0, 0, 1, 10), (2, 2, 0, 30)]
    )


def test_filters_nodes_and_removes_their_incident_edges() -> None:
    """filters nodes and removes their incident edges"""
    nodes = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2), (0, 2, 3)]).begin_mutation()
    nodes.filter_nodes(lambda node: node != "B")
    assert_snapshot(nodes, "directed", [(0, "A"), (2, "C")], [(2, 0, 2, 3)])


def test_filters_edges_without_removing_nodes() -> None:
    """filters edges without removing nodes"""
    edges = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2), (0, 2, 3)]).begin_mutation()
    edges.filter_edges(lambda edge: edge % 2 == 1)
    assert_snapshot(edges, "directed", [(0, "A"), (1, "B"), (2, "C")], [(0, 0, 1, 1), (2, 0, 2, 3)])


def test_exposes_earlier_bulk_writes_to_later_callbacks() -> None:
    """exposes earlier bulk writes to later callbacks"""
    nodes = directed(["a", "b"]).begin_mutation()
    node_states: list[list[str]] = []

    def upper(node: str) -> str:
        node_states.append(list(nodes.nodes().values()))
        return node.upper()

    nodes.map_nodes(upper)
    assert node_states == [["a", "b"], ["A", "b"]]

    edges = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2)]).begin_mutation()
    edge_states: list[list[int]] = []

    def double(edge: int) -> int:
        edge_states.append([e.data for e in edges.edges().values()])
        return edge * 2

    edges.map_edges(double)
    assert edge_states == [[1, 2], [2, 2]]


def test_publishes_updated_callback_values_to_subsequent_graph_reads() -> None:
    """publishes updated callback values to subsequent graph reads"""
    nodes = directed(["old"]).begin_mutation()

    def renew(_: str) -> str:
        assert list(nodes.bfs(start=[0]).values()) == ["old"]
        return "new"

    nodes.update_node(0, renew)
    assert list(nodes.bfs(start=[0]).values()) == ["new"]

    edges = directed(["source", "target"], [(0, 1, 1)]).begin_mutation()

    def bump(_: int) -> int:
        assert next(iter(edges.simple_paths(source=0, target=1))).costs == (1,)
        return 2

    edges.update_edge(0, bump)
    assert next(iter(edges.simple_paths(source=0, target=1))).costs == (2,)


def test_reverses_directed_edges_and_leaves_undirected_stored_orientation_unchanged() -> None:
    """reverses directed edges and leaves undirected stored orientation unchanged"""
    directed_mutable = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2)]).begin_mutation()
    directed_mutable.reverse()
    directed_mutable.add_edge(0, 1, 3)
    assert directed_mutable.to_snapshot().edges == (
        IndexedEdge(0, 1, 0, 1),
        IndexedEdge(1, 2, 1, 2),
        IndexedEdge(2, 0, 1, 3),
    )
    assert directed_mutable.neighbors(2) == [1]
    assert directed_mutable.has_edge(1, 0)
    assert directed_mutable.has_edge(0, 1)

    undirected_mutable = undirected(["A", "B"], [(1, 0, 1)]).begin_mutation()
    undirected_mutable.reverse()
    assert undirected_mutable.to_snapshot().edges == (IndexedEdge(0, 1, 0, 1),)


# --- set operations -----------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    id: str
    label: str


def _left() -> Graph[Node, str]:
    return directed(
        [Node("a", "A1"), Node("b", "B1"), Node("c", "C1")], [(0, 1, "left"), (1, 2, "shared")]
    )


def _right() -> Graph[Node, str]:
    return directed(
        [Node("b", "B2"), Node("c", "C2"), Node("d", "D2")], [(0, 1, "shared"), (1, 2, "right")]
    )


def _node_id(node: Node) -> str:
    return node.id


def _semantic(g: Graph[Node, str]) -> tuple[list[str], list[str]]:
    nodes = dict(g)
    return (
        sorted(f"{node.id}:{node.label}" for node in nodes.values()),
        sorted(f"{nodes[e.source].id}->{nodes[e.target].id}:{e.data}" for e in g.edges().values()),
    )


def test_composes_intersects_differs_and_symmetrically_differs_by_projected_identity() -> None:
    """composes, intersects, differs, and symmetrically differs by projected identity"""
    composed = (["a:A1", "b:B2", "c:C2", "d:D2"], ["a->b:left", "b->c:shared", "c->d:right"])
    intersected = (["b:B1", "c:C1"], ["b->c:shared"])
    differed = (["a:A1", "b:B1", "c:C1"], ["a->b:left"])
    symmetric = (["a:A1", "b:B2", "c:C2", "d:D2"], ["a->b:left", "c->d:right"])
    left, right = _left(), _right()
    assert _semantic(left.compose(right, node_identity=_node_id)) == composed
    assert _semantic(left.pipe(lambda g: g.compose(right, node_identity=_node_id))) == composed
    assert _semantic(left.intersection(right, node_identity=_node_id)) == intersected
    assert _semantic(left.difference(right, node_identity=_node_id)) == differed
    assert _semantic(left.symmetric_difference(right, node_identity=_node_id)) == symmetric


class NodeKey:
    """A key with its own ``__eq__`` / ``__hash__`` (Effect's ``Equal``)."""

    def __init__(self, id: str) -> None:
        self.id = id

    def __eq__(self, that: object) -> bool:
        return isinstance(that, NodeKey) and self.id == that.id

    def __hash__(self) -> int:
        return hash(self.id)


def test_supports_effect_equal_and_hash_node_identities() -> None:
    """supports Effect Equal and Hash node identities"""
    result = _left().compose(_right(), node_identity=lambda node: NodeKey(node.id))
    assert _semantic(result) == (
        ["a:A1", "b:B2", "c:C2", "d:D2"],
        ["a->b:left", "b->c:shared", "c->d:right"],
    )


def test_coalesces_duplicate_identities_to_the_last_payload_and_redirects_edges() -> None:
    """coalesces duplicate identities to the last payload and redirects edges"""
    g = directed([Node("a", "first"), Node("a", "last")], [(0, 1, "edge")])
    result = g.compose(graph.directed(), node_identity=_node_id)
    edge = next(iter(result.edges().values()))
    assert list(result.nodes().values()) == [Node("a", "last")]
    assert edge.source == edge.target


@dataclass(frozen=True)
class Labeled:
    id: str
    label: str


def test_uses_right_edge_payloads_for_custom_identity_compose_and_intersection() -> None:
    """uses right edge payloads for custom-identity compose and intersection"""
    left = directed(["A", "B"], [(0, 1, Labeled("shared", "left"))])
    right = directed(["A", "B"], [(0, 1, Labeled("shared", "right"))])

    def edge_id(edge: Labeled) -> str:
        return edge.id

    composed = left.compose(right, edge_identity=edge_id)
    intersected = left.intersection(right, edge_identity=edge_id)
    assert next(iter(composed.edges().values())).data.label == "right"
    assert next(iter(intersected.edges().values())).data.label == "right"


def test_includes_edge_data_in_the_default_edge_identity() -> None:
    """includes edge data in the default edge identity"""
    first = directed(["A", "B"], [(0, 1, "left")])
    second = directed(["A", "B"], [(0, 1, "right")])
    assert first.compose(second).edge_count() == 2
    assert first.intersection(second).edge_count() == 0
    assert first.difference(second).edge_count() == 1
    assert first.symmetric_difference(second).edge_count() == 2


def test_uses_undefined_node_data_as_the_default_node_identity() -> None:
    """uses undefined node data as the default node identity"""
    assert directed([None]).compose(directed([None])).node_count() == 1


def test_treats_equal_parallel_edges_as_set_members_while_difference_preserves_unmatched_occurrences() -> (  # noqa: E501
    None
):
    """treats equal parallel edges as set members while difference preserves unmatched occurrences"""  # noqa: E501
    parallel = directed(["A", "B"], [(0, 1, "same"), (0, 1, "same")])
    one = directed(["A", "B"], [(0, 1, "same")])
    empty: Graph[str, str] = graph.directed()
    assert parallel.compose(empty).edge_count() == 1
    assert parallel.intersection(one).edge_count() == 1
    assert parallel.difference(empty).edge_count() == 2
    assert parallel.difference(one).edge_count() == 0
    assert parallel.symmetric_difference(empty).edge_count() == 1


def test_matches_undirected_identities_independent_of_stored_orientation() -> None:
    """matches undirected identities independent of stored orientation"""
    first = undirected(["A", "B"], [(0, 1, "same")])
    second = undirected(["B", "A"], [(0, 1, "same")])
    assert first.intersection(second).edge_count() == 1
    assert first.difference(second).edge_count() == 0


def test_rejects_runtime_kind_mismatches_for_every_binary_set_operation() -> None:
    """rejects runtime kind mismatches for every binary set operation"""
    first = cast("Graph[str, str, Kind]", graph.directed())
    second = cast("Graph[str, str, Kind]", graph.undirected())
    operations: list[Callable[[], object]] = [
        lambda: first.compose(second),
        lambda: first.intersection(second),
        lambda: first.difference(second),
        lambda: first.symmetric_difference(second),
        lambda: first.sum(second),
    ]
    for operation in operations:
        assert_graph_error(operation, "Cannot combine directed and undirected graphs")


def test_builds_directed_and_undirected_complements_without_self_loops() -> None:
    """builds directed and undirected complements without self-loops"""

    def join(a: str, b: str) -> str:
        return f"{a}-{b}"

    assert_snapshot(
        directed(["A", "B"], [(0, 1, "existing")]).complement(join),
        "directed",
        [(0, "A"), (1, "B")],
        [(0, 1, 0, "B-A")],
    )
    assert_snapshot(
        undirected(["A", "B", "C"], [(0, 1, "existing")]).complement(join),
        "undirected",
        [(0, "A"), (1, "B"), (2, "C")],
        [(0, 0, 2, "A-C"), (1, 1, 2, "B-C")],
    )


def test_returns_induced_neighborhoods_and_validates_radius() -> None:
    """returns induced neighborhoods and validates radius"""
    g = directed(["A", "B", "C", "D"], [(0, 1, "AB"), (1, 2, "BC"), (2, 1, "CB"), (2, 3, "CD")])
    assert_snapshot(
        g.neighborhood(1, radius=1),
        "directed",
        [(0, "B"), (1, "C")],
        [(0, 0, 1, "BC"), (1, 1, 0, "CB")],
    )
    assert_snapshot(
        g.pipe(lambda x: x.neighborhood(1, radius=math.inf)),
        "directed",
        [(0, "B"), (1, "C"), (2, "D")],
        [(0, 0, 1, "BC"), (1, 1, 0, "CB"), (2, 1, 2, "CD")],
    )
    for radius in [math.nan, -1, 0.5]:
        assert_graph_error(
            lambda radius=radius: g.neighborhood(1, radius=radius),
            "Traversal radius must be a non-negative integer or Infinity",
        )


def test_can_ignore_edge_direction_when_selecting_a_neighborhood() -> None:
    """can ignore edge direction when selecting a neighborhood"""
    g = directed(["A", "B", "C"], [(0, 1, "AB"), (0, 2, "AC")])
    assert_snapshot(
        g.neighborhood(1, radius=2, direction="undirected"),
        "directed",
        [(0, "B"), (1, "A"), (2, "C")],
        [(0, 1, 0, "AB"), (1, 1, 2, "AC")],
    )


def test_preserves_sparse_indexes_in_induced_subgraphs_and_rejects_missing_nodes() -> None:
    """preserves sparse indexes in induced subgraphs and rejects missing nodes"""
    g = graph.from_snapshot(
        snapshot(
            "directed",
            [(2, "A"), (5, "B"), (9, "C")],
            [(3, 2, 5, "AB"), (7, 5, 9, "BC"), (11, 5, 5, "loop")],
        )
    )
    assert_snapshot(
        g.pipe(lambda x: x.induced_subgraph([9, 5, 5])),
        "directed",
        [(5, "B"), (9, "C")],
        [(7, 5, 9, "BC"), (11, 5, 5, "loop")],
    )
    assert_graph_error(lambda: g.induced_subgraph([2, 4]), "Node 4 does not exist")


def test_preserves_graph_kind_for_empty_induced_subgraphs() -> None:
    """preserves graph kind for empty induced subgraphs"""
    assert_snapshot(graph.undirected().induced_subgraph([]), "undirected", [])


def test_keeps_equal_nodes_and_their_edges_disjoint_in_sums() -> None:
    """keeps equal nodes and their edges disjoint in sums"""
    first = directed(["A", "B"], [(0, 1, "left")])
    second = directed(["A", "B"], [(0, 1, "right")])
    for result in (first.sum(second), first.pipe(lambda g: g.sum(second))):
        assert_snapshot(
            result,
            "directed",
            [(0, "A"), (1, "B"), (2, "A"), (3, "B")],
            [(0, 0, 1, "left"), (1, 2, 3, "right")],
        )


# --- queries ------------------------------------------------------------------------


def _query_graph() -> Graph[str, str]:
    return directed(
        ["A", "B", "C"],
        [(0, 1, "first"), (0, 1, "parallel"), (2, 0, "incoming"), (0, 0, "loop"), (0, 2, "last")],
    )


def test_reports_exact_edge_order_multiplicity_and_directed_degrees() -> None:
    """reports exact edge order, multiplicity, and directed degrees"""
    g = _query_graph()
    assert g.incident_edges(0) == [0, 1, 2, 3, 4]
    assert g.outgoing_edges(0) == [0, 1, 3, 4]
    assert g.incoming_edges(0) == [2, 3]
    assert g.edges_between(0, 1) == [0, 1]
    assert g.edges_between(1, 0) == []
    assert g.out_degree(0) == 4
    assert g.in_degree(0) == 2


def test_deduplicates_neighbors_in_first_edge_occurrence_order() -> None:
    """deduplicates neighbors in first-edge occurrence order"""
    g = _query_graph()
    assert g.neighbors(0) == [1, 0, 2]
    assert g.pipe(lambda x: x.successors(0)) == [1, 0, 2]
    assert g.predecessors(0) == [2, 0]
    assert g.neighbors_directed(0, "outgoing") == [1, 0, 2]
    assert g.successors(0.5) == []  # pyright: ignore[reportArgumentType]


def test_deduplicates_high_degree_neighbors_in_first_edge_occurrence_order() -> None:
    """deduplicates high-degree neighbors in first-edge occurrence order"""
    targets = list(range(1, 35))
    g = directed([0, *targets], [(0, target, None) for target in [2, 1, *targets, 1]])
    assert g.neighbors(0) == [2, 1, *targets[2:]]


def test_handles_undirected_orientation_self_loops_parallel_edges_and_degree() -> None:
    """handles undirected orientation, self-loops, parallel edges, and degree"""
    g = undirected(["A", "B"], [(1, 0, 1), (0, 1, 2), (0, 0, 3)])
    assert g.neighbors(0) == [1, 0]
    assert g.neighbors(1) == [0]
    assert g.incident_edges(0) == [0, 1, 2]
    assert g.edges_between(0, 1) == [0, 1]
    assert g.degree(0) == 4
    assert g.has_edge(0, 1)
    assert g.has_edge(1, 0)


def test_preserves_edge_order_when_merging_directed_incidence_and_scanning_undirected_adjacency() -> (  # noqa: E501
    None
):
    """preserves edge order when merging directed incidence and scanning undirected adjacency"""
    directed_graph = directed(
        [0, 1, 2],
        [
            (0, 1, "out-first"),
            (2, 0, "in-first"),
            (0, 0, "loop"),
            (0, 2, "out-last"),
            (1, 0, "in-last"),
        ],
    )
    assert directed_graph.incident_edges(0) == [0, 1, 2, 3, 4]
    assert directed_graph.edges_between(0, 0) == [2]
    undirected_graph = undirected(
        [0, 1, 2], [(1, 0, "reverse"), (0, 0, "loop"), (0, 2, "forward"), (2, 0, "reverse-last")]
    )
    assert undirected_graph.incident_edges(0) == [0, 1, 2, 3]
    assert undirected_graph.edges_between(0, 2) == [2, 3]
    assert undirected_graph.edges_between(2, 0) == [2, 3]


def test_reports_directed_edge_membership_without_assuming_symmetry() -> None:
    """reports directed edge membership without assuming symmetry"""
    g = directed(["A", "B", "C"], [(0, 1, 1)])
    assert g.has_edge(0, 1)
    assert not g.has_edge(1, 0)
    assert not g.has_edge(0, 2)
    assert not g.has_edge(99, 0)


def test_passes_stored_endpoints_to_edge_finder_predicates() -> None:
    """passes stored endpoints to edge finder predicates"""
    g = undirected(["A", "B", "C"], [(2, 0, "match"), (0, 1, "match")])
    calls: list[tuple[str, int, int]] = []

    def predicate(data: str, source: int, target: int) -> bool:
        calls.append((data, source, target))
        return source == 0

    assert g.find_edge(predicate) == 1
    assert calls == [("match", 2, 0), ("match", 0, 1)]
    assert g.find_edges(lambda _, source, target: source > target) == [0]


def test_finds_undefined_edge_payloads() -> None:
    """finds undefined edge payloads"""
    edges: list[EdgeSpec[int | None]] = [(0, 1, None), (1, 2, 42), (2, 0, None)]
    g = directed(["A", "B", "C"], edges)
    assert g.find_edge(lambda edge, _s, _t: edge is None) == 0
    assert g.find_edges(lambda edge, _s, _t: edge is None) == [0, 2]


def test_reports_kind_and_missing_node_errors_consistently() -> None:
    """reports kind and missing-node errors consistently"""
    one: Graph[str, int, Any] = directed(["A"], list[EdgeSpec[int]]())
    undirected_one: Graph[str, int, Any] = undirected(["A"], list[EdgeSpec[int]]())
    assert_graph_error(lambda: one.degree(0), "Cannot get degree of directed graph")
    assert_graph_error(
        lambda: undirected_one.outgoing_edges(0), "Cannot get outgoing edges of undirected graph"
    )
    assert_graph_error(
        lambda: undirected_one.incoming_edges(0), "Cannot get incoming edges of undirected graph"
    )
    assert_graph_error(
        lambda: undirected_one.successors(0), "Cannot get successors of undirected graph"
    )
    assert_graph_error(lambda: one.incident_edges(1), "Node 1 does not exist")
    assert_graph_error(lambda: one.edges_between(0, 1), "Node 1 does not exist")


# --- serialization ------------------------------------------------------------------


def test_serializes_representative_directed_and_undirected_graphviz_graphs_exactly() -> None:
    """serializes representative directed and undirected GraphViz graphs exactly"""
    directed_graph = directed(["A", "B"], [(0, 1, 1)])
    directed_expected = "\n".join(
        [
            'digraph "G" {',
            '  "0" [label="A"];',
            '  "1" [label="B"];',
            '  "0" -> "1" [label="1"];',
            "}",
        ]
    )
    assert directed_graph.to_graph_viz() == directed_expected
    assert directed_graph.pipe(lambda g: g.to_graph_viz()) == directed_expected
    assert undirected(["A", "B"], [(1, 0, "edge")]).to_graph_viz() == "\n".join(
        [
            'graph "G" {',
            '  "0" [label="A"];',
            '  "1" [label="B"];',
            '  "1" -- "0" [label="edge"];',
            "}",
        ]
    )


def test_escapes_graphviz_graph_names_and_labels_exactly() -> None:
    """escapes GraphViz graph names and labels exactly"""
    g = directed(['C:\\new\n"line"', "end"], [(0, 1, 'edge\\path\n"quoted"')])
    assert g.to_graph_viz(
        graph_name='My "Graph"', node_label=lambda node: f"node:{node}", edge_label=identity
    ) == "\n".join(
        [
            'digraph "My \\"Graph\\"" {',
            '  "0" [label="node:C:\\\\new\\n\\"line\\""];',
            '  "1" [label="node:end"];',
            '  "0" -> "1" [label="edge\\\\path\\n\\"quoted\\""];',
            "}",
        ]
    )


def test_serializes_representative_directed_and_undirected_mermaid_graphs_exactly() -> None:
    """serializes representative directed and undirected Mermaid graphs exactly"""
    directed_graph = directed(["A", "B"], [(0, 1, "edge")])
    directed_expected = "\n".join(["flowchart TD", '  0["A"]', '  1["B"]', '  0 -->|"edge"| 1'])
    assert directed_graph.to_mermaid() == directed_expected
    assert directed_graph.pipe(lambda g: g.to_mermaid()) == directed_expected
    assert undirected(["A", "B"], [(1, 0, "")]).to_mermaid() == "\n".join(
        ["graph TD", '  0["A"]', '  1["B"]', "  1 --- 0"]
    )


def test_escapes_mermaid_labels_and_applies_direction_type_and_custom_labels() -> None:
    """escapes Mermaid labels and applies direction, type, and custom labels"""
    g = directed(['#"<>&[]{}()|\\', "B\r\n2\r3\n4"], [(0, 1, 2)])
    serialized = g.to_mermaid(
        direction="LR",
        diagram_type="graph",
        node_label=identity,
        edge_label=lambda weight: f"w({weight})",
    )
    assert serialized == "\n".join(
        [
            "graph LR",
            '  0["#35;#quot;#lt;#gt;#amp;#91;#93;#123;#125;#40;#41;#124;#92;"]',
            '  1["B<br/>2<br/>3<br/>4"]',
            '  0 ---|"w#40;2#41;"| 1',
        ]
    )
    assert "\r" not in serialized


def test_supports_every_mermaid_node_shape() -> None:
    """supports every Mermaid node shape"""
    expected: list[tuple[graph.MermaidNodeShape, str]] = [
        ("rectangle", '0["A"]'),
        ("rounded", '0("A")'),
        ("circle", '0(("A"))'),
        ("diamond", '0{"A"}'),
        ("hexagon", '0{{"A"}}'),
        ("stadium", '0(["A"])'),
        ("subroutine", '0[["A"]]'),
        ("cylindrical", '0[("A")]'),
    ]
    for shape, node in expected:
        rendered = directed(["A"]).to_mermaid(node_shape=lambda _, shape=shape: shape)
        assert rendered == f"flowchart TD\n  {node}"


# --- cycles and connectivity --------------------------------------------------------


def test_returns_exact_sparse_cycle_witnesses_including_self_loops_and_parallel_edges() -> None:
    """returns exact sparse cycle witnesses including self-loops and parallel edges"""
    directed_cycle = graph.from_snapshot(
        snapshot(
            "directed",
            [(2, "A"), (5, "B"), (9, "C")],
            [(3, 2, 5, 1), (7, 5, 9, 1), (11, 9, 2, 1)],
        )
    )
    assert directed_cycle.find_cycle() == CycleResult((2, 5, 9, 2), (3, 7, 11))
    assert undirected(["A"], [(0, 0, 1)]).find_cycle() == CycleResult((0, 0), (0,))
    assert undirected(["A", "B"], [(0, 1, 1), (1, 0, 2)]).find_cycle() == CycleResult(
        (0, 1, 0), (0, 1)
    )


def test_returns_none_for_acyclic_directed_and_reversed_storage_undirected_graphs() -> None:
    """returns None for acyclic directed and reversed-storage undirected graphs"""
    assert directed([0, 1, 2], [(0, 1, 1), (1, 2, 1)]).find_cycle() is None
    assert undirected([0, 1, 2], [(0, 1, 1), (2, 1, 1)]).find_cycle() is None


def test_invalidates_acyclic_results_after_adding_and_removing_a_cycle_edge() -> None:
    """invalidates acyclic results after adding and removing a cycle edge"""
    mutable = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 1)]).begin_mutation()
    assert mutable.is_acyclic()
    cycle = mutable.add_edge(2, 0, 1)
    assert not mutable.is_acyclic()
    mutable.remove_edge(cycle)
    assert mutable.is_acyclic()


def test_handles_undirected_reversed_orientation_self_loops_and_parallel_cycles() -> None:
    """handles undirected reversed orientation, self-loops, and parallel cycles"""
    assert undirected(["A", "B", "C"], [(0, 1, 1), (2, 1, 1)]).is_acyclic()
    assert not undirected(["A"], [(0, 0, 1)]).is_acyclic()
    assert not undirected(["A", "B"], [(0, 1, 1), (0, 1, 2)]).is_acyclic()


def test_returns_complete_connected_weak_and_strong_component_partitions() -> None:
    """returns complete connected, weak, and strong component partitions"""
    connected = undirected(["A", "B", "C", "D", "E"], [(0, 1, 1), (2, 3, 1)])
    directed_graph = directed(
        ["A", "B", "C", "D", "E"], [(0, 1, 1), (1, 0, 1), (2, 1, 1), (3, 4, 1)]
    )
    assert canonical(connected.connected_components()) == [[0, 1], [2, 3], [4]]
    assert canonical(directed_graph.weakly_connected_components()) == [[0, 1, 2], [3, 4]]
    assert canonical(directed_graph.strongly_connected_components()) == [[0, 1], [2], [3], [4]]
    assert canonical(connected.begin_mutation().connected_components()) == [[0, 1], [2, 3], [4]]
    assert canonical(directed_graph.begin_mutation().strongly_connected_components()) == [
        [0, 1],
        [2],
        [3],
        [4],
    ]


def test_computes_reachability_in_outgoing_incoming_and_undirected_modes() -> None:
    """computes reachability in outgoing, incoming, and undirected modes"""
    g = directed(["A", "B", "C", "D"], [(0, 1, 1), (1, 2, 1), (3, 1, 1)])
    assert list(g.unweighted_distances(0).items()) == [(0, 0), (1, 1), (2, 2)]
    assert list(g.unweighted_distances(2, direction="incoming").items()) == [
        (0, 2),
        (1, 1),
        (2, 0),
        (3, 2),
    ]
    assert list(g.unweighted_distances(0, direction="undirected").items()) == [
        (0, 0),
        (1, 1),
        (2, 2),
        (3, 2),
    ]
    assert g.has_path(0, 2)
    assert not g.has_path(2, 0)
    assert g.pipe(lambda x: x.has_path(2, 0, direction="incoming"))
    assert not g.has_path(2, 3)
    assert g.has_path(2, 3, direction="undirected")


def test_updates_connectivity_results_after_mutable_changes() -> None:
    """updates connectivity results after mutable changes"""
    mutable = directed(["A", "B", "C"], [(0, 1, 1)]).begin_mutation()
    assert canonical(mutable.weakly_connected_components()) == [[0, 1], [2]]
    assert not mutable.has_path(0, 2)
    mutable.add_edge(1, 2, 1)
    assert canonical(mutable.weakly_connected_components()) == [[0, 1, 2]]
    assert mutable.has_path(0, 2)


def test_checks_connected_weak_strong_and_tree_predicates_including_empty_graphs() -> None:
    """checks connected, weak, strong, and tree predicates including empty graphs"""
    tree = undirected(["A", "B", "C"], [(0, 1, 1), (1, 2, 1)])
    disconnected = undirected(["A", "B"])
    weak = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 1)])
    weakly_disconnected = directed(["A", "B"])
    strong = weak.mutate(lambda m: _ignore(m.add_edge(2, 0, 1)))
    assert tree.is_connected()
    assert not disconnected.is_connected()
    assert tree.is_tree()
    assert weak.is_weakly_connected()
    assert not weakly_disconnected.is_weakly_connected()
    assert not weak.is_strongly_connected()
    assert strong.is_strongly_connected()
    assert graph.undirected().is_connected()
    assert not graph.undirected().is_tree()


def test_rejects_runtime_connectivity_kind_mismatches_and_missing_endpoints() -> None:
    """rejects runtime connectivity kind mismatches and missing endpoints"""
    directed_graph: Graph[Any, Any, Any] = graph.directed()
    undirected_graph: Graph[Any, Any, Any] = graph.undirected()
    assert_graph_error(
        directed_graph.connected_components, "Cannot find connected components of directed graph"
    )
    assert_graph_error(
        undirected_graph.weakly_connected_components,
        "Cannot find weakly connected components of undirected graph",
    )
    assert_graph_error(
        undirected_graph.strongly_connected_components,
        "Cannot find strongly connected components of undirected graph",
    )
    assert_graph_error(directed_graph.is_tree, "Cannot determine tree status of directed graph")
    assert_graph_error(lambda: graph.directed().has_path(0, 1), "Node 0 does not exist")


# --- bipartite graphs ---------------------------------------------------------------


def test_recognizes_even_odd_disconnected_and_self_loop_cases() -> None:
    """recognizes even, odd, disconnected, and self-loop cases"""
    even = undirected([0, 1, 2, 3], [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 0, 1)])
    assert even.is_bipartite()
    assert even.begin_mutation().is_bipartite()
    assert not undirected([0, 1, 2], [(0, 1, 1), (1, 2, 1), (2, 0, 1)]).is_bipartite()
    assert undirected([0, 1, 2, 3], [(0, 1, 1), (2, 3, 1)]).is_bipartite()
    assert not undirected([0], [(0, 0, 1)]).is_bipartite()


def test_reads_fresh_mutable_structure_after_bipartite_mutations() -> None:
    """reads fresh mutable structure after bipartite mutations"""
    mutable = undirected([0, 1, 2], [(0, 1, 1), (1, 2, 1)]).begin_mutation()
    assert mutable.is_bipartite()
    mutable.add_edge(2, 0, 1)
    assert not mutable.is_bipartite()
    mutable.remove_edge(2)
    mutable.add_edge(0, 1, 1)
    assert mutable.is_bipartite()
    mutable.add_edge(2, 2, 1)
    assert not mutable.is_bipartite()


def test_returns_deterministic_maximum_matches_and_the_first_parallel_edge() -> None:
    """returns deterministic maximum matches and the first parallel edge"""
    g = undirected(
        [0, 1, 2, 3],
        [(0, 2, "first"), (2, 0, "parallel"), (0, 3, "edge"), (1, 2, "edge"), (1, 3, "edge")],
    )
    expected = [BipartiteMatch(0, 2, 0), BipartiteMatch(1, 3, 4)]
    assert g.maximum_bipartite_matching() == expected
    assert g.begin_mutation().maximum_bipartite_matching() == expected


def _oracle_matching(adjacency: list[list[int]], left: int = 0, used: int = 0) -> int:
    if left == len(adjacency):
        return 0
    best = _oracle_matching(adjacency, left + 1, used)
    for right in adjacency[left]:
        if used & (1 << right) == 0:
            best = max(best, 1 + _oracle_matching(adjacency, left + 1, used | (1 << right)))
    return best


def test_matches_a_brute_force_oracle_for_every_three_by_three_bipartite_graph() -> None:
    """matches a brute-force oracle for every three-by-three bipartite graph"""
    for mask in range(1 << 9):
        adjacency: list[list[int]] = [[], [], []]
        edges: list[EdgeSpec[None]] = []
        for left, right in itertools.product(range(3), range(3)):
            if mask & (1 << (left * 3 + right)):
                adjacency[left].append(right)
                edges.append((left, right + 3, None))
        g = undirected([None] * 6, edges)
        matching = g.maximum_bipartite_matching()
        assert len(matching) == _oracle_matching(adjacency)
        assert len({match.left for match in matching}) == len(matching)
        assert len({match.right for match in matching}) == len(matching)
        for match in matching:
            assert 0 <= match.left < 3
            assert 3 <= match.right < 6
            edge = g.get_edge(match.edge)
            assert edge is not None
            assert {edge.source, edge.target} == {match.left, match.right}


def test_rejects_directed_and_non_bipartite_graphs() -> None:
    """rejects directed and non-bipartite graphs"""
    directed_graph: Graph[Any, Any, Any] = graph.directed()
    assert_graph_error(
        directed_graph.is_bipartite, "Cannot determine bipartite status of directed graph"
    )
    assert_graph_error(
        directed_graph.maximum_bipartite_matching,
        "Cannot find bipartite matching of directed graph",
    )
    assert_graph_error(
        undirected([0, 1, 2], [(0, 1, 1), (1, 2, 1), (2, 0, 1)]).maximum_bipartite_matching,
        "Cannot find bipartite matching of non-bipartite graph",
    )


# --- low-link connectivity ----------------------------------------------------------


def _analyze(g: graph.GraphView[Any, Any, graph.Undirected]) -> tuple[Any, Any, Any]:
    return (g.bridges(), g.articulation_points(), g.biconnected_components())


def test_handles_paths_cycles_disconnected_components_parallel_edges_loops_and_sparse_indexes() -> (
    None
):
    """handles paths, cycles, disconnected components, parallel edges, loops, and sparse indexes"""
    g = graph.from_snapshot(
        snapshot(
            "undirected",
            [(2, "A"), (5, "B"), (9, "C"), (12, "D")],
            [(3, 5, 2, "first"), (7, 2, 5, "parallel"), (11, 5, 9, "bridge"), (13, 9, 9, "loop")],
        )
    )
    expected = ([11], [5], [[2, 5], [5, 9], [9]])
    assert _analyze(g) == expected
    assert _analyze(g.begin_mutation()) == expected


def test_groups_cycles_sharing_an_articulation_point_across_disconnected_components() -> None:
    """groups cycles sharing an articulation point across disconnected components"""
    g = undirected(
        [None] * 8,
        [
            *[(0, 1, None), (1, 2, None), (2, 0, None)],
            *[(2, 3, None), (3, 4, None), (4, 2, None)],
            (5, 6, None),
        ],
    )
    assert _analyze(g) == ([6], [2], [[0, 1, 2], [2, 3, 4], [5, 6]])


def test_returns_empty_results_for_empty_and_isolated_graphs() -> None:
    """returns empty results for empty and isolated graphs"""
    assert _analyze(graph.undirected()) == ([], [], [])
    assert _analyze(undirected([None])) == ([], [], [])


def test_rejects_directed_graphs_at_runtime() -> None:
    """rejects directed graphs at runtime"""
    g: Graph[Any, Any, Any] = graph.directed()
    for operation in (g.bridges, g.articulation_points, g.biconnected_components):
        assert_graph_error(operation, "Cannot analyze undirected connectivity of directed graph")


# --- flow ---------------------------------------------------------------------------


def test_returns_fixed_flow_and_cut_results_in_data_first_and_data_last_forms() -> None:
    """returns fixed flow and cut results in data-first and data-last forms"""
    g = directed(["source", "target"], [(0, 1, 3)])
    flow = MaximumFlowResult(3, {0: 3}, (0,))
    cut = MinimumCutResult(3, (0,), (0,), (1,))
    assert g.maximum_flow(source=0, target=1, capacity=identity) == flow
    assert g.pipe(lambda x: x.maximum_flow(source=0, target=1, capacity=identity)) == flow
    assert g.minimum_cut(source=0, target=1, capacity=identity) == cut
    assert g.begin_mutation().minimum_cut(source=0, target=1, capacity=identity) == cut


def test_enforces_capacities_conservation_and_max_flow_min_cut_equality() -> None:
    """enforces capacities, conservation, and max-flow/min-cut equality"""
    capacities = [16, 13, 10, 4, 12, 9, 14, 7, 20, 4]
    endpoints = [(0, 1), (0, 2), (1, 2), (2, 1), (1, 3), (3, 2), (2, 4), (4, 3), (3, 5), (4, 5)]
    g = directed([None] * 6, [(s, t, capacities[i]) for i, (s, t) in enumerate(endpoints)])
    for candidate in (g, g.begin_mutation()):
        flow = candidate.maximum_flow(source=0, target=5, capacity=identity)
        cut = candidate.minimum_cut(source=0, target=5, capacity=identity)
        balance = [0.0] * 6
        for edge, (s, t) in enumerate(endpoints):
            value = flow.flows[edge]
            assert 0 <= value <= capacities[edge]
            balance[s] -= value
            balance[t] += value
        assert flow.value == 23
        assert cut.value == 23
        assert sum(capacities[edge] for edge in cut.edges) == 23
        assert balance == [-23, 0, 0, 0, 0, 23]
        assert sorted([*cut.source, *cut.target]) == [0, 1, 2, 3, 4, 5]


def test_uses_reverse_residual_edges_to_reroute_flow() -> None:
    """uses reverse residual edges to reroute flow"""
    g = directed(
        [None] * 6,
        [(0, 1, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1), (3, 5, 1), (1, 4, 1), (4, 5, 1)],
    )
    assert g.maximum_flow(source=0, target=5, capacity=identity).value == 2


def test_handles_parallel_edges_self_loops_fractions_and_disconnected_targets() -> None:
    """handles parallel edges, self-loops, fractions, and disconnected targets"""
    g = directed([None] * 4, [(0, 0, 100), (0, 1, 0), (0, 2, 0.75), (2, 1, 1), (0, 2, 0.25)])
    assert g.maximum_flow(source=0, target=1, capacity=identity) == MaximumFlowResult(
        1, {0: 0, 1: 0, 2: 0.75, 3: 1, 4: 0.25}, (1, 2, 4)
    )
    assert g.maximum_flow(source=0, target=3, capacity=identity) == MaximumFlowResult(
        0, {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}, ()
    )


def test_rejects_invalid_graphs_endpoints_capacities_and_finite_range_overflow() -> None:
    """rejects invalid graphs, endpoints, capacities, and finite-range overflow"""
    g = directed([None, None], list[EdgeSpec[float]]())
    assert_graph_error(
        lambda: g.maximum_flow(source=0, target=2, capacity=identity), "Node 2 does not exist"
    )
    assert_graph_error(
        lambda: g.maximum_flow(source=0, target=0, capacity=identity),
        "Flow source and target must be different nodes",
    )
    wrong_kind: Graph[Any, Any, Any] = graph.undirected()
    assert_graph_error(
        lambda: wrong_kind.maximum_flow(source=0, target=1, capacity=identity),
        "Cannot compute flow of undirected graph",
    )
    for capacity in [-1, math.nan, math.inf, -math.inf]:
        invalid = directed([None, None], [(0, 0, capacity)])
        assert_graph_error(
            lambda invalid=invalid: invalid.maximum_flow(source=0, target=1, capacity=identity),
            "Edge 0 capacity must be a finite non-negative number",
        )
    overflow = directed([None, None], [(0, 1, sys.float_info.max), (0, 1, sys.float_info.max)])
    assert_graph_error(
        lambda: overflow.maximum_flow(source=0, target=1, capacity=identity),
        "Maximum flow exceeds the finite number range",
    )


# --- spanning forests and reductions ------------------------------------------------


def test_preserves_sparse_indexes_isolated_nodes_and_fixed_mutable_parity_in_minimum_spanning_forests() -> (  # noqa: E501
    None
):
    """preserves sparse indexes, isolated nodes, and fixed mutable parity in minimum spanning forests"""  # noqa: E501
    nodes = [(2, "A"), (5, "B"), (9, "C"), (20, "isolated")]
    g = graph.from_snapshot(
        snapshot(
            "undirected",
            nodes,
            [(3, 2, 5, 4), (7, 2, 5, 1), (11, 5, 9, -2), (13, 2, 9, 2), (17, 9, 20, math.inf)],
        )
    )
    expected_edges = [(7, 2, 5, 1), (11, 5, 9, -2)]
    assert_snapshot(g.minimum_spanning_forest(identity), "undirected", nodes, expected_edges)
    assert_snapshot(
        g.begin_mutation().minimum_spanning_forest(identity), "undirected", nodes, expected_edges
    )


def test_breaks_equal_spanning_forest_weights_by_first_edge_order() -> None:
    """breaks equal spanning-forest weights by first edge order"""
    g = undirected([0, 1, 2], [(0, 1, 1), (1, 2, 1), (0, 2, 1)])
    forest = g.minimum_spanning_forest(identity)
    assert [edge.index for edge in forest.to_snapshot().edges] == [0, 1]


def test_preserves_sparse_reachability_and_first_parallel_edges_in_transitive_reductions() -> None:
    """preserves sparse reachability and first parallel edges in transitive reductions"""
    nodes = [(2, "A"), (5, "B"), (9, "C")]
    g = graph.from_snapshot(
        snapshot(
            "directed",
            nodes,
            [(3, 2, 5, "first"), (4, 2, 5, "parallel"), (7, 5, 9, "next"), (11, 2, 9, "redundant")],
        )
    )
    expected_edges = [(3, 2, 5, "first"), (7, 5, 9, "next")]
    assert_snapshot(g.transitive_reduction(), "directed", nodes, expected_edges)
    assert_snapshot(g.begin_mutation().transitive_reduction(), "directed", nodes, expected_edges)


def test_keeps_both_branches_of_a_diamond() -> None:
    """keeps both branches of a diamond"""
    g = directed([0, 1, 2, 3], [(0, 1, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1)])
    assert indices(g.transitive_reduction().edges()) == [0, 1, 2, 3]


def test_rejects_invalid_kinds_weights_and_cyclic_reductions() -> None:
    """rejects invalid kinds, weights, and cyclic reductions"""
    wrong_directed: Graph[Any, Any, Any] = graph.directed()
    assert_graph_error(
        lambda: wrong_directed.minimum_spanning_forest(lambda _: 1),
        "Cannot find minimum spanning forest of directed graph",
    )
    for weight in [math.nan, -math.inf]:
        g = undirected([0, 1], [(0, 1, weight)])
        assert_graph_error(
            lambda g=g: g.minimum_spanning_forest(identity),
            "Minimum spanning forest does not support NaN or -Infinity edge weights",
        )
    wrong_undirected: Graph[Any, Any, Any] = graph.undirected()
    assert_graph_error(
        wrong_undirected.transitive_reduction, "Cannot transitively reduce undirected graph"
    )
    assert_graph_error(
        directed([0, 1], [(0, 1, 1), (1, 0, 1)]).transitive_reduction,
        "Cannot transitively reduce cyclic graph",
    )


# --- pathfinding --------------------------------------------------------------------


def _paths_graph() -> Graph[str, int]:
    return directed(
        ["source", "first", "second", "target"], [(0, 1, 1), (0, 2, 1), (2, 3, 1), (1, 3, 1)]
    )


def zero(*_: object) -> float:
    return 0


def test_returns_complete_dijkstra_and_a_star_paths_with_deterministic_ties_and_fixed_mutable_parity() -> (  # noqa: E501
    None
):
    """returns complete Dijkstra and A* paths with deterministic ties and fixed mutable parity"""
    g = _paths_graph()
    expected = path([0, 1, 3], [0, 3], 2, [1, 1])
    for candidate in (g, g.begin_mutation()):
        assert candidate.dijkstra(source=0, target=3, cost=identity) == expected
        assert candidate.astar(source=0, target=3, cost=identity, heuristic=zero) == expected
    assert g.pipe(lambda x: x.dijkstra(source=0, target=3, cost=identity)) == expected
    assert g.bellman_ford(source=0, target=3, cost=identity) == path([0, 2, 3], [1, 2], 2, [1, 1])
    every = g.pipe(lambda x: x.floyd_warshall(identity))
    assert every.distances[0][3] == 2
    assert every.paths[0][3] == expected.path
    assert every.edges[0][3] == expected.edges
    assert every.costs[0][3] == expected.costs


def test_preserves_parallel_edges_for_topological_and_weighted_algorithms() -> None:
    """preserves parallel edges for topological and weighted algorithms"""
    g = directed([0, 1, 2], [(0, 1, 10), (0, 1, 1), (1, 2, 2)])
    assert indices(g.topo()) == [0, 1, 2]
    assert g.dijkstra(source=0, target=2, cost=identity) == path([0, 1, 2], [1, 2], 3, [1, 2])


def test_handles_decreased_dijkstra_priorities_with_fresh_order_and_stale_entries() -> None:
    """handles decreased Dijkstra priorities with fresh order and stale entries"""
    reordered = directed(
        ["source", "improved", "shortcut", "direct", "target"],
        [(0, 1, 10), (0, 2, 1), (0, 3, 2), (2, 1, 1), (1, 4, 1), (3, 4, 1)],
    )
    assert reordered.dijkstra(source=0, target=4, cost=identity) == path(
        [0, 3, 4], [2, 5], 3, [2, 1]
    )
    stale = _stale()
    assert stale.dijkstra(source=0, target=4, cost=identity) == path(
        [0, 2, 1, 3, 4], [1, 2, 3, 4], 42, [1, 1, 20, 20]
    )


def _stale() -> Graph[str, int]:
    return directed(
        ["source", "improved", "shortcut", "middle", "target"],
        [(0, 1, 10), (0, 2, 1), (2, 1, 1), (1, 3, 20), (3, 4, 20)],
    )


def test_skips_stale_a_star_entries_and_does_not_reopen_closed_nodes() -> None:
    """skips stale A* entries and does not reopen closed nodes"""
    assert _stale().astar(source=0, target=4, cost=identity, heuristic=zero) == path(
        [0, 2, 1, 3, 4], [1, 2, 3, 4], 42, [1, 1, 20, 20]
    )
    closed = directed(
        ["source", "closed", "later", "target"], [(0, 1, 10), (1, 3, 1), (0, 2, 1), (2, 1, 1)]
    )
    assert closed.astar(
        source=0,
        target=3,
        cost=identity,
        heuristic=lambda node, _: -100 if node == "closed" else 0,
    ) == path([0, 1, 3], [0, 1], 11, [10, 1])


def test_preserves_sparse_parallel_edge_identity_across_all_shortest_path_algorithms() -> None:
    """preserves sparse parallel edge identity across all shortest-path algorithms"""
    g = graph.from_snapshot(
        snapshot("directed", [(2, "source"), (5, "target")], [(3, 2, 5, 1), (1_000_000, 2, 5, 1)])
    )
    expected = path([2, 5], [3], 1, [1])
    for candidate in (g, g.begin_mutation()):
        assert candidate.dijkstra(source=2, target=5, cost=identity) == expected
        assert candidate.astar(source=2, target=5, cost=identity, heuristic=zero) == expected
        assert candidate.bellman_ford(source=2, target=5, cost=identity) == expected
        every = candidate.floyd_warshall(identity)
        assert every.distances[2][5] == 1
        assert every.paths[2][5] == (2, 5)
        assert every.edges[2][5] == (3,)
        assert every.costs[2][5] == (1,)


def test_handles_unreachable_and_same_node_paths_completely() -> None:
    """handles unreachable and same-node paths completely"""
    g = directed(["A", "B"], list[EdgeSpec[int]]())
    expected = path([0], list[int](), 0, list[int]())
    assert g.dijkstra(source=0, target=1, cost=identity) is None
    assert g.dijkstra(source=0, target=0, cost=identity) == expected
    assert g.astar(source=0, target=0, cost=identity, heuristic=zero) == expected
    assert g.bellman_ford(source=0, target=0, cost=identity) == expected
    every = g.floyd_warshall(identity)
    assert every.distances[0][1] == math.inf
    assert every.paths[0][1] is None
    assert every.edges[0][1] == ()
    assert every.costs[0][1] == ()
    assert every.distances[0][0] == 0
    assert every.paths[0][0] == (0,)
    assert every.edges[0][0] == ()
    assert every.costs[0][0] == ()


def test_uses_negative_bellman_ford_edges_in_shortest_paths() -> None:
    """uses negative Bellman-Ford edges in shortest paths"""
    g = directed([0, 1, 2], [(0, 1, -1), (1, 2, 3), (0, 2, 5)])
    assert g.bellman_ford(source=0, target=2, cost=identity) == path([0, 1, 2], [0, 1], 2, [-1, 3])


def test_ignores_negative_cycles_separated_from_the_bellman_ford_target_by_impassable_edges() -> (
    None
):
    """ignores negative cycles separated from the Bellman-Ford target by impassable edges"""
    g = directed([0, 1, 2, 3], [(0, 1, 1), (1, 2, -2), (2, 1, 1), (0, 3, 5), (2, 3, math.inf)])
    expected = path([0, 3], [3], 5, [5])
    assert g.bellman_ford(source=0, target=3, cost=identity) == expected
    assert g.begin_mutation().bellman_ford(source=0, target=3, cost=identity) == expected
    unreachable = directed([0, 1, 2, 3], [(0, 1, 1), (1, 2, -2), (2, 1, 1), (2, 3, math.inf)])
    assert unreachable.bellman_ford(source=0, target=3, cost=identity) is None


def test_detects_directed_and_undirected_negative_self_loops_when_source_equals_target() -> None:
    """detects directed and undirected negative self-loops when source equals target"""
    candidates: list[Graph[int, int, Any]] = [
        directed([0], [(0, 0, -1)]),
        undirected([0], [(0, 0, -1)]),
    ]
    for g in candidates:
        assert_graph_error(
            lambda g=g: g.bellman_ford(source=0, target=0, cost=identity),
            "Negative cycle affects path to node 0",
        )


def _zero_cost_cycle(cycle_weight: float, distance: float) -> None:
    g = directed([0, 1, 2], [(0, 1, cycle_weight), (1, 0, -cycle_weight), (0, 2, distance)])
    result = g.floyd_warshall(identity)
    assert result.paths[0][2] == (0, 2)
    assert result.edges[0][2] == (2,)
    assert result.costs[0][2] == (distance,)
    assert result.distances[0][2] == pytest.approx(distance, abs=1e-15)


def test_reconstructs_floyd_warshall_paths_with_integer_weights_on_a_zero_cost_cycle() -> None:
    """reconstructs Floyd-Warshall paths with integer weights on a zero-cost cycle"""
    _zero_cost_cycle(16, 1)


def test_reconstructs_floyd_warshall_paths_with_floating_point_weights_on_a_zero_cost_cycle() -> (
    None
):
    """reconstructs Floyd-Warshall paths with floating-point weights on a zero-cost cycle"""
    _zero_cost_cycle(0.1, 0.01)


def test_reconstructs_every_floyd_warshall_path_through_overlapping_zero_cost_cycles() -> None:
    """reconstructs every Floyd-Warshall path through overlapping zero-cost cycles"""
    connections: list[EdgeSpec[float]] = [
        (0, 1, 0.1),
        (1, 0, -0.1),
        (1, 2, -0.1),
        (2, 1, 0.1),
        (2, 3, 0.1),
        (3, 2, -0.1),
        (0, 4, 0.01),
        (4, 5, 0),
        (5, 0, 1),
    ]
    result = directed([0, 1, 2, 3, 4, 5], connections).floyd_warshall(identity)
    distances = [
        [0, 0.1, 0, 0.1, 0.01, 0.01],
        [-0.1, 0, -0.1, 0, -0.09, -0.09],
        [0, 0.1, 0, 0.1, 0.01, 0.01],
        [-0.1, 0, -0.1, 0, -0.09, -0.09],
        [1, 1.1, 1, 1.1, 0, 0],
        [1, 1.1, 1, 1.1, 1.01, 0],
    ]
    for source, target in itertools.product(range(6), range(6)):
        found = result.paths[source][target]
        assert found is not None
        edges = result.edges[source][target]
        costs = result.costs[source][target]
        assert found[0] == source
        assert found[-1] == target
        assert len(set(found)) == len(found)
        assert len(edges) == len(found) - 1
        assert len(costs) == len(edges)
        for i, edge in enumerate(edges):
            assert connections[edge] == (found[i], found[i + 1], costs[i])
        expected = distances[source][target]
        assert result.distances[source][target] == pytest.approx(expected, abs=1e-15)
        assert math.fsum(costs) == pytest.approx(expected, abs=1e-15)


def test_preserves_tiny_floyd_warshall_improvements() -> None:
    """preserves tiny Floyd-Warshall improvements"""
    g = directed([0, 1, 2], [(0, 2, 3e-20), (0, 1, 1e-20), (1, 2, 1e-20)])
    result = g.floyd_warshall(identity)
    assert result.distances[0][2] == 2e-20
    assert result.paths[0][2] == (0, 1, 2)
    assert result.edges[0][2] == (1, 2)
    assert result.costs[0][2] == (1e-20, 1e-20)


def test_detects_tiny_floyd_warshall_negative_cycles() -> None:
    """detects tiny Floyd-Warshall negative cycles"""
    g = directed([0, 1], [(0, 1, 1e-20), (1, 0, -2e-20)])
    assert_graph_error(
        lambda: g.floyd_warshall(identity), "Negative cycle detected involving node 0"
    )


@dataclass(frozen=True)
class Weight:
    weight: float


def test_preserves_null_edge_payloads_in_floyd_warshall_multihop_paths() -> None:
    """preserves null edge payloads in Floyd-Warshall multihop paths"""
    edges: list[EdgeSpec[Weight | None]] = [(0, 1, None), (1, 2, None), (0, 2, Weight(10))]
    g = directed(["A", "B", "C"], edges)
    result = g.floyd_warshall(lambda edge: 1 if edge is None else edge.weight)
    assert result.distances[0][2] == 2
    assert result.paths[0][2] == (0, 1, 2)
    assert result.edges[0][2] == (0, 1)
    assert result.costs[0][2] == (None, None)


def test_treats_positive_infinity_as_unreachable_in_every_shortest_path_algorithm() -> None:
    """treats positive Infinity as unreachable in every shortest-path algorithm"""
    g = directed([0, 1], [(0, 1, math.inf)])
    assert g.dijkstra(source=0, target=1, cost=identity) is None
    assert g.astar(source=0, target=1, cost=identity, heuristic=zero) is None
    assert g.bellman_ford(source=0, target=1, cost=identity) is None
    every = g.floyd_warshall(identity)
    assert every.distances[0][1] == math.inf
    assert every.paths[0][1] is None
    assert every.edges[0][1] == ()
    assert every.costs[0][1] == ()


def test_reports_relevant_bellman_ford_and_floyd_warshall_negative_cycles() -> None:
    """reports relevant Bellman-Ford and Floyd-Warshall negative cycles"""
    cycle = directed([0, 1, 2], [(0, 1, 1), (1, 2, -3), (2, 0, 1)])
    assert_graph_error(
        lambda: cycle.bellman_ford(source=0, target=2, cost=identity),
        "Negative cycle affects path to node 2",
    )
    assert_graph_error(
        lambda: cycle.floyd_warshall(identity), "Negative cycle detected involving node 0"
    )
    negative_undirected = undirected([0, 1], [(0, 1, -1)])
    assert_graph_error(
        lambda: negative_undirected.bellman_ford(source=0, target=1, cost=identity),
        "Negative cycle affects path to node 1",
    )


def test_validates_endpoints_edge_weights_heuristics_and_finite_arithmetic() -> None:
    """validates endpoints, edge weights, heuristics, and finite arithmetic"""
    assert_graph_error(
        lambda: graph.directed().dijkstra(source=0, target=1, cost=lambda _: 1),
        "Node 0 does not exist",
    )
    for weight in [-1, math.nan, -math.inf]:
        invalid = directed([0, 1], [(0, 1, weight)])
        assert_graph_error(
            lambda invalid=invalid: invalid.dijkstra(source=0, target=1, cost=identity),
            "Dijkstra's algorithm requires non-negative edge weights",
        )
        assert_graph_error(
            lambda invalid=invalid: invalid.astar(
                source=0, target=1, cost=identity, heuristic=zero
            ),
            "A* algorithm requires non-negative edge weights",
        )
    for heuristic in [math.nan, math.inf, -math.inf]:
        single = directed(["A"], list[EdgeSpec[int]]())
        assert_graph_error(
            lambda single=single, h=heuristic: single.astar(
                source=0, target=0, cost=lambda _: 1, heuristic=lambda _n, _t: h
            ),
            "A* algorithm requires finite heuristic values",
        )
        line = directed(["source", "middle", "target"], [(0, 1, 1), (1, 2, 1)])
        assert_graph_error(
            lambda line=line, h=heuristic: line.astar(
                source=0,
                target=2,
                cost=identity,
                heuristic=lambda node, _: h if node == "middle" else 0,
            ),
            "A* algorithm requires finite heuristic values",
        )
    for weight in [math.nan, -math.inf]:
        invalid = directed([0, 1], [(0, 1, weight)])
        assert_graph_error(
            lambda invalid=invalid: invalid.bellman_ford(source=0, target=1, cost=identity),
            "Bellman-Ford algorithm does not support NaN or -Infinity edge weights",
        )
        assert_graph_error(
            lambda invalid=invalid: invalid.floyd_warshall(identity),
            "Floyd-Warshall algorithm does not support NaN or -Infinity edge weights",
        )
    big = sys.float_info.max
    overflow = directed([0, 1, 2], [(0, 1, big), (1, 2, big)])
    assert_graph_error(
        lambda: overflow.dijkstra(source=0, target=2, cost=identity),
        "Dijkstra distance calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: overflow.astar(source=0, target=2, cost=identity, heuristic=zero),
        "A* distance calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: directed([0, 1], [(0, 1, big)]).astar(
            source=0, target=1, cost=identity, heuristic=lambda node, _: big if node == 1 else 0
        ),
        "A* priority calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: overflow.bellman_ford(source=0, target=2, cost=identity),
        "Bellman-Ford distance calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: overflow.floyd_warshall(identity),
        "Floyd-Warshall distance calculation exceeded the finite number range",
    )
    underflow = directed([0, 1, 2], [(0, 1, -big), (1, 2, -big)])
    assert_graph_error(
        lambda: underflow.bellman_ford(source=0, target=2, cost=identity),
        "Bellman-Ford distance calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: underflow.floyd_warshall(identity),
        "Floyd-Warshall distance calculation exceeded the finite number range",
    )


def test_validates_negative_dijkstra_and_a_star_weights_before_early_returns() -> None:
    """validates negative Dijkstra and A* weights before early returns"""
    early = directed([0, 1, 2], [(0, 1, 1), (0, 2, 2), (2, 1, -5)])
    same = directed([0], [(0, 0, -1)])
    for g, source, target in ((early, 0, 1), (same, 0, 0)):
        assert_graph_error(
            lambda g=g, s=source, t=target: g.dijkstra(source=s, target=t, cost=identity),
            "Dijkstra's algorithm requires non-negative edge weights",
        )
        assert_graph_error(
            lambda g=g, s=source, t=target: g.astar(
                source=s, target=t, cost=identity, heuristic=zero
            ),
            "A* algorithm requires non-negative edge weights",
        )


def test_traverses_undirected_edges_against_stored_orientation() -> None:
    """traverses undirected edges against stored orientation"""
    g = undirected(["A", "B", "C"], [(0, 1, 1), (2, 1, 1)])
    expected = path([0, 1, 2], [0, 1], 2, [1, 1])
    assert g.dijkstra(source=0, target=2, cost=identity) == expected
    assert g.astar(source=0, target=2, cost=identity, heuristic=zero) == expected
    assert g.bellman_ford(source=0, target=2, cost=identity) == expected
    every = g.floyd_warshall(identity)
    assert every.distances[0][2] == 2
    assert every.paths[0][2] == (0, 1, 2)
    assert every.edges[0][2] == (0, 1)
    assert every.costs[0][2] == (1, 1)


# --- path enumeration ---------------------------------------------------------------


def test_lazily_and_repeatably_enumerates_complete_simple_paths_in_edge_order() -> None:
    """lazily and repeatably enumerates complete simple paths in edge order"""
    g = directed(
        [0, 1, 2, 3],
        [(0, 1, "01"), (0, 2, "02"), (1, 2, "12"), (1, 3, "13"), (2, 3, "23"), (2, 1, "21")],
    )
    paths = g.simple_paths(source=0, target=3, limit=3)
    expected = [
        path([0, 1, 2, 3], [0, 2, 4], 3, ["01", "12", "23"]),
        path([0, 1, 3], [0, 3], 2, ["01", "13"]),
        path([0, 2, 3], [1, 4], 2, ["02", "23"]),
    ]
    assert list(paths) == expected
    assert list(paths) == expected
    assert list(g.pipe(lambda x: x.simple_paths(source=0, target=3, limit=3))) == expected


def test_enumerates_parallel_and_structurally_tied_shortest_paths_exactly() -> None:
    """enumerates parallel and structurally tied shortest paths exactly"""
    g = directed([0, 1, 2, 3], [(0, 1, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1), (0, 1, 1)])
    expected = [
        path([0, 1, 3], [0, 2], 2, [1, 1]),
        path([0, 1, 3], [4, 2], 2, [1, 1]),
        path([0, 2, 3], [1, 3], 2, [1, 1]),
    ]
    assert list(g.all_shortest_paths(source=0, target=3, cost=identity)) == expected
    assert list(g.pipe(lambda x: x.all_shortest_paths(source=0, target=3, cost=identity))) == (
        expected
    )
    limited = g.begin_mutation().all_shortest_paths(source=0, target=3, cost=identity, limit=2)
    assert list(limited) == expected[:2]


def test_terminates_zero_cost_predecessor_cycles_and_emits_only_simple_shortest_paths() -> None:
    """terminates zero-cost predecessor cycles and emits only simple shortest paths"""
    g = directed([0, 1, 2, 3], [(0, 1, 0), (1, 2, 0), (2, 1, 0), (1, 3, 1), (2, 3, 1)])
    assert list(g.all_shortest_paths(source=0, target=3, cost=identity)) == [
        path([0, 1, 3], [0, 3], 1, [0, 1]),
        path([0, 1, 2, 3], [0, 1, 4], 1, [0, 0, 1]),
    ]


def test_defers_shortest_path_cost_evaluation_until_iteration() -> None:
    """defers shortest-path cost evaluation until iteration"""
    calls: list[int] = []

    def cost(edge: int) -> int:
        calls.append(edge)
        return edge

    paths = directed([0, 1], [(0, 1, 1)]).all_shortest_paths(source=0, target=1, cost=cost)
    assert calls == []
    assert list(paths) == [path([0, 1], [0], 1, [1])]
    assert len(calls) == 1


def test_revalidates_mutable_endpoints_and_isolates_active_snapshots() -> None:
    """revalidates mutable endpoints and isolates active snapshots"""
    removed = directed([0, 1], [(0, 1, 1)]).begin_mutation()
    pending = removed.simple_paths(source=0, target=1)
    removed.remove_node(0)
    assert_graph_error(lambda: list(pending), "Node 0 does not exist")

    shortest_removed = directed([0, 1], [(0, 1, 1)]).begin_mutation()
    shortest_pending = shortest_removed.all_shortest_paths(source=0, target=1, cost=identity)
    shortest_removed.remove_node(1)
    assert_graph_error(lambda: list(shortest_pending), "Node 1 does not exist")

    first = path([0, 1, 3], [0, 2], 2, [1, 1])
    second = path([0, 2, 3], [1, 3], 2, [1, 1])
    diamond = [(0, 1, 1), (0, 2, 1), (1, 3, 1), (2, 3, 1)]

    mutable = directed([0, 1, 2, 3], diamond).begin_mutation()
    paths = mutable.simple_paths(source=0, target=3)
    iterator = iter(paths)
    assert next(iterator) == first
    mutable.remove_edge(1)
    assert next(iterator) == second
    assert list(paths) == [first]

    shortest_mutable = directed([0, 1, 2, 3], diamond).begin_mutation()
    shortest = shortest_mutable.all_shortest_paths(source=0, target=3, cost=identity)
    shortest_iterator = iter(shortest)
    assert next(shortest_iterator) == first
    shortest_mutable.remove_edge(1)
    assert next(shortest_iterator) == second
    assert list(shortest) == [first]


def test_handles_empty_path_enumerations() -> None:
    """handles empty path enumerations"""
    g = directed(["A", "B"], list[EdgeSpec[int]]())
    same = [path([0], list[int](), 0, list[int]())]
    assert list(g.simple_paths(source=0, target=0)) == same
    assert list(g.all_shortest_paths(source=0, target=0, cost=identity)) == same
    assert list(g.all_shortest_paths(source=0, target=1, cost=identity)) == []


def test_validates_limits_endpoints_and_non_negative_shortest_path_costs() -> None:
    """validates limits, endpoints, and non-negative shortest-path costs"""
    g = directed([0, 1], [(0, 1, -1)])
    assert_graph_error(
        lambda: list(g.all_shortest_paths(source=0, target=1, cost=identity)),
        "All shortest paths requires non-negative edge weights",
    )
    assert_graph_error(
        lambda: list(g.all_shortest_paths(source=0, target=1, cost=identity, limit=0)),
        "All shortest paths requires non-negative edge weights",
    )
    big = sys.float_info.max
    overflow = directed([0, 1, 2], [(0, 1, big), (1, 2, big)])
    assert_graph_error(
        lambda: list(overflow.all_shortest_paths(source=0, target=2, cost=identity)),
        "All shortest paths distance calculation exceeded the finite number range",
    )
    assert_graph_error(
        lambda: g.simple_paths(source=0, target=1, limit=-1),
        "Path enumeration limit must be a non-negative integer or Infinity",
    )
    assert_graph_error(lambda: g.simple_paths(source=0, target=2), "Node 2 does not exist")
    assert list(g.simple_paths(source=0, target=1, limit=0)) == []


# --- traversal ----------------------------------------------------------------------


def _traversal_graph() -> Graph[str, int]:
    return directed(["A", "B", "C", "D"], [(0, 1, 1), (0, 2, 2), (1, 3, 3), (2, 3, 4)])


def test_traverses_dfs_bfs_and_postorder_in_documented_order() -> None:
    """traverses DFS, BFS, and postorder in documented order"""
    g = _traversal_graph()
    assert indices(g.dfs(start=[0])) == [0, 1, 3, 2]
    assert indices(g.bfs(start=[0])) == [0, 1, 2, 3]
    assert indices(g.dfs_post_order(start=[0])) == [3, 1, 2, 0]
    assert indices(g.dfs()) == []


def test_preserves_postorder_with_parallel_edges_self_loops_and_directionless_traversal() -> None:
    """preserves postorder with parallel edges, self-loops, and directionless traversal"""
    parallel = directed(
        [0, 1, 2, 3, 4],
        [(0, 1, 1), (0, 1, 2), (0, 1, 3), (1, 2, 4), (1, 3, 5), (1, 4, 6), (1, 1, 7)],
    )
    assert indices(parallel.dfs_post_order(start=[0])) == [2, 3, 4, 1, 0]
    assert indices(parallel.dfs_post_order(start=[0, 1])) == [2, 3, 4, 1, 0]
    directionless = directed([0, 1, 2, 3], [(0, 1, 1), (2, 1, 2), (1, 3, 3), (1, 1, 4)])
    assert indices(directionless.dfs_post_order(start=[1], direction="undirected")) == [3, 0, 2, 1]


def test_uses_shortest_distance_for_radius_membership_and_supports_traversal_directions() -> None:
    """uses shortest distance for radius membership and supports traversal directions"""
    g = directed([0, 1, 2, 3], [(0, 1, 1), (1, 2, 1), (0, 2, 1), (2, 3, 1)])
    assert indices(g.dfs(start=[0], radius=2)) == [0, 1, 2, 3]
    assert indices(g.bfs(start=[2], direction="incoming")) == [2, 1, 0]
    assert indices(g.dfs_post_order(start=[2], direction="incoming")) == [0, 1, 2]
    assert indices(g.bfs(start=[1], direction="undirected", radius=1)) == [1, 2, 0]
    line = directed([0, 1, 2], [(0, 1, 1), (1, 2, 1)])
    assert indices(line.dfs_post_order(start=[0], radius=1)) == [1, 0]


def test_preserves_bounded_undirected_dfs_order_for_reciprocal_neighbors() -> None:
    """preserves bounded undirected DFS order for reciprocal neighbors"""
    g = directed([None] * 5, [(0, 1, 1), (4, 1, 2), (1, 4, 3)])
    assert indices(g.dfs(start=[1], direction="undirected", radius=2)) == [1, 4, 0]


def test_validates_radius_in_data_first_and_data_last_forms() -> None:
    """validates radius in data-first and data-last forms"""
    g = _traversal_graph()
    for radius in [math.nan, -math.inf, -1, 0.5]:
        runs: list[Callable[[], object]] = [
            lambda r=radius: g.dfs(start=[0], radius=r),
            lambda r=radius: g.pipe(lambda x: x.bfs(start=[0], radius=r)),
            lambda r=radius: g.dfs_post_order(start=[0], radius=r),
        ]
        for run in runs:
            assert_graph_error(run, "Traversal radius must be a non-negative integer or Infinity")


def test_copies_starts_prioritizes_distinct_roots_and_preserves_sparse_indexes() -> None:
    """copies starts, prioritizes distinct roots, and preserves sparse indexes"""
    g = _traversal_graph()
    start = [0]
    walkers = [g.dfs(start=start), g.bfs(start=start), g.dfs_post_order(start=start)]
    start[0] = 3
    assert indices(walkers[0]) == [0, 1, 3, 2]
    assert indices(walkers[1]) == [0, 1, 2, 3]
    assert indices(walkers[2]) == [3, 1, 2, 0]
    assert indices(g.bfs(start=[0, 0, 2, 2])) == [0, 2, 1, 3]

    sparse = graph.from_snapshot(
        snapshot(
            "directed",
            [(2, "A"), (5, "B"), (1_000_000, "C")],
            [(3, 2, 5, 1), (1_000_000, 5, 1_000_000, 2)],
        )
    )
    assert indices(sparse.bfs(start=[2])) == [2, 5, 1_000_000]
    assert indices(sparse.dfs_post_order(start=[2])) == [1_000_000, 5, 2]


def test_revalidates_missing_starts_for_fresh_dfs_bfs_and_postorder_iterators() -> None:
    """revalidates missing starts for fresh DFS, BFS, and postorder iterators"""
    mutable = directed([0, 1], [(0, 1, 1)]).begin_mutation()
    walkers = [
        mutable.dfs(start=[0]).indices(),
        mutable.bfs(start=[0]).indices(),
        mutable.dfs_post_order(start=[0]).indices(),
    ]
    mutable.remove_node(0)
    for walker in walkers:
        assert_graph_error(lambda walker=walker: iter(walker), "Node 0 does not exist")


def test_isolates_active_mutable_traversal_snapshots_while_fresh_iterators_see_mutations() -> None:
    """isolates active mutable traversal snapshots while fresh iterators see mutations"""
    mutable = directed(["A", "B", "C"], [(0, 1, 1), (1, 2, 2)]).begin_mutation()
    walkers = [
        mutable.dfs(start=[0]).indices(),
        mutable.bfs(start=[0]).indices(),
        mutable.dfs_post_order(start=[0]).indices(),
    ]
    active = [iter(walker) for walker in walkers]
    mutable.remove_node(1)
    assert list(active[0]) == [0, 1, 2]
    assert list(active[1]) == [0, 1, 2]
    assert list(active[2]) == [2, 1, 0]
    for walker in walkers:
        assert list(walker) == [0]


def test_topologically_sorts_with_prioritized_initials_and_validates_fresh_mutable_state() -> None:
    """topologically sorts with prioritized initials and validates fresh mutable state"""
    g = directed(["A", "B", "C", "D"], [(0, 1, 1), (2, 3, 1)])
    assert indices(g.topo(initials=[2])) == [2, 0, 3, 1]

    mutable = directed(["A", "B"], list[EdgeSpec[int]]()).begin_mutation()
    walker = mutable.topo()
    assert indices(walker) == [0, 1]
    mutable.add_edge(0, 1, 1)
    mutable.add_edge(1, 0, 2)
    assert_graph_error(
        lambda: list(walker.indices()), "Cannot perform topological sort on cyclic graph"
    )


def test_isolates_active_mutable_topological_snapshots_while_fresh_iterators_see_mutations() -> (
    None
):
    """isolates active mutable topological snapshots while fresh iterators see mutations"""
    mutable = directed([0, 1, 2], [(0, 1, 1), (1, 2, 1)]).begin_mutation()
    walker = mutable.topo().indices()
    active = iter(walker)
    mutable.remove_node(1)
    assert list(active) == [0, 1, 2]
    assert list(walker) == [0, 2]


def test_rejects_invalid_topological_graphs_and_initials() -> None:
    """rejects invalid topological graphs and initials"""
    wrong_kind: Graph[Any, Any, Any] = graph.undirected()
    assert_graph_error(wrong_kind.topo, "Cannot perform topological sort on undirected graph")
    assert_graph_error(
        directed([0, 1], [(0, 1, 1), (1, 0, 1)]).topo,
        "Cannot perform topological sort on cyclic graph",
    )
    g = directed([0, 1], [(0, 1, 1)])
    assert_graph_error(lambda: list(g.topo(initials=[1])), "Initial node 1 has incoming edges")
    assert_graph_error(lambda: g.topo(initials=[2]), "Node 2 does not exist")


def test_keeps_nodes_edges_and_externals_live_on_mutable_graphs() -> None:
    """keeps nodes, edges, and externals live on mutable graphs"""
    mutable = directed(["A", "B"], [(0, 1, 1)]).begin_mutation()
    nodes = iter(mutable.nodes().indices())
    edges = iter(mutable.edges().indices())
    externals = iter(mutable.externals().indices())
    assert next(nodes) == 0
    assert next(edges) == 0
    assert next(externals) == 1
    mutable.add_node("C")
    mutable.add_edge(1, 2, 2)
    assert list(nodes) == [1, 2]
    assert list(edges) == [1]
    assert list(externals) == [2]


def test_selects_outgoing_sinks_and_incoming_sources() -> None:
    """selects outgoing sinks and incoming sources"""
    g = directed(["source", "middle", "sink", "isolated"], [(0, 1, 1), (1, 2, 2)])
    assert indices(g.externals()) == [2, 3]
    assert indices(g.externals(direction="outgoing")) == [2, 3]
    assert indices(g.externals(direction="incoming")) == [0, 3]


# --- Walker -------------------------------------------------------------------------


class _Two:
    """A visit over two fixed ``(index, data)`` pairs, made fresh on each call."""

    def __init__(self, first: tuple[int, str], second: tuple[int, str]) -> None:
        self.pairs = (first, second)

    def __call__[U](self, f: Callable[[int, str], U], /) -> Iterator[U]:
        for index, data in self.pairs:
            yield f(index, data)


def test_projects_representative_walkers_through_indices_values_entries_and_visit() -> None:
    """projects representative walkers through indices, values, entries, and visit"""
    walker = Walker[int, str](_Two((2, "A"), (5, "B")))
    assert list(walker.indices()) == [2, 5]
    assert list(walker.values()) == ["A", "B"]
    assert list(walker.entries()) == [(2, "A"), (5, "B")]
    assert list(walker.visit(lambda index, value: f"{index}:{value}")) == ["2:A", "5:B"]


def test_is_repeatable_and_gives_independent_iterators_fresh_state() -> None:
    """is repeatable and gives independent iterators fresh state"""
    walker = Walker[int, str](_Two((0, "A"), (1, "B")))
    assert list(walker) == [(0, "A"), (1, "B")]
    assert list(walker) == [(0, "A"), (1, "B")]
    left, right = iter(walker), iter(walker)
    assert next(left) == (0, "A")
    assert next(right) == (0, "A")
    assert next(left) == (1, "B")
    assert next(right) == (1, "B")


def test_preserves_receivers_supplied_by_iterable_iterator_methods() -> None:
    """preserves receivers supplied by iterable iterator methods

    Effect's visit returns a ``Set``, whose iterator method needs its own
    receiver; a Python visit may return any iterable (here a tuple)."""

    class Pair:
        def __call__[U](self, f: Callable[[int, str], U], /) -> Iterable[U]:
            return (f(0, "A"), f(1, "B"))

    assert list(Walker[int, str](Pair())) == [(0, "A"), (1, "B")]
