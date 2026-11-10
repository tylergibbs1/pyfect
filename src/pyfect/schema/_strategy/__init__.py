"""``to_strategy``'s derivation over Hypothesis (Effect's ``Arbitrary.schema``
mapped to Hypothesis strategies; Hypothesis runs, shrinks and replays).

Each node of the decoded side gets a strategy built within its checks'
constraint (``_arbitrary_constraint.py``); its checks then filter what the
strategy draws, so a value always satisfies them. A declaration is drawn
through its plan (``_arbitrary_graph.py``): its ``to_arbitrary``, or values
of a linked node decoded through the link and checked by the declaration.
Recursion is bounded by a budget spent on each cyclic ``Suspend``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Hashable
from typing import Any

from pyfect._extras import missing_extra

try:
    from hypothesis import strategies as st
    from hypothesis.errors import InvalidArgument
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("to_strategy", "hypothesis", error) from error

from pyfect.exit import Failure, Success
from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint, constraint_of
from pyfect.schema._arbitrary_graph import INFINITE, Graph, Json, Linked, Strategy
from pyfect.schema._strategy import _leaves
from pyfect.schema._strategy._composites import (
    ArraysPlan,
    Index,
    ObjectsPlan,
    arrays,
    objects,
)
from pyfect.schema.getter._coerce import to_string

type _Strategy = st.SearchStrategy[Any]

RECURSION_DEPTH = 4
"""How many times a value may pass through a cyclic ``Suspend`` (more when
the schema's finite values need more)."""

_REJECTED = object()
_SCALARS = (ast.String, ast.Number, ast.BigInt)


def derive(root: ast.AST) -> _Strategy:
    graph = Graph(root)
    cost = graph.cost(graph.root)
    if cost == INFINITE:
        raise ValueError(
            "Unable to derive an arbitrary for a schema without a finite generation path"
            f" ({graph.root.expected()})"
        )
    drawn = _Derivation(graph)(graph.root, max(RECURSION_DEPTH, int(cost)))
    # Only values the schema also encodes (a JSON string holds no NaN, say).
    encoder = root.flip()
    return drawn.filter(lambda value: not isinstance(encoder.parse(value, {}), Failure))


def _parses(node: ast.AST, value: object) -> bool:
    return type(ast.run_now(node.parse(value, {}))) is Success


def _keep(strategy: _Strategy, f: Callable[[Any], object]) -> _Strategy:
    """``strategy`` mapped by ``f``, dropping what ``f`` rejects."""
    return strategy.map(f).filter(lambda value: value is not _REJECTED)


class _Derivation:
    def __init__(self, graph: Graph) -> None:
        self._graph = graph
        self._done: dict[tuple[int, int], tuple[ast.AST, _Strategy]] = {}

    def __call__(self, node: ast.AST, budget: int) -> _Strategy:
        """``node``'s strategy using parts that cost at most ``budget``."""
        node = self._graph.unwrap(node)
        key = (id(node), budget)
        hit = self._done.get(key)
        if hit is None:
            hit = (node, self._checked(node, budget))
            self._done[key] = hit
        return hit[1]

    def _fits(self, node: ast.AST, budget: int) -> bool:
        return self._graph.cost(node) <= budget

    def _checked(self, node: ast.AST, budget: int) -> _Strategy:
        constraint = constraint_of(node.checks)
        strategy = self._derive(node, budget, constraint)
        checks = node.checks
        if not checks:
            return strategy
        return strategy.filter(lambda value: ast.collect_issues(checks, value, node, {}) is None)

    def _derive(  # noqa: PLR0911, PLR0912
        self, node: ast.AST, budget: int, constraint: ArbitraryConstraint
    ) -> _Strategy:
        match node:
            case ast.Never():
                return st.nothing()
            case ast.Any() | ast.Unknown():
                return _leaves.json()
            case ast.Null():
                return st.none()
            case ast.Boolean():
                return st.booleans()
            case ast.String():
                return _leaves.string(constraint)
            case ast.Number():
                return _leaves.number(constraint)
            case ast.BigInt():
                return _leaves.big_int(constraint)
            case ast.Literal():
                return st.just(node.literal)
            case ast.Enum():
                members = node.members
                values = members if node.side == "type" else tuple(m.value for m in members)
                return st.sampled_from(values)
            case ast.Union():
                return self._union(node, budget)
            case ast.Arrays():
                return self._arrays(node, budget, constraint)
            case ast.Objects():
                return self._objects(node, budget, constraint)
            case ast.Suspend():
                target = node.target
                inner = budget - 1 if self._graph.is_cyclic(node) else budget
                return st.deferred(lambda: self(target, inner))
            case ast.Class():
                return self._class(node, budget)
            case ast.Declaration():
                return self._declaration(node, budget)
            case ast.TemplateLiteral():
                return self._template(node, budget)
            case _:
                raise ValueError(f"Unable to derive an arbitrary for {node.expected()}")

    def _template(self, node: ast.TemplateLiteral, budget: int) -> _Strategy:
        # Each part's text, joined; a non-finite number has no segment.
        parts = [
            self(p, budget).filter(math.isfinite) if isinstance(p, ast.Number) else self(p, budget)
            for p in node.parts
        ]
        return (
            st.tuples(*parts)
            .map(lambda values: "".join(map(to_string, values)))
            .filter(lambda text: _parses(node, text))
        )

    def _union(self, node: ast.Union, budget: int) -> _Strategy:
        members = [self(m, budget) for m in node.types if self._fits(m, budget)]
        strategy = st.one_of(members)
        if node.mode == "one_of":
            # A value two members take is not one of them.
            return strategy.filter(lambda value: _parses(node, value))
        return strategy

    def _arrays(self, node: ast.Arrays, budget: int, constraint: ArbitraryConstraint) -> _Strategy:
        def part(type: ast.AST) -> _Strategy | None:
            return self(type, budget) if self._fits(type, budget) else None

        head, *post = node.rest or (None,)
        rest = None if head is None else part(head)
        plan = ArraysPlan(
            required=[self(e.type, budget) for e in node.elements if not e.optional],
            optional=[part(e.type) for e in node.elements if e.optional],
            rest=rest,
            post=[self(p, budget) for p in post],
            mutable=node.mutable,
            unique=constraint.unique,
        )
        return arrays(plan, constraint)

    def _objects(
        self, node: ast.Objects, budget: int, constraint: ArbitraryConstraint
    ) -> _Strategy:
        signatures = node.index_signatures

        def fits_indexes(key: object, value: object) -> bool:
            # A key an index signature takes holds a value of its type too
            # (a declared key included), whichever part drew it.
            return all(_parses(i.type, value) for i in signatures if i.selects(key))

        def prop(p: ast.PropertySignature) -> tuple[Hashable, _Strategy]:
            selecting = [i for i in signatures if i.selects(p.name)]
            if not selecting:
                return p.name, self(p.type, budget)
            strategy = self._within(p.type, [i.type for i in selecting], budget)
            return p.name, strategy.filter(lambda value: fits_indexes(p.name, value))

        plan = ObjectsPlan(
            required=[prop(p) for p in node.properties if not p.optional],
            optional=[
                prop(p) for p in node.properties if p.optional and self._fits(p.type, budget)
            ],
            indexes=[
                Index(self(i.parameter, budget), self(i.type, budget))
                for i in signatures
                if self._fits(i.parameter, budget) and self._fits(i.type, budget)
            ],
            fits_indexes=fits_indexes,
        )
        return objects(plan, constraint)

    def _within(self, node: ast.AST, others: list[ast.AST], budget: int) -> _Strategy:
        """``node``'s strategy, drawn within the checks of the scalar
        ``others`` of its kind too (Effect combines a fixed field's
        constraints with the index signatures taking its key); the caller
        filters by the rest."""
        merged = node
        for other in others:
            if type(other) is type(merged) and isinstance(merged, _SCALARS) and other.checks:
                merged = ast.append_checks(merged, other.checks)
        if merged is not node:
            try:
                strategy = self._checked(merged, budget)
                strategy.validate()
            except (InvalidArgument, ValueError):
                pass  # No value fits both: the caller's filter gives up when drawing.
            else:
                return strategy
        return self(node, budget)

    def _class(self, node: ast.Class, budget: int) -> _Strategy:
        shape = node.shape
        if node.side != "type":
            return self(self._graph.typed(shape.encoded), budget)
        fields = self(self._graph.typed(shape.fields), budget)

        def construct(values: dict[object, object]) -> object:
            instance = shape.construct(values)
            checked = ast.check_instance(shape, instance, {})
            return checked.value if isinstance(checked, Success) else _REJECTED

        return _keep(fields, construct)

    def _declaration(self, node: ast.Declaration, budget: int) -> _Strategy:
        match self._graph.plan(node):
            case Strategy(make=make):
                parameters = tuple(self(self._graph.typed(p), budget) for p in node.type_parameters)
                strategy: _Strategy = make(parameters)
                return strategy
            case Json():
                return _leaves.json().filter(lambda value: _parses(node, value))
            case Linked(link=link, target=target):

                def decode(value: object) -> object:
                    decoded = ast.run_now(link.transformation.decode_result(Success(value), {}))
                    if not isinstance(decoded, Success):
                        return _REJECTED
                    checked = ast.run_now(node.parse(decoded.value, {}))
                    return checked.value if isinstance(checked, Success) else _REJECTED

                return _keep(self(target, budget), decode)
