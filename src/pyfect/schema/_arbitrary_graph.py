"""The decoded side of a schema as ``to_strategy`` walks it: each node's
typed form, how a declaration is generated, and how deep each node must
recurse at least (Effect's ``minCost`` analysis in ``Arbitrary.schema``).

A ``Suspend`` on a cycle costs one level of recursion. A node's cost is the
largest cost among the parts its every value holds (a required key, a
required element, the cheapest union member); a part a value may leave out
(an optional key, the rest of an array) costs nothing. A node no finite
value reaches costs ``INFINITE``: ``Never``, a struct requiring one, a
recursion with no way out. Strategies at recursion budget ``n`` only
use parts costing at most ``n``, so every value they draw is finite.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint, constraint_of
from pyfect.schema._arbitrary_number import big_int_interval, float_interval, integer_interval

INFINITE = math.inf

type CodecArbitrary = Callable[[tuple[ast.AST, ...], ArbitraryConstraint], ast.Link]
"""A declaration's ``to_codec_arbitrary`` annotation: the link from a node
whose generated values decode to the declaration's, given the decoded
sides of its type parameters and its checks' constraint."""


@dataclass(frozen=True, slots=True)
class Strategy:
    """A declaration with a ``to_arbitrary`` annotation: a function of its
    type parameters' strategies."""

    make: Callable[[tuple[Any, ...]], Any]


@dataclass(frozen=True, slots=True)
class Json:
    """A declaration whose values are any JSON (``Json``, a declaration
    already written as JSON)."""


@dataclass(frozen=True, slots=True)
class Linked:
    """A declaration generated as values of ``target`` decoded through
    ``link``."""

    link: ast.Link
    target: ast.AST


type Plan = Strategy | Json | Linked


def _big_decimals(constraint: ArbitraryConstraint) -> Callable[[tuple[Any, ...]], Any]:
    """Effect's constructive ``BigDecimal`` arbitrary, within the bounds."""

    def make(_: tuple[Any, ...]) -> Any:
        from pyfect.schema._strategy._big_decimal import big_decimals

        return big_decimals(constraint)

    return make


