"""``HashSet`` and ``HashMap``: Effect's ``Schema.HashSet`` / ``Schema.HashMap``,
decoding to ``pyfect.hash_set.HashSet`` / ``pyfect.hash_map.HashMap``.

They key by Effect's ``Equal``, so ``1`` and ``True`` stay apart and every
``NaN`` is one item, as in Effect (``S.FrozenSet`` / ``S.Map`` decode to
Python's ``frozenset`` / ``dict``, which merge ``1`` and ``True``). A set is
parsed as an array of its values (issues at ``["values"][i]``), a map as an
array of ``(key, value)`` pairs (at ``["entries"][i][0]`` / ``[1]``), in the
collection's hash order; JSON writes the same arrays.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast

from pyfect._js import js_sort_key
from pyfect.hash_map import HashMap as _HashMap
from pyfect.hash_set import HashSet as _HashSet
from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_size import is_max_length, is_min_length, is_unique, is_unique_key
from pyfect.schema._codec_links import link
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._to_equivalence import Equivalence, same_items
from pyfect.schema._to_formatter import Formatter

# Explicit parameters (``tests/test_schema_variance.py``): ``HashSet`` and
# ``HashMap`` take their items in ``add`` / ``set``, so they are invariant.
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
K_co = TypeVar("K_co", covariant=True)
V_co = TypeVar("V_co", covariant=True)
KI_co = TypeVar("KI_co", covariant=True)
VI_co = TypeVar("VI_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)

type _Set = _HashSet[object]
type _Map = _HashMap[object, object]
type _Entry = tuple[object, object]


def _sized(rest: ast.AST, check: ast.Check[Any], constraint: ArbitraryConstraint) -> ast.AST:
    """Arrays of ``rest`` passing ``check`` and the constraint's size bounds
    (Effect's ``withArrayLengthConstraints``)."""
    checks: list[ast.Check[Any]] = [check]
    if constraint.min_size is not None:
        checks.append(is_min_length(constraint.min_size))
    if constraint.max_size is not None:
        checks.append(is_max_length(constraint.max_size))
    return ast.append_checks(ast.Arrays(rest=(rest,)), (checks[0], *checks[1:]))


def _sorted_text(size: int, name: str, texts: Iterable[str]) -> str:
    if size == 0:
        return f"{name}(0) {{}}"
    return f"{name}({size}) {{ {', '.join(sorted(texts, key=js_sort_key))} }}"


# ------------------------------------------------------------------ HashSet


@dataclass(frozen=True, slots=True, eq=False)
class HashSetSchema(
    Bottom[_HashSet[A_co], _HashSet[I_co], RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]
):
    """A ``HashSet`` of ``value``'s values."""

    value: Codec[A_co, I_co, RD_co, RE_co]


def _set_of(values: Iterable[object]) -> _Set:
    return _HashSet.from_iterable(values)


def _set_values(values: _Set) -> tuple[object, ...]:
    return tuple(values)


def _set_run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    values = ast.Arrays(rest=nodes)

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if not isinstance(input, _HashSet):
            return ast.invalid_type(node, input, options)
        hash_set = cast("_Set", input)
        items = _set_values(hash_set)
        parsed = ast.parse_at_key(node, "values", values, items, input=hash_set, options=options)
        return ast.map_value(parsed, lambda out: _set_of(cast("tuple[object, ...]", out)))

    return parse


def _set_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    return link(ast.Arrays(rest=nodes), decode=_set_of, encode=_set_values)


def _set_arbitrary(nodes: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    (value,) = nodes
    return link(_sized(value, is_unique(), constraint), decode=_set_of, encode=_set_values)


def _set_equivalence(parameters: tuple[Equivalence[Any], ...]) -> Equivalence[_Set]:
    return same_items(parameters[0])


def _set_formatter(parameters: tuple[Formatter[Any], ...]) -> Formatter[_Set]:
    (value,) = parameters
    return lambda values: _sorted_text(len(values), "HashSet", map(value, values))


def HashSet[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> HashSetSchema[A, I, RD, RE]:
    """A ``pyfect.hash_set.HashSet`` of ``value``'s values (Effect's
    ``Schema.HashSet``), keyed by Effect's ``Equal``: ``1`` and ``True``
    are two items. Anything else is ``Expected HashSet``. JSON writes an
    array of the values."""
    node = ast.Declaration(
        (value.__codec__().ast,),
        _set_run,
        annotations={
            "representation": {"id": "effect/schema/HashSet", "payload": None},
            "expected": "HashSet",
            "to_codec": _set_codec,
            "to_codec_arbitrary": _set_arbitrary,
            "to_equivalence": _set_equivalence,
            "to_formatter": _set_formatter,
        },
    )
    return HashSetSchema(node, value)


# ------------------------------------------------------------------ HashMap


@dataclass(frozen=True, slots=True, eq=False)
class HashMapSchema(
    Bottom[_HashMap[K_co, V_co], _HashMap[KI_co, VI_co], RD_co, RE_co],
    Generic[K_co, V_co, KI_co, VI_co, RD_co, RE_co],
):
    """A ``HashMap`` of ``key``'s values to ``value``'s."""

    key: Codec[K_co, KI_co, RD_co, RE_co]
    value: Codec[V_co, VI_co, RD_co, RE_co]


def _map_of(entries: Iterable[_Entry]) -> _Map:
    return _HashMap.from_iterable(entries)


def _map_entries(entries: _Map) -> tuple[_Entry, ...]:
    return tuple(entries)


def _entry(nodes: tuple[ast.AST, ...]) -> ast.Arrays:
    return ast.Arrays(tuple(ast.Element(n) for n in nodes))


def _map_run(nodes: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    entries = ast.Arrays(rest=(_entry(nodes),))

    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        if not isinstance(input, _HashMap):
            return ast.invalid_type(node, input, options)
        hash_map = cast("_Map", input)
        pairs = _map_entries(hash_map)
        parsed = ast.parse_at_key(node, "entries", entries, pairs, input=hash_map, options=options)
        return ast.map_value(parsed, lambda out: _map_of(cast("tuple[_Entry, ...]", out)))

    return parse


def _map_codec(nodes: tuple[ast.AST, ...]) -> ast.Link:
    return link(ast.Arrays(rest=(_entry(nodes),)), decode=_map_of, encode=_map_entries)


def _map_arbitrary(nodes: tuple[ast.AST, ...], constraint: ArbitraryConstraint) -> ast.Link:
    drawn = _sized(_entry(nodes), is_unique_key(), constraint)
    return link(drawn, decode=_map_of, encode=_map_entries)


def _map_equivalence(parameters: tuple[Equivalence[Any], ...]) -> Equivalence[_Map]:
    key, value = parameters

    def same_entry(a: _Entry, b: _Entry) -> bool:
        return key(a[0], b[0]) and value(a[1], b[1])

    return same_items(same_entry)


def _map_formatter(parameters: tuple[Formatter[Any], ...]) -> Formatter[_Map]:
    key, value = parameters
    return lambda entries: _sorted_text(
        len(entries), "HashMap", (f"{key(k)} => {value(v)}" for k, v in entries)
    )


def HashMap[K, V, KI, VI, RD, RE](
    key: Codec[K, KI, RD, RE], value: Codec[V, VI, RD, RE], /
) -> HashMapSchema[K, V, KI, VI, RD, RE]:
    """A ``pyfect.hash_map.HashMap`` of ``key`` values to ``value`` values
    (Effect's ``Schema.HashMap``), keyed by Effect's ``Equal``: ``1`` and
    ``True`` are two keys. Anything else is ``Expected HashMap``. JSON
    writes an array of ``[key, value]`` pairs."""
    nodes = (key.__codec__().ast, value.__codec__().ast)
    annotations = {
        "representation": {"id": "effect/schema/HashMap", "payload": None},
        "expected": "HashMap",
        "to_codec": _map_codec,
        "to_codec_arbitrary": _map_arbitrary,
        "to_equivalence": _map_equivalence,
        "to_formatter": _map_formatter,
    }
    node = ast.Declaration(nodes, _map_run, annotations=annotations)
    return HashMapSchema(node, key, value)
