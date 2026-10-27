"""``FrozenSet`` and ``Map``: Effect's ``ReadonlySet`` / ``HashSet`` and
``ReadonlyMap`` / ``HashMap`` over Python's ``frozenset`` and ``dict``.

Both are declarations: they take a set or a mapping and parse what it
holds, as an array of values (issues at ``["values"][i]``) or of
``(key, value)`` pairs (at ``["entries"][i][0]`` / ``[1]``), in iteration
order. A ``Record`` reads a mapping as an object with keys; a ``Map`` reads
it as entries, so any key schema takes part on both sides.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pyfect.schema import ast
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
K_ = TypeVar("K_")
V_ = TypeVar("V_")
KI_ = TypeVar("KI_")
VI_co = TypeVar("VI_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class FrozenSetSchema(
    Bottom[frozenset[A_co], frozenset[I_co], RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]
):
    """A set of ``value``'s values."""

    value: Codec[A_co, I_co, RD_co, RE_co]


def _set_run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    values = ast.Arrays((), nodes)

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if not isinstance(input, Set):
            return ast.invalid_type(node, input, options)
        values_in = cast("Set[object]", input)
        items = tuple(values_in)
        return ast.map_value(
            ast.parse_at_key(node, "values", values, items, input=values_in, options=options),
            lambda parsed: frozenset(cast("tuple[object, ...]", parsed)),
        )

    return parse


def FrozenSet[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> FrozenSetSchema[A, I, RD, RE]:
    """A ``set`` or ``frozenset`` of ``value``'s values, decoded to a
    ``frozenset`` (Effect's ``ReadonlySet``). Anything else is ``Expected
    frozenset``."""
    node = ast.Declaration(
        (value.__codec__().ast,), _set_run, annotations={"expected": "frozenset"}
    )
    return FrozenSetSchema(node, value)


@dataclass(frozen=True, slots=True, eq=False)
class MapSchema(
    Bottom[dict[K_, V_], Mapping[KI_, VI_co], RD_co, RE_co],
    Generic[K_, V_, KI_, VI_co, RD_co, RE_co],
):
    """A mapping of ``key``'s values to ``value``'s."""

    key: Codec[K_, KI_, RD_co, RE_co]
    value: Codec[V_, VI_co, RD_co, RE_co]


def _map_run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    entries = ast.Arrays((), (ast.Arrays(tuple(ast.Element(n) for n in nodes)),))

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if not isinstance(input, Mapping):
            return ast.invalid_type(node, input, options)
        mapping = cast("Mapping[object, object]", input)
        pairs = tuple(mapping.items())
        return ast.map_value(
            ast.parse_at_key(node, "entries", entries, pairs, input=mapping, options=options),
            lambda parsed: dict(cast("tuple[tuple[object, object], ...]", parsed)),
        )

    return parse


def Map[K, V, KI, VI, RD, RE](
    key: Codec[K, KI, RD, RE], value: Codec[V, VI, RD, RE], /
) -> MapSchema[K, V, KI, VI, RD, RE]:
    """A ``Mapping`` of ``key`` values to ``value`` values, decoded to a
    ``dict`` (Effect's ``ReadonlyMap``). Anything else is ``Expected
    Mapping``."""
    nodes = (key.__codec__().ast, value.__codec__().ast)
    node = ast.Declaration(nodes, _map_run, annotations={"expected": "Mapping"})
    return MapSchema(node, key, value)
