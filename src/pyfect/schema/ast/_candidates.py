"""Which members of a union may take an input (Effect's candidate index).

A member is a candidate by the input's kind (``"string"``, ``"object"``,
...), a ``Literal`` member only for its literal. Members that are mappings
with required literal keys (``"_tag": "A"``, Effect's sentinels) are
discriminated: an input mapping picks them by the values it holds under
those keys, before any member is parsed.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from pyfect.logger._text import format_unknown, json_quote
from pyfect.schema.ast._base import AST
from pyfect.schema.ast._class import Class
from pyfect.schema.ast._keywords import BigInt, Boolean, Never, Null, Number, String, Unknown
from pyfect.schema.ast._literal import Enum, Literal, LiteralValue, same_literal
from pyfect.schema.ast._objects import Objects
from pyfect.schema.ast._suspend import Suspend

ALL = frozenset({"null", "string", "number", "bigint", "boolean", "array", "object"})
OBJECT = frozenset({"object"})

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


def kinds(ast: AST) -> frozenset[str]:
    """The kinds of input ``ast`` may accept (Effect's ``getCandidateTypes``)."""
    members = _members(ast)
    if members is not None:
        return frozenset[str]().union(*map(kinds, members))
    match ast:
        case Literal(literal=literal):
            return _literal_kind(literal)
        case Enum(side="decode" | "encoded"):
            return frozenset[str]().union(*(_literal_kind(m.value) for m in ast.enum))
        case Objects() | Class(side="decode" | "encoded"):
            return OBJECT
        case _:
            return next((kinds for t, kinds in _NODE_KINDS if isinstance(ast, t)), ALL)


type Sentinel = tuple[Hashable, LiteralValue]
"""A required key and the literal it must hold."""


def _input_side(ast: AST) -> AST:
    """The node of what the member takes as input (Effect's ``toCandidate``).
    A suspended member takes anything: selecting candidates never makes it
    (it may be the union itself)."""
    return Unknown() if isinstance(ast, Suspend) else ast.flip().to_type()


def sentinels(ast: AST) -> tuple[Sentinel, ...]:
    """The required literal keys of a mapping node (Effect's
    ``collectSentinels``); a union's are those all its members share."""
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

    def __call__(self, input: object) -> list[int]:
        members = self._members
        if self._only_literals:
            return [
                i
                for i, m in enumerate(members)
                if m.literal is not None and not m.never and same_literal(m.literal[0], input)
            ]
        if not self._sentinel_keys or not isinstance(input, Mapping):
            return self._by_kind(input)
        return self._by_sentinels(cast("Mapping[object, object]", input))

    def _by_kind(self, input: object) -> list[int]:
        kind = kind_of(input)

        def takes(m: _Member) -> bool:
            if m.literal is not None:
                return same_literal(m.literal[0], input)
            return not m.kinds.isdisjoint(kind)

        return [
            i for i, m in enumerate(self._members) if not m.never and not m.sentinels and takes(m)
        ]

    def _by_sentinels(self, input: Mapping[object, object]) -> list[int]:
        """Discriminated members whose sentinels the input does not
        contradict and that one of its sentinel values selects, plus the
        other members taking a mapping. A missing key is neutral."""
        observed = {key: input[key] for key in self._sentinel_keys if key in input}
        selected: list[int] = []
        for i, m in enumerate(self._members):
            if m.never:
                continue
            if not m.sentinels:
                if not m.kinds.isdisjoint(OBJECT):
                    selected.append(i)
                continue
            matched = False
            contradicted = False
            for key, literal in m.sentinels:
                value = observed.get(key, _ABSENT)
                if value is _ABSENT:
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
    ``{ readonly "_tag": "A", ... }``, any other as it expects itself."""
    side = _input_side(ast)
    if isinstance(side, Class) and side.side == "encoded":
        side = side.shape.encoded
    if isinstance(side, Objects):
        literals = [p for p in side.properties if isinstance(p.type, Literal)]
        if literals:
            entries = ", ".join(
                f"readonly {_format_key(p.name)}{'?' if p.optional else ''}: {p.type.expected()}"
                for p in literals
            )
            return f"{{ {entries}, ... }}"
    return ast.expected()


def _format_key(key: Hashable) -> str:
    return json_quote(key) if isinstance(key, str) else format_unknown(key)
