"""Ports of Effect's ``schema/Graph.test.ts`` (``Schema.Graph``).
Each test's docstring is the Effect test title.

Python mappings: ``Arbitrary.sampleEffect`` is Hypothesis drawing from
``S.to_strategy``; ``Graph.edges(g)`` entries are ``(index, Edge)``; an
encoded graph is a ``dict`` with tuples of records (``S.to_codec_json``
writes JSON arrays as tuples, which compare equal to Effect's arrays here
once turned into lists).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, cast

import pytest
from hypothesis import HealthCheck, given, settings

from pyfect import graph
from pyfect import schema as S

directed_codec = S.to_codec_json(S.Graph("directed", S.String, S.Number))
undirected_codec = S.to_codec_json(S.Graph("undirected", S.String, S.Number))
decode_directed = S.decode_unknown_sync(directed_codec)
encode_directed = S.encode_sync(directed_codec)


def plain(value: object) -> Any:
    """``value`` with tuples as lists, as JSON reads it."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in cast("dict[str, object]", value).items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in cast("Sequence[object]", value)]
    return value


def empty(kind: str) -> dict[str, Any]:
    return {"type": kind, "nodes": [], "edges": []}


def assert_decode_failure(input: object, path: str, message: str | None = None) -> None:
    with pytest.raises(Exception) as error:
        decode_directed(input)
    formatted = str(error.value)
    assert path in formatted
    if message is not None:
        assert message in formatted


def sample(schema: S.Top, count: int) -> list[Any]:
    values: list[Any] = []

    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(S.to_strategy(schema))
    def collect(value: object) -> None:
        values.append(value)

    collect()
    return values


@pytest.mark.parametrize("kind", ["directed", "undirected"])
def test_derives_productive_arbitrary_graphs(kind: Literal["directed", "undirected"]):
    """derives productive arbitrary graphs"""
    schema = S.Graph(kind, S.String, S.Number)
    values = sample(schema, 100)
    assert all(map(S.is_(schema), values))
    assert any(len(list(g)) > 0 for g in values)
    assert any(len(list(g.edges())) > 0 for g in values)


def test_derives_recursive_graph_payloads():
    """derives recursive graph payloads"""
    recursive: S.Bottom[Any] = S.suspend(lambda: S.Graph("directed", recursive, S.Null))
    values = sample(recursive, 30)
    assert all(map(S.is_(recursive), values))
    assert any(len(list(g)) > 0 for g in values)


def test_derives_active_structure_equivalence_from_payload_schemas():
    """derives active-structure equivalence from payload schemas"""

    def same_parity(a: float, b: float) -> bool:
        return a % 2 == b % 2

    def parity(_: object) -> Callable[[float, float], bool]:
        return same_parity

    modulo = S.Number.annotate(to_equivalence=parity)
    equivalence = S.to_equivalence(S.Graph("directed", modulo, modulo))

    def build(first: int) -> graph.Graph[int, int]:
        def add(m: graph.MutableGraph[int, int]) -> None:
            a = m.add_node(first)
            b = m.add_node(first + 1)
            m.add_edge(a, b, first + 2)

        return graph.directed(add)

    assert equivalence(build(0), build(2)) is True

    undirected_equivalence = S.to_equivalence(S.Graph("undirected", S.Number, S.Number))

    def edge(source: int, target: int) -> graph.Graph[int, int, Literal["undirected"]]:
        def add(m: graph.MutableGraph[int, int, Literal["undirected"]]) -> None:
            m.add_node(0)
            m.add_node(1)
            m.add_edge(source, target, 2)

        return graph.undirected(add)

    assert undirected_equivalence(edge(0, 1), edge(1, 0)) is True


def test_encodes_and_decodes_empty_directed_and_undirected_graphs():
    """encodes and decodes empty directed and undirected graphs"""
    assert plain(encode_directed(graph.directed())) == empty("directed")
    assert plain(S.encode_sync(undirected_codec)(graph.undirected())) == empty("undirected")
    assert decode_directed(empty("directed")).type == "directed"
    assert S.decode_unknown_sync(undirected_codec)(empty("undirected")).type == "undirected"


