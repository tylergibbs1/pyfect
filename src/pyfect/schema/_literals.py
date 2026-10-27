"""Exact-value schemas: ``Literal``, ``Literals``, ``Enum``, and the
``Union`` that ``Literals`` is.

``Literals("a", "b")`` keeps string literals in its type
(``LiteralsSchema[Literal["a", "b"]]``); an all-``int`` call widens to
``int`` and needs the expected type written out
(``x: S.LiteralsSchema[Literal[1, 2]] = S.Literals(1, 2)``).
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import LiteralString, Never, cast

from pyfect.schema import ast
from pyfect.schema._schema import Bottom, Codec

type LiteralValue = LiteralString | int | float | bool | None
"""What a literal may be: a string, a number, a boolean or ``None``."""


@dataclass(frozen=True, slots=True, eq=False)
class LiteralSchema[L: LiteralValue](Bottom[L, L, Never, Never]):
    """The schema of one value; ``literal`` is that value."""

    literal: L


def Literal[L: LiteralValue](literal: L, /) -> LiteralSchema[L]:
    """Accepts ``literal`` only (a value of its kind: ``1`` is not ``True``
    nor ``1.0``). A non-finite number raises ``ValueError``."""
    return LiteralSchema(ast.Literal(literal), literal)


@dataclass(frozen=True, slots=True, eq=False)
class UnionSchema[A, I, RD, RE](Bottom[A, I, RD, RE]):
    """A union; ``members`` are its schemas, in order."""

    members: tuple[Codec[A, I, RD, RE], ...]

    def map_members[B, J, SD, SE](
        self,
        f: Callable[[tuple[Codec[A, I, RD, RE], ...]], Sequence[Codec[B, J, SD, SE]]],
        /,
        *,
        unsafe_preserve_checks: bool = False,
    ) -> UnionSchema[B, J, SD, SE]:
        """The union, with the same mode, of the schemas ``f`` makes from the
        members. Its checks are dropped unless ``unsafe_preserve_checks``
        (they may not hold for the new members)."""
        members = tuple(f(self.members))
        union = cast("ast.Union", self.ast)
        checks = union.checks if unsafe_preserve_checks else None
        node = ast.Union(tuple(m.__codec__().ast for m in members), union.mode, checks=checks)
        return UnionSchema(node, members)


def Union[A, I, RD, RE](
    *members: Codec[A, I, RD, RE], mode: ast.UnionMode = "any_of"
) -> UnionSchema[A, I, RD, RE]:
    """A value of any member, tried in order (``mode="one_of"``: of exactly
    one, failing when several match)."""
    node = ast.Union(tuple(m.__codec__().ast for m in members), mode)
    return UnionSchema(node, members)


@dataclass(frozen=True, slots=True, eq=False)
class LiteralsSchema[L: LiteralValue](Bottom[L, L, Never, Never]):
    """A union of literals; ``literals`` are the values, in order."""

    literals: tuple[L, ...]

    @property
    def members(self) -> tuple[LiteralSchema[L], ...]:
        return tuple(LiteralSchema(ast.Literal(lit), lit) for lit in self.literals)

    def pick(self, *literals: L) -> LiteralsSchema[L]:
        """The union of ``literals`` only (each one of this union's)."""
        return Literals(*literals)

    def map_members[A, I, RD, RE](
        self, f: Callable[[tuple[LiteralSchema[L], ...]], Sequence[Codec[A, I, RD, RE]]], /
    ) -> UnionSchema[A, I, RD, RE]:
        """The union of the schemas ``f`` makes from the members."""
        return Union(*f(self.members))


def Literals[L: LiteralValue](*literals: L) -> LiteralsSchema[L]:
    """Accepts any of ``literals`` (Effect's ``Literals``, a union of
    ``Literal`` members): ``Expected "a" | "b"`` otherwise."""
    return LiteralsSchema(ast.Union(tuple(ast.Literal(lit) for lit in literals)), literals)


@dataclass(frozen=True, slots=True, eq=False)
class EnumSchema[E: enum.Enum](Bottom[E, str | int | float, Never, Never]):
    """The members of the Python enum ``enums``, encoded as their values."""

    enums: type[E]


def Enum[E: enum.Enum](enums: type[E], /) -> EnumSchema[E]:
    """Decodes a value of ``enums`` (or a member) to its member and encodes
    a member to its value (Effect's ``Enum``, whose members are their
    values). Values must be strings or finite numbers, else ``TypeError`` /
    ``ValueError``."""
    return EnumSchema(ast.Enum(enums), enums)