class Graph:
    """The decoded side of one root, with each node's cost."""

    def __init__(self, root: ast.AST) -> None:
        self._typed: dict[int, tuple[ast.AST, ast.AST]] = {}
        self._plans: dict[int, tuple[ast.AST, Plan]] = {}
        self.root = self.typed(root)
        self._nodes = self._reachable(self.root)
        self._cyclic = self._find_cycles()
        self._costs = self._solve()

    def typed(self, node: ast.AST) -> ast.AST:
        """``node.to_type()``, made once per node so the walk sees one graph."""
        hit = self._typed.get(id(node))
        if hit is None:
            typed = node.to_type()
            hit = (node, typed)
            self._typed[id(node)] = hit
            self._typed.setdefault(id(typed), (typed, typed))
        return hit[1]

    def cost(self, node: ast.AST) -> float:
        return self._costs[id(node)]

    def is_cyclic(self, node: ast.Suspend) -> bool:
        return id(node) in self._cyclic

    def unwrap(self, node: ast.AST) -> ast.AST:
        """``node`` past any chain of unchecked suspends off a cycle (each
        is its target)."""
        while isinstance(node, ast.Suspend) and not node.checks and not self.is_cyclic(node):
            node = node.target
        return node

    def plan(self, node: ast.Declaration) -> Plan:
        """How ``node`` is generated: its ``to_arbitrary``, then its
        ``to_codec_arbitrary``, ``to_codec_json`` or ``to_codec`` link (as
        in Effect's ``compileDeclaration``)."""
        hit = self._plans.get(id(node))
        if hit is None:
            hit = (node, self._plan(node))
            self._plans[id(node)] = hit
        return hit[1]

    def _plan(self, node: ast.Declaration) -> Plan:
        annotations = node.annotations or {}
        make = annotations.get("to_arbitrary")
        if callable(make):
            return Strategy(cast("Callable[[tuple[Any, ...]], Any]", make))
        representation = annotations.get("representation")
        id = (
            cast("dict[str, object]", representation).get("id")
            if isinstance(representation, dict)
            else None
        )
        if id == "effect/schema/Json":
            return Json()
        if id == "effect/schema/BigDecimal" and make is None:
            return Strategy(_big_decimals(constraint_of(node.checks)))
        parameters = tuple(self.typed(p) for p in node.type_parameters)
        codec_arbitrary = annotations.get("to_codec_arbitrary")
        if callable(codec_arbitrary):
            make_link = cast("CodecArbitrary", codec_arbitrary)
            return self._linked(make_link(parameters, constraint_of(node.checks)))
        for key in ("to_codec_json", "to_codec"):
            to_codec = annotations.get(key)
            if callable(to_codec):
                link = cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", to_codec)(
                    parameters
                )
                return Json() if link is None else self._linked(link)
        raise ValueError(
            f"Unable to derive an arbitrary for an unsupported Declaration ({node.expected()}):"
            " give it a to_arbitrary or to_codec_arbitrary annotation"
        )

    def _linked(self, link: ast.Link) -> Linked:
        return Linked(link, self.typed(link.to))

    def parts(self, node: ast.AST) -> Iterator[tuple[ast.AST, bool]]:  # noqa: PLR0912
        """Each part of ``node``, and whether every value of ``node`` holds
        one."""
        match node:
            case ast.Union():
                for member in node.types:
                    yield member, False
            case ast.Arrays():
                minimum = constraint_of(node.checks).min_length or 0
                for i, element in enumerate(node.elements):
                    yield element.type, not element.optional or i < minimum
                if node.rest:
                    head, *post = node.rest
                    yield head, minimum > len(node.elements) + len(post)
                    for element in post:
                        yield element, True
            case ast.Objects():
                minimum = constraint_of(node.checks).min_properties or 0
                for p in node.properties:
                    yield p.type, not p.optional
                required = sum(not p.optional for p in node.properties)
                for index in node.index_signatures:
                    yield index.parameter, minimum > required
                    yield index.type, minimum > required
            case ast.Suspend():
                yield node.target, True
            case ast.TemplateLiteral():
                for part in node.parts:
                    yield part, True
            case ast.Class():
                side = node.shape.fields if node.side == "type" else node.shape.encoded
                yield self.typed(side), True
            case ast.Declaration():
                match self.plan(node):
                    case Strategy():
                        for parameter in node.type_parameters:
                            yield self.typed(parameter), True
                    case Linked(target=target):
                        yield target, True
                    case Json():
                        pass
            case _:
                pass

    def _reachable(self, root: ast.AST) -> list[ast.AST]:
        seen: dict[int, ast.AST] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen[id(node)] = node
            _validate(node)
            stack.extend(part for part, _ in self.parts(node))
        return list(seen.values())

    def _find_cycles(self) -> set[int]:
        """The suspends a value can reach again from inside themselves: those
        in a strongly connected component of more than one node, or with an
        edge to themselves (Tarjan's algorithm, without recursion)."""
        index: dict[int, int] = {}
        low: dict[int, int] = {}
        on_stack: set[int] = set()
        stack: list[ast.AST] = []
        cyclic: set[int] = set()
        for start in self._nodes:
            if id(start) in index:
                continue
            work = [(start, iter([p for p, _ in self.parts(start)]))]
            index[id(start)] = low[id(start)] = len(index)
            stack.append(start)
            on_stack.add(id(start))
            while work:
                node, children = work[-1]
                child = next(children, None)
                if child is not None:
                    if id(child) not in index:
                        index[id(child)] = low[id(child)] = len(index)
                        stack.append(child)
                        on_stack.add(id(child))
                        work.append((child, iter([p for p, _ in self.parts(child)])))
                    elif id(child) in on_stack:
                        low[id(node)] = min(low[id(node)], index[id(child)])
                        if child is node:
                            cyclic.add(id(node))
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[id(parent)] = min(low[id(parent)], low[id(node)])
                if low[id(node)] == index[id(node)]:
                    component: list[ast.AST] = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(id(member))
                        component.append(member)
                        if member is node:
                            break
                    if len(component) > 1:
                        cyclic.update(id(m) for m in component)
        return {id(n) for n in self._nodes if isinstance(n, ast.Suspend) and id(n) in cyclic}

    def _solve(self) -> dict[int, float]:
        costs = dict.fromkeys(map(id, self._nodes), INFINITE)
        changed = True
        while changed:
            changed = False
            # Parts were found after the nodes holding them: leaves first.
            for node in reversed(self._nodes):
                cost = self._cost_of(node, costs)
                if cost < costs[id(node)]:
                    costs[id(node)] = cost
                    changed = True
        return costs

    def _cost_of(self, node: ast.AST, costs: dict[int, float]) -> float:
        match node:
            case ast.Never():
                return INFINITE
            case ast.Union():
                return min((costs[id(m)] for m in node.types), default=INFINITE)
            case ast.Suspend():
                target = costs[id(node.target)]
                return target + 1 if self.is_cyclic(node) else target
            case _:
                return max(
                    (costs[id(part)] for part, required in self.parts(node) if required),
                    default=0,
                )


def _contradicts(minimum: object, maximum: object) -> bool:
    return minimum is not None and maximum is not None and cast("Any", minimum) > maximum


def _equal(minimum: object, maximum: object) -> bool:
    return minimum is not None and maximum is not None and minimum == maximum


def _validate(node: ast.AST) -> None:
    """Raise when ``node``'s checks leave no value to generate (Effect's
    ``validateConstraint``)."""
    c = constraint_of(node.checks)
    match node:
        case ast.Arrays():
            required = sum(not e.optional for e in node.elements) + max(0, len(node.rest) - 1)
            if _contradicts(c.min_length, c.max_length) or _contradicts(required, c.max_length):
                raise ValueError("Unable to derive an arbitrary for array constraints")
        case ast.Objects():
            required = sum(not p.optional for p in node.properties)
            if _contradicts(c.min_properties, c.max_properties) or _contradicts(
                required, c.max_properties
            ):
                raise ValueError("Unable to derive an arbitrary for object property constraints")
        case _:
            pass
    bounds = (
        (c.min_length, c.max_length),
        (c.min_size, c.max_size),
        (c.min_properties, c.max_properties),
        (c.minimum, c.maximum),
    )
    excluded = (c.exclusive_minimum or c.exclusive_maximum) and _equal(c.minimum, c.maximum)
    if excluded or any(_contradicts(low, high) for low, high in bounds):
        raise ValueError("Unable to derive an arbitrary for constraints")
    match node:
        case ast.Number():
            if c.number == "integer":
                integer_interval(c)
            else:
                float_interval(c)
        case ast.BigInt():
            big_int_interval(c)
        case ast.Enum() if not node.members:
            raise ValueError("Unable to derive an arbitrary for an enum with no members")
        case _:
            pass