def test_preserves_indexed_directed_structure():
    """preserves indexed directed structure, isolated nodes, loops, parallel edges, and gaps"""

    def build(m: graph.MutableGraph[str, int]) -> None:
        removed = m.add_node("removed")
        source = m.add_node("source")
        target = m.add_node("target")
        m.add_node("isolated")
        m.remove_node(removed)
        removed_edge = m.add_edge(source, target, -1)
        m.add_edge(source, source, 1)
        m.add_edge(source, target, 2)
        m.add_edge(source, target, 3)
        m.remove_edge(removed_edge)

    encoded: dict[str, Any] = {
        "type": "directed",
        "nodes": [
            {"index": 1, "data": "source"},
            {"index": 2, "data": "target"},
            {"index": 3, "data": "isolated"},
        ],
        "edges": [
            {"index": 1, "source": 1, "target": 1, "data": 1},
            {"index": 2, "source": 1, "target": 2, "data": 2},
            {"index": 3, "source": 1, "target": 2, "data": 3},
        ],
    }
    assert plain(encode_directed(graph.directed(build))) == encoded
    decoded = decode_directed(encoded)
    assert list(decoded) == [(n["index"], n["data"]) for n in encoded["nodes"]]
    assert [
        {"index": i, "source": e.source, "target": e.target, "data": e.data}
        for i, e in decoded.edges()
    ] == encoded["edges"]
    assert plain(encode_directed(decoded)) == encoded


def test_preserves_stored_orientation_for_undirected_edges():
    """preserves stored orientation for undirected edges"""

    def build(m: graph.MutableGraph[str, int, Literal["undirected"]]) -> None:
        a = m.add_node("A")
        b = m.add_node("B")
        m.add_edge(b, a, 1)

    encode = S.encode_sync(undirected_codec)
    encoded = plain(encode(graph.undirected(build)))
    assert encoded == {
        "type": "undirected",
        "nodes": [{"index": 0, "data": "A"}, {"index": 1, "data": "B"}],
        "edges": [{"index": 0, "source": 1, "target": 0, "data": 1}],
    }
    assert plain(encode(S.decode_unknown_sync(undirected_codec)(encoded))) == encoded


def test_starts_a_new_allocation_lineage_after_the_highest_active_indexes():
    """starts a new allocation lineage after the highest active indexes"""
    decoded = decode_directed(
        {
            "type": "directed",
            "nodes": [{"index": 2, "data": "A"}, {"index": 5, "data": "B"}],
            "edges": [{"index": 4, "source": 2, "target": 5, "data": 1}],
        }
    )
    added: list[int] = []

    def add(m: graph.MutableGraph[str, float]) -> None:
        node = m.add_node("C")
        added.extend((node, m.add_edge(5, node, 2)))

    decoded.mutate(add)
    assert added == [6, 5]


def test_does_not_serialize_removed_trailing_allocation_history():
    """does not serialize removed trailing allocation history"""

    def build(m: graph.MutableGraph[str, int]) -> None:
        a = m.add_node("A")
        b = m.add_node("B")
        trailing = m.add_node("removed")
        active = m.add_edge(a, b, 1)
        removed = m.add_edge(a, b, 2)
        m.remove_edge(removed)
        m.remove_node(trailing)
        assert active == 0

    decoded = decode_directed(encode_directed(graph.directed(build)))
    added: list[int] = []

    def add(m: graph.MutableGraph[str, float]) -> None:
        added.extend((m.add_node("next"), m.add_edge(0, 1, 3)))

    decoded.mutate(add)
    assert added == [2, 1]


