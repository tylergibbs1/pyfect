"""``Union``: a value of any (or exactly one) of several nodes.

Members are tried in order. Only candidates are tried: a ``Literal`` member
when the input is its literal, any other member when the input's kind
(``"string"``, ``"number"``, ...) is one it can accept. With no candidate
the issue is an empty ``AnyOf`` (``Expected "a" | 1``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal as _Literal

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import AST, issue_of
from pyfect.schema.ast._keywords import BigInt, Boolean, Never, Null, Number, String
from pyfect.schema.ast._literal import Enum, Literal, LiteralValue, same_literal
from pyfect.schema.issue import AnyOf, Issue, OneOf, reported

type UnionMode = _Literal["any_of", "one_of"]

_ALL = frozenset({"null", "string", "number", "bigint", "boolean", "array", "object"})


_VALUE_KINDS: tuple[tuple[type, frozenset[str]], ...] = (
    (type(None), frozenset({"null"})),
    (bool, frozenset({"boolean"})),
    (int, frozenset({"number", "bigint"})),
    (float, frozenset({"number"})),
    (str, frozenset({"string"})),
    (list, frozenset({"array"})),
    (tuple, frozenset({"array"})),
)
_OBJECT = frozenset({"object"})


def _kind_of(value: object) -> frozenset[str]:
    """The kinds a value is (a Python ``int`` is a number and a bigint)."""
    return next((kinds for t, kinds in _VALUE_KINDS if isinstance(value, t)), _OBJECT)


def _literal_kind(literal: LiteralValue) -> frozenset[str]:
    return (
        frozenset({"number"})
        if isinstance(literal, int | float) and not isinstance(literal, bool)
        else _kind_of(literal)
    )


_NODE_KINDS: tuple[tuple[type[AST], frozenset[str]], ...] = (
    (Null, frozenset({"null"})),
    (String, frozenset({"string"})),
    (Number, frozenset({"number"})),
    (BigInt, frozenset({"bigint"})),
    (Boolean, frozenset({"boolean"})),
)


def _kinds(ast: AST) -> frozenset[str]:
    """The kinds of input ``ast`` may accept (Effect's ``getCandidateTypes``)."""
    match ast:
        case Literal(literal=literal):
            return _literal_kind(literal)
        case Enum(side="decode" | "encoded"):
            return frozenset[str]().union(*(_literal_kind(m.value) for m in ast.enum))
        case Union(types=types):
            return frozenset[str]().union(*map(_kinds, types))
        case _:
            return next((kinds for t, kinds in _NODE_KINDS if isinstance(ast, t)), _ALL)


def _is_candidate(ast: AST, input: object) -> bool:
    if isinstance(ast, Never):
        return False
    if isinstance(ast, Literal):
        return same_literal(ast.literal, input)
    return not _kinds(ast).isdisjoint(_kind_of(input))


@dataclass(frozen=True, slots=True, eq=False)
class Union(AST):
    """A value matching a member: the first one (``mode="any_of"``), or
    exactly one (``"one_of"``, failing with ``OneOf`` when several do)."""

    types: tuple[AST, ...]
    mode: UnionMode = "any_of"
    tag = "Union"

    def get_expected(self) -> str:
        expected = (self.annotations or {}).get("expected")
        if isinstance(expected, str):
            return expected
        if not self.types:
            return "never"
        return " | ".join(dict.fromkeys(t.expected() for t in self.types))

    def _parse(self, input: object, options: ParseOptions) -> Exit[object, Issue]:
        candidates = [t for t in self.types if _is_candidate(t, input)]
        out: Success[object] | None = None
        successes: list[AST] = []
        issues: list[Issue] = []
        for member in candidates:
            match member.parse(input, options):
                case Success() as success:
                    if self.mode == "any_of":
                        return success
                    successes.append(member)
                    if out is not None:
                        return fail_exit(OneOf(self, tuple(successes), reported(input, options)))
                    out = success
                case failure:
                    issue = issue_of(failure)
                    if issue is None:
                        return failure
                    issues.append(issue)
        if out is not None:
            return out
        return fail_exit(AnyOf(self, tuple(issues), reported(input, options)))

    def _map_types(self, f: Callable[[AST], AST]) -> Union:
        types = tuple(map(f, self.types))
        if all(a is b for a, b in zip(types, self.types, strict=True)):
            return self
        return replace(self, types=types)

    def flip(self) -> Union:
        return self._map_types(lambda t: t.flip())

    def to_type(self) -> Union:
        return self._map_types(lambda t: t.to_type())
