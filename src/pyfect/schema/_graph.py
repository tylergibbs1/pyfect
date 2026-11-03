"""``Graph``: Effect's ``Schema.Graph``, immutable ``pyfect.graph`` graphs
of one kind whose node and edge payloads are schemas' values.

A graph is parsed as its snapshot, ``{"type", "nodes": [{"index",
"data"}], "edges": [{"index", "source", "target", "data"}]}``, so a
payload's issue is at ``["nodes"][i]["data"]``. JSON writes that snapshot;
decoding checks that indexes strictly increase and that every endpoint is
an encoded node, at the offending path, before the graph is built.
Removed-index history is not kept: new indexes start after the highest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from pyfect import graph as _graph
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.graph import IndexedEdge, IndexedNode, Kind, Snapshot
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_number import is_less_than_or_equal_to
from pyfect.schema._checks_size import is_min_length
from pyfect.schema._options import ParseOptions
from pyfect.schema._primitives import Natural
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._to_equivalence import Equivalence
from pyfect.schema.issue import InvalidValue, Issue, Pointer, reported

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
N_co = TypeVar("N_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
NI_co = TypeVar("NI_co", covariant=True)
EI_co = TypeVar("EI_co", covariant=True)
K_co = TypeVar("K_co", bound=Kind, covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type _Encoded = Mapping[str, Any]
type _AnyGraph = _graph.Graph[Any, Any, Kind]

_INDEX = ast.append_checks(Natural.ast, (is_less_than_or_equal_to(2**53 - 1),))
"""A node or edge index: a non-negative safe integer (Effect's ``Natural``)."""


@dataclass(frozen=True, slots=True, eq=False)
class GraphSchema(
    Bottom[_graph.Graph[N_co, E_co, K_co], _graph.Graph[NI_co, EI_co, K_co], RD_co, RE_co],
    Generic[N_co, E_co, NI_co, EI_co, K_co, RD_co, RE_co],
):
    """Immutable ``kind`` graphs of ``node`` and ``edge`` payloads."""

    kind: K_co
    node: Codec[N_co, NI_co, RD_co, RE_co]
    edge: Codec[E_co, EI_co, RD_co, RE_co]


def _encoded_schema(kind: Kind, node: ast.AST, edge: ast.AST) -> ast.Objects:
    def record(**fields: ast.AST) -> ast.AST:
        return ast.Objects(tuple(ast.PropertySignature(k, v) for k, v in fields.items()))

    return ast.Objects(
        (
            ast.PropertySignature("type", ast.Literal(kind)),
            ast.PropertySignature("nodes", ast.Arrays(rest=(record(index=_INDEX, data=node),))),
            ast.PropertySignature(
                "edges",
                ast.Arrays(rest=(record(index=_INDEX, source=_INDEX, target=_INDEX, data=edge),)),
            ),
        )
    )


def _invalid(
    path: tuple[object, ...], expected: str, value: object, options: ParseOptions
) -> Exit[Any, Issue]:
    return fail_exit(Pointer(path, InvalidValue({"expected": expected}, reported(value, options))))


def _decode(encoded: _Encoded, options: ParseOptions) -> Exit[_AnyGraph, Issue]:
    """The graph of a parsed snapshot, or the issue at the first index
    that does not increase or endpoint that names no node."""
    nodes = cast("Sequence[_Encoded]", encoded["nodes"])
    edges = cast("Sequence[_Encoded]", encoded["edges"])
    previous = -1
    indexes: set[int] = set()
    for i, node in enumerate(nodes):
        index = node["index"]
        if index <= previous:
            return _invalid(
                ("nodes", i, "index"), "a strictly increasing node index", index, options
            )
        previous = index
        indexes.add(index)
    previous = -1
    for i, edge in enumerate(edges):
        if edge["index"] <= previous:
            expected = "a strictly increasing edge index"
            return _invalid(("edges", i, "index"), expected, edge["index"], options)
        previous = edge["index"]
        for end in ("source", "target"):
            if edge[end] not in indexes:
                return _invalid(("edges", i, end), "an encoded node index", edge[end], options)
    snapshot = Snapshot(
        encoded["type"],
        tuple(IndexedNode(n["index"], n["data"]) for n in nodes),
        tuple(IndexedEdge(e["index"], e["source"], e["target"], e["data"]) for e in edges),
    )
    return Success(_graph.from_snapshot(snapshot))


def _encoded(g: _AnyGraph) -> _Encoded:
    snapshot = g.to_snapshot()
    return {
        "type": snapshot.type,
        "nodes": tuple({"index": n.index, "data": n.data} for n in snapshot.nodes),
        "edges": tuple(
            {"index": e.index, "source": e.source, "target": e.target, "data": e.data}
            for e in snapshot.edges
        ),
    }


def _is_graph_of(kind: Kind, value: object) -> bool:
    return isinstance(value, _graph.Graph) and cast("_AnyGraph", value).type == kind


def _run(kind: Kind) -> ast.DeclarationRun:
    def run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
        encoded = _encoded_schema(kind, *nodes)

        def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
            if not _is_graph_of(kind, input):
                return ast.invalid_type(node, input, options)
            snapshot = _encoded(cast("_AnyGraph", input))
            return ast.flat_map(
                encoded.parse(snapshot, options),
                lambda parsed: _decode(cast("_Encoded", parsed), options),
            )

        return parse

    return run


def _codec(kind: Kind) -> Callable[[tuple[ast.AST, ...]], ast.Link]:
    expected = f"an immutable {kind} Graph"

    def encode(g: _AnyGraph, options: ParseOptions) -> Exit[_Encoded, Issue]:
        if not _is_graph_of(kind, g):
            return fail_exit(InvalidValue({"expected": expected}, reported(g, options)))
        return Success(_encoded(g))

    def to_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
        return ast.Link(
            _encoded_schema(kind, *nodes), T.transform_effect(decode=_decode, encode=encode)
        )

    return to_codec


def _arbitrary(kind: Kind) -> Callable[[tuple[ast.AST, ...], ArbitraryConstraint], ast.Link]:
    """Effect's ``graphToArbitrary``: ``None`` for the empty graph, or
    node payloads and ``(source, target, data)`` edges whose endpoints
    wrap around the node count."""

    def build(drawn: _Encoded | None) -> _AnyGraph:
        if drawn is None:
            return _graph.from_snapshot(Snapshot(kind))
        data = cast("Sequence[object]", drawn["nodes"])
        edges = cast("Sequence[tuple[int, int, object]]", drawn["edges"])
        count = len(data)
        return _graph.from_snapshot(
            Snapshot(
                kind,
                tuple(IndexedNode(i, d) for i, d in enumerate(data)),
                tuple(
                    IndexedEdge(i, source % count, target % count, d)
                    for i, (source, target, d) in enumerate(edges)
                ),
            )
        )

    def unbuild(g: _AnyGraph) -> _Encoded | None:
        snapshot = g.to_snapshot()
        if not snapshot.nodes:
            return None
        return {
            "nodes": tuple(n.data for n in snapshot.nodes),
            "edges": tuple((e.source, e.target, e.data) for e in snapshot.edges),
        }

    def to_codec_arbitrary(nodes: tuple[ast.AST, ...], _: ArbitraryConstraint) -> ast.Link:
        node, edge = nodes
        drawn = ast.Objects(
            (
                ast.PropertySignature(
                    "nodes", ast.append_checks(ast.Arrays(rest=(node,)), (is_min_length(1),))
                ),
                ast.PropertySignature(
                    "edges",
                    ast.Arrays(
                        rest=(
                            ast.Arrays(
                                (
                                    ast.Element(Natural.ast),
                                    ast.Element(Natural.ast),
                                    ast.Element(edge),
                                )
                            ),
                        )
                    ),
                ),
            )
        )
        return ast.Link(
            ast.Union((ast.null, drawn)), T.Transformation(G.transform(build), G.transform(unbuild))
        )

    return to_codec_arbitrary


def _equivalence(
    parameters: tuple[Equivalence[Any], ...],
) -> Equivalence[_AnyGraph]:
    """Effect's ``graphToEquivalence``: the same kind, node indexes and
    edge indexes in order, equivalent payloads and the same endpoints (in
    either order for an undirected edge)."""
    node, edge = parameters

    def equivalent(self: _AnyGraph, that: _AnyGraph) -> bool:
        a, b = self.to_snapshot(), that.to_snapshot()
        if a.type != b.type or len(a.nodes) != len(b.nodes) or len(a.edges) != len(b.edges):
            return False
        for an, bn in zip(a.nodes, b.nodes, strict=True):
            if an.index != bn.index or not node(an.data, bn.data):
                return False
        for ae, be in zip(a.edges, b.edges, strict=True):
            ends = (ae.source, ae.target)
            same_ends = ends == (be.source, be.target) or (
                a.type == "undirected" and ends == (be.target, be.source)
            )
            if ae.index != be.index or not same_ends or not edge(ae.data, be.data):
                return False
        return True

    return equivalent


def Graph[N, E, NI, EI, K: Kind, RD, RE](
    kind: K, node: Codec[N, NI, RD, RE], edge: Codec[E, EI, RD, RE], /
) -> GraphSchema[N, E, NI, EI, K, RD, RE]:
    """Immutable ``kind`` graphs (``"directed"`` / ``"undirected"``) of
    ``node`` and ``edge`` payloads (Effect's ``Schema.Graph``). A mutable
    graph or one of the other kind is ``Expected an immutable <kind>
    Graph``. JSON writes the graph's snapshot, indexes kept."""
    nodes = (node.__codec__().ast, edge.__codec__().ast)
    annotations = {
        "representation": {"id": "effect/schema/Graph", "payload": kind},
        "expected": f"an immutable {kind} Graph",
        "to_codec": _codec(kind),
        "to_codec_arbitrary": _arbitrary(kind),
        "to_equivalence": _equivalence,
    }
    declaration = ast.Declaration(nodes, _run(kind), annotations=annotations)
    return GraphSchema(declaration, kind, node, edge)
