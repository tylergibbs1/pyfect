"""``FrozenSet`` and ``Map``: Effect's ``ReadonlySet`` / ``HashSet`` and
``ReadonlyMap`` / ``HashMap`` over Python's ``frozenset`` and ``dict``.

Both are declarations: they take a set or a mapping and parse what it
holds, as an array of values (issues at ``["values"][i]``) or of
``(key, value)`` pairs (at ``["entries"][i][0]`` / ``[1]``), in iteration
order. A ``Record`` reads a mapping as an object with keys; a ``Map`` reads
it as entries, so any key schema takes part on both sides.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from pyfect._equal import dict_of, frozenset_of
from pyfect.exit import Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import _arbitrary_links as _arb
from pyfect.schema import _instances as _inst
from pyfect.schema import ast
from pyfect.schema._codec_links import partial_link
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.issue import InvalidValue, reported

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


_SET_EXPECTED = "items a frozenset keeps apart (True and 1 are one item in Python)"
_MAP_EXPECTED = "keys a dict keeps apart (True and 1 are one key in Python)"


def _built(
    result: ast.ParseResult,
    build: Callable[[Any], object | None],
    expected: str,
    input: object,
    options: ParseOptions,
) -> ast.ParseResult:
    def finish(parsed: object) -> ast.ParseResult:
        out = build(parsed)
        if out is None:
            return fail_exit(InvalidValue({"expected": expected}, reported(input, options)))
        return Success(out)

    return ast.flat_map(result, finish)


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
        return _built(
            ast.parse_at_key(node, "values", values, items, input=values_in, options=options),
            frozenset_of,
            _SET_EXPECTED,
            values_in,
            options,
        )

    return parse


def _set_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    # Written as an array of its values, as Effect does.
    return partial_link(
        ast.Arrays(rest=nodes), decode=frozenset_of, encode=tuple, expected=_SET_EXPECTED
    )


def FrozenSet[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> FrozenSetSchema[A, I, RD, RE]:
    """A ``set`` or ``frozenset`` of ``value``'s values, decoded to a
    ``frozenset`` (Effect's ``ReadonlySet``). Anything else is ``Expected
    frozenset``."""
    node = ast.Declaration(
        (value.__codec__().ast,),
        _set_run,
        annotations={
            "expected": "frozenset",
            "to_codec": _set_codec,
            "to_codec_arbitrary": _arb.frozen_set,
            "to_equivalence": _inst.set_equivalence,
            "to_formatter": _inst.set_formatter,
        },
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
        return _built(
            ast.parse_at_key(node, "entries", entries, pairs, input=mapping, options=options),
            dict_of,
            _MAP_EXPECTED,
            mapping,
            options,
        )

    return parse


def _entries(mapping: Mapping[object, object]) -> tuple[tuple[object, object], ...]:
    return tuple(mapping.items())


def _map_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    # Written as an array of ``[key, value]`` pairs, as Effect does.
    entry = ast.Arrays(tuple(ast.Element(n) for n in nodes))
    return partial_link(
        ast.Arrays(rest=(entry,)), decode=dict_of, encode=_entries, expected=_MAP_EXPECTED
    )


def Map[K, V, KI, VI, RD, RE](
    key: Codec[K, KI, RD, RE], value: Codec[V, VI, RD, RE], /
) -> MapSchema[K, V, KI, VI, RD, RE]:
    """A ``Mapping`` of ``key`` values to ``value`` values, decoded to a
    ``dict`` (Effect's ``ReadonlyMap``). Anything else is ``Expected
    Mapping``."""
    nodes = (key.__codec__().ast, value.__codec__().ast)
    annotations = {
        "expected": "Mapping",
        "to_codec": _map_codec,
        "to_codec_arbitrary": _arb.map_,
        "to_equivalence": _inst.map_equivalence,
        "to_formatter": _inst.map_formatter,
    }
    node = ast.Declaration(nodes, _map_run, annotations=annotations)
    return MapSchema(node, key, value)