def test_rebuilds_adjacency_and_initializes_derived_caches_for_cyclic_graphs():
    """rebuilds adjacency and initializes derived caches for cyclic graphs"""
    g = decode_directed(
        {
            "type": "directed",
            "nodes": [
                {"index": 0, "data": "A"},
                {"index": 2, "data": "B"},
                {"index": 4, "data": "C"},
            ],
            "edges": [
                {"index": 1, "source": 0, "target": 2, "data": 1},
                {"index": 3, "source": 2, "target": 4, "data": 2},
                {"index": 5, "source": 4, "target": 0, "data": 3},
            ],
        }
    )
    assert list(g.neighbors(0)) == [2]
    assert list(g.predecessors(0)) == [4]
    assert g.is_acyclic() is False


def test_applies_node_and_edge_payload_transformations():
    """applies node and edge payload transformations"""
    codec = S.to_codec_json(S.Graph("directed", S.FiniteFromString, S.FiniteFromString))
    encoded = {
        "type": "directed",
        "nodes": [{"index": 0, "data": "1"}, {"index": 1, "data": "2"}],
        "edges": [{"index": 0, "source": 0, "target": 1, "data": "3"}],
    }
    g = S.decode_unknown_sync(codec)(encoded)
    assert list(g) == [(0, 1), (1, 2)]
    assert g.get_edge(0) == graph.Edge(0, 1, 3)
    assert plain(S.encode_sync(codec)(g)) == encoded


def test_rejects_mutable_graphs_and_the_wrong_graph_kind():
    """rejects mutable graphs and the wrong graph kind"""
    mutable: Any = graph.directed().begin_mutation()
    with pytest.raises(Exception, match="immutable directed Graph"):
        encode_directed(mutable)
    wrong: Any = graph.undirected()
    with pytest.raises(Exception, match="immutable directed Graph"):
        encode_directed(wrong)
    assert_decode_failure(empty("undirected"), '["type"]', 'Expected "directed"')


@pytest.mark.parametrize("index", [-1, 0.5, 2**53])
def test_rejects_invalid_node_and_edge_indexes_at_precise_paths(index: float):
    """rejects invalid node and edge indexes at precise paths"""
    assert_decode_failure(
        {"type": "directed", "nodes": [{"index": index, "data": "A"}], "edges": []},
        '["nodes"][0]["index"]',
    )
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": 0, "data": "A"}],
            "edges": [{"index": index, "source": 0, "target": 0, "data": 1}],
        },
        '["edges"][0]["index"]',
    )


@pytest.mark.parametrize(("first", "second"), [(0, 0), (1, 0)])
def test_rejects_indexes_that_do_not_increase(first: int, second: int):
    """rejects invalid node and edge indexes at precise paths"""
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": first, "data": "A"}, {"index": second, "data": "B"}],
            "edges": [],
        },
        '["nodes"][1]["index"]',
        "strictly increasing",
    )
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": 0, "data": "A"}],
            "edges": [
                {"index": first + 1, "source": 0, "target": 0, "data": 1},
                {"index": second + 1, "source": 0, "target": 0, "data": 2},
            ],
        },
        '["edges"][1]["index"]',
        "strictly increasing",
    )


def test_rejects_dangling_endpoints_without_leaking_graph_error():
    """rejects dangling endpoints without leaking GraphError"""
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": 1, "data": "A"}],
            "edges": [{"index": 0, "source": 0, "target": 1, "data": 1}],
        },
        '["edges"][0]["source"]',
        "encoded node index",
    )
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": 1, "data": "A"}],
            "edges": [{"index": 0, "source": 1, "target": 2, "data": 1}],
        },
        '["edges"][0]["target"]',
        "encoded node index",
    )


def test_reports_payload_failures_at_array_and_property_paths():
    """reports payload failures at array and property paths"""
    assert_decode_failure(
        {"type": "directed", "nodes": [{"index": 0, "data": None}], "edges": []},
        '["nodes"][0]["data"]',
        "Expected string",
    )
    assert_decode_failure(
        {
            "type": "directed",
            "nodes": [{"index": 0, "data": "A"}],
            "edges": [{"index": 0, "source": 0, "target": 0, "data": None}],
        },
        '["edges"][0]["data"]',
        "Expected number",
    )
