"""Which members of a union may take an input (Effect's candidate index).

A member is a candidate by the input's kind (``"string"``, ``"object"``,
...), a ``Literal`` member only for its literal. Members that are mappings
with required literal keys (``"_tag": "A"``) or tuples with required
literal elements (``("a", ...)``), Effect's sentinels, are discriminated:
an input picks them by the values it holds under those keys or indexes,
before any member is parsed.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from pyfect.logger._text import format_unknown, json_quote
from pyfect.schema.ast._arrays import Arrays
from pyfect.schema.ast._base import AST
from pyfect.schema.ast._class import Class
from pyfect.schema.ast._encoding import Encoding, to_encoded
from pyfect.schema.ast._keywords import BigInt, Boolean, Never, Null, Number, String, Unknown
from pyfect.schema.ast._literal import Enum, Literal, LiteralValue, same_literal
from pyfect.schema.ast._objects import ObjectKeys, Objects, reads_properties
from pyfect.schema.ast._suspend import Suspend

if TYPE_CHECKING:
    from pyfect.schema.ast._union import Union

ALL = frozenset({"null", "string", "number", "bigint", "boolean", "array", "object"})
NOT_NULL = ALL - {"null"}
OBJECT = frozenset({"object"})
ARRAY = frozenset({"array"})

_VALUE_KINDS: tuple[tuple[type, frozenset[str]], ...] = (
    (type(None), frozenset({"null"})),
    (bool, frozenset({"boolean"})),
    (int, frozenset({"number", "bigint"})),
    (float, frozenset({"number"})),
    (str, frozenset({"string"})),
    (list, frozenset({"array"})),
    (tuple, frozenset({"array"})),
)

_NODE_KINDS: tuple[tuple[type[AST], frozenset[str]], ...] = (
    (Null, frozenset({"null"})),
    (String, frozenset({"string"})),
    (Number, frozenset({"number"})),
    (BigInt, frozenset({"bigint"})),
    (Boolean, frozenset({"boolean"})),
)


def kind_of(value: object) -> frozenset[str]:
    """The kinds a value is (a Python ``int`` is a number and a bigint)."""
    return next((kinds for t, kinds in _VALUE_KINDS if isinstance(value, t)), OBJECT)


def _literal_kind(literal: LiteralValue) -> frozenset[str]:
    return (
        frozenset({"number"})
        if isinstance(literal, int | float) and not isinstance(literal, bool)
        else kind_of(literal)
    )


def _members(ast: AST) -> tuple[AST, ...] | None:
    """A union's members; ``None`` for any other node."""
    from pyfect.schema.ast._union import Union

    return ast.types if isinstance(ast, Union) else None


def kinds(ast: AST) -> frozenset[str]:  # noqa: PLR0911
    """The kinds of input ``ast`` may accept (Effect's ``getCandidateTypes``)."""
    members = _members(ast)
    if members is not None:
        return frozenset[str]().union(*map(kinds, members))
    match ast:
        case Literal(literal=literal):
            return _literal_kind(literal)
        case Enum(side="decode" | "encoded"):
            return frozenset[str]().union(*(_literal_kind(m.value) for m in ast.enum))
        case Objects(properties=(), index_signatures=()):
            return NOT_NULL
        case Objects() | Class(side="decode" | "encoded"):
            return OBJECT
        case Arrays():
            return ARRAY
        case _:
            return next((kinds for t, kinds in _NODE_KINDS if isinstance(ast, t)), ALL)


type Sentinel = tuple[Hashable, LiteralValue]
"""A required key (or a tuple's index) and the literal it must hold."""


def _input_side(ast: AST) -> AST:
    """The node of what the member takes as input (Effect's ``toCandidate``).
    A suspended member takes anything: selecting candidates never makes it
    (it may be the union itself)."""
    return Unknown() if isinstance(ast, Suspend) else _settled(ast).flip().to_type()


def _settled(ast: AST) -> AST:
    """``ast`` with every part whose failures a middleware sees (and may
    recover from, as ``catch_decoding`` does) taken as ``Unknown``: such a
    part may take any input and holds no sentinel (Effect's ``toCandidate``)."""
    encoding = ast.encoding
    if encoding is not None:
        return _settled_encoding(ast, encoding)
    members = _members(ast)
    if members is not None:
        return cast("Union", ast).map_types(_settled)
    match ast:
        case Objects(properties=properties):
            types = [_settled(p.type) for p in properties]
            if all(t is p.type for t, p in zip(types, properties, strict=True)):
                return ast
            settled = (replace(p, type=t) for t, p in zip(types, properties, strict=True))
            return replace(ast, properties=tuple(settled))
        case Arrays():
            return ast.map_types(_settled)
        case _:
            return ast


def _settled_encoding(ast: AST, encoding: Encoding) -> AST:
    if any(link.transformation.sees_failures for link in encoding):
        return Unknown()
    *links, last = encoding
    source = _settled(last.to)
    return ast if source is last.to else replace(ast, encoding=(*links, replace(last, to=source)))


def sentinels(ast: AST) -> tuple[Sentinel, ...]:
    """The required literal keys of a mapping node and the required literal
    elements of a tuple, by index (Effect's ``collectSentinels``); a union's
    are those all its members share."""
    members = _members(ast)
    if members is not None:
        if not members:
            return ()
        each = [sentinels(_input_side(m)) for m in members]
        return tuple(s for s in each[0] if all(_has(other, s) for other in each[1:]))
    match ast:
        case Objects(properties=properties):
            return tuple(
                (p.name, p.type.literal)
                for p in properties
                if not p.optional and isinstance(p.type, Literal)
            )
        case Class(side="encoded" | "decode"):
            return sentinels(ast.shape.encoded)
        case Arrays(elements=elements):
            return tuple(
                (i, e.type.literal)
                for i, e in enumerate(elements)
                if not e.optional and isinstance(e.type, Literal)
            )
        case _:
            return ()


def _has(found: Sequence[Sentinel], sentinel: Sentinel) -> bool:
    key, literal = sentinel
    return any(k == key and same_literal(literal, v) for k, v in found)


@dataclass(frozen=True, slots=True)
class _Member:
    literal: tuple[LiteralValue] | None
    """``(literal,)`` for a ``Literal`` member."""
    sentinels: tuple[Sentinel, ...]
    kinds: frozenset[str]
    never: bool


def _member(ast: AST) -> _Member:
    side = _input_side(ast)
    found = sentinels(side)
    literal = (side.literal,) if isinstance(side, Literal) else None
    return _Member(literal, found, frozenset() if found else kinds(side), isinstance(side, Never))


_ABSENT = object()


def _observed(
    input: object, keys: tuple[Hashable, ...]
) -> tuple[dict[Hashable, object], frozenset[str]] | None:
    """The values ``input`` holds under the sentinel ``keys`` (a mapping's
    keys, an object's attributes, a list's or tuple's indexes) and its kind;
    ``None`` when it is none of these."""
    if isinstance(input, Mapping) or reads_properties(input):
        mapping = (
            cast("Mapping[object, object]", input)
            if isinstance(input, Mapping)
            else ObjectKeys(input)
        )
        return {key: mapping[key] for key in keys if key in mapping}, OBJECT
    if isinstance(input, list | tuple):
        items = cast("Sequence[object]", input)
        n = len(items)
        return {key: items[key] for key in keys if type(key) is int and 0 <= key < n}, ARRAY
    return None


class CandidateIndex:
    """The candidates of a union's members for an input."""

    __slots__ = ("_members", "_only_literals", "_sentinel_keys")

    def __init__(self, types: Sequence[AST]) -> None:
        self._members = [_member(t) for t in types]
        live = [m for m in self._members if not m.never]
        self._only_literals = bool(live) and all(m.literal is not None for m in live)
        keys: dict[Hashable, None] = {}
        for m in live:
            for key, _ in m.sentinels:
                keys[key] = None
        self._sentinel_keys = tuple(keys)

    def __call__(self, input: object, constructing: bool = False) -> list[int]:
        """The candidates for ``input``; under a constructor (Effect's
        constructor mode) a missing sentinel key selects every member that
        has it, as a constructor default may fill it in."""
        members = self._members
        if self._only_literals:
            return [
                i
                for i, m in enumerate(members)
                if m.literal is not None and not m.never and same_literal(m.literal[0], input)
            ]
        if self._sentinel_keys:
            observed = _observed(input, self._sentinel_keys)
            if observed is not None:
                return self._by_sentinels(*observed, constructing)
        return self._by_kind(input)

    def _by_kind(self, input: object) -> list[int]:
        kind = kind_of(input)

        def takes(m: _Member) -> bool:
            if m.literal is not None:
                return same_literal(m.literal[0], input)
            return not m.kinds.isdisjoint(kind)

        return [
            i for i, m in enumerate(self._members) if not m.never and not m.sentinels and takes(m)
        ]

    def _by_sentinels(
        self, observed: dict[Hashable, object], kind: frozenset[str], constructing: bool
    ) -> list[int]:
        """Discriminated members whose sentinels the input does not
        contradict and that one of its sentinel values selects (or, when
        ``constructing``, that has a key the input lacks), plus the other
        members taking the input's kind. A missing key is neutral."""
        selected: list[int] = []
        for i, m in enumerate(self._members):
            if m.never:
                continue
            if not m.sentinels:
                if not m.kinds.isdisjoint(kind):
                    selected.append(i)
                continue
            matched = False
            contradicted = False
            for key, literal in m.sentinels:
                value = observed.get(key, _ABSENT)
                if value is _ABSENT:
                    matched = matched or constructing
                    continue
                if same_literal(literal, value):
                    matched = True
                else:
                    contradicted = True
            if matched and not contradicted:
                selected.append(i)
        return selected


def member_expected(ast: AST) -> str:
    """How a union names a member: a mapping with literal keys as
    ``{ readonly "_tag": "A", ... }``, a tuple with literal elements as
    ``readonly [ "a", ... ]``, any other as its encoded side expects (what
    the union decodes from)."""
    side = to_encoded(ast)
    if isinstance(side, Class) and side.side == "encoded":
        side = side.shape.encoded
    if isinstance(side, Arrays):
        literals = [e for e in side.elements if isinstance(e.type, Literal)]
        if literals:
            entries = ", ".join(f"{e.type.expected()}{'?' if e.optional else ''}" for e in literals)
            return f"{'' if side.mutable else 'readonly '}[ {entries}, ... ]"
    if isinstance(side, Objects):
        literals = [p for p in side.properties if isinstance(p.type, Literal)]
        if literals:
            entries = ", ".join(
                f"readonly {_format_key(p.name)}{'?' if p.optional else ''}: {p.type.expected()}"
                for p in literals
            )
            return f"{{ {entries}, ... }}"
    return side.expected()


def _format_key(key: Hashable) -> str:
    return json_quote(key) if isinstance(key, str) else format_unknown(key)
