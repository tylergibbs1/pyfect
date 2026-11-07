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
from typing import TYPE_CHECKING, Any, Generic, LiteralString, Never, TypeVar, cast, overload

from pyfect._one_or_many import one_or_many
from pyfect.schema import ast
from pyfect.schema._schema import Bottom, Codec

if TYPE_CHECKING:
    from pyfect.schema._transform import DecodeToSchema

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)
B = TypeVar("B")
J = TypeVar("J")
SD = TypeVar("SD")
SE = TypeVar("SE")

type LiteralValue = LiteralString | int | float | bool | None
"""What a literal may be: a string, a number, a boolean or ``None``."""

L_co = TypeVar("L_co", bound=LiteralValue, covariant=True)
L_ = TypeVar("L_", bound=LiteralValue)
"""Invariant: ``LiteralsSchema.pick`` takes literals of the union's type."""
E_co = TypeVar("E_co", bound=enum.Enum, covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class LiteralSchema(Bottom[L_co, L_co, Never, Never], Generic[L_co]):
    """The schema of one value; ``literal`` is that value."""

    literal: L_co

    def transform[L2: LiteralValue](self, to: L2, /) -> DecodeToSchema[L2, L_co]:
        """This literal decoded as ``to``, and ``to`` encoded back as it
        (Effect's ``Literal.transform``)."""
        # _transform imports this module.
        from pyfect.schema import getter as G
        from pyfect.schema._transform import decode_to
        from pyfect.schema.transformation import Transformation

        literal = self.literal
        transformation: Transformation[L2, L_co] = Transformation(
            G.transform(lambda _: to), G.transform(lambda _: literal)
        )
        return self.pipe(decode_to(Literal(to), transformation))


def Literal[L: LiteralValue](literal: L, /) -> LiteralSchema[L]:
    """Accepts ``literal`` only (a value of its kind: ``1`` is not ``True``
    nor ``1.0``). A non-finite number raises ``ValueError``."""
    return LiteralSchema(ast.Literal(literal), literal)


@dataclass(frozen=True, slots=True, eq=False)
class UnionSchema(Bottom[A_co, I_co, RD_co, RE_co], Generic[A_co, I_co, RD_co, RE_co]):
    """A union; ``members`` are its schemas, in order."""

    members: tuple[Codec[A_co, I_co, RD_co, RE_co], ...]

    def map_members(
        self,
        f: Callable[[tuple[Codec[A_co, I_co, RD_co, RE_co], ...]], Sequence[Codec[B, J, SD, SE]]],
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


@overload
def Union[A = Never, I = Never, RD = Never, RE = Never](
    members: list[Codec[A, I, RD, RE]] | tuple[Codec[A, I, RD, RE], ...],
    /,
    *,
    mode: ast.UnionMode = "any_of",
) -> UnionSchema[A, I, RD, RE]: ...
@overload
def Union[A = Never, I = Never, RD = Never, RE = Never](
    *members: Codec[A, I, RD, RE], mode: ast.UnionMode = "any_of"
) -> UnionSchema[A, I, RD, RE]: ...
def Union(*members: Any, mode: ast.UnionMode = "any_of") -> UnionSchema[Any, Any, Any, Any]:
    """A value of any member, tried in order (``mode="one_of"``: of exactly
    one, failing when several match). The members are given as arguments
    or, as in Effect, as one list or tuple."""
    members = one_or_many(members)
    node = ast.Union(tuple(m.__codec__().ast for m in members), mode)
    return UnionSchema(node, members)


@dataclass(frozen=True, slots=True, eq=False)
class LiteralsSchema(Bottom[L_, L_, Never, Never], Generic[L_]):
    """A union of literals; ``literals`` are the values, in order."""

    literals: tuple[L_, ...]

    @property
    def members(self) -> tuple[LiteralSchema[L_], ...]:
        return tuple(LiteralSchema(ast.Literal(lit), lit) for lit in self.literals)

    @overload
    def pick(self, literals: list[L_] | tuple[L_, ...], /) -> LiteralsSchema[L_]: ...
    @overload
    def pick(self, *literals: L_) -> LiteralsSchema[L_]: ...
    def pick(self, *literals: Any) -> LiteralsSchema[L_]:
        """The union of ``literals`` only (each one of this union's), given
        as arguments or, as in Effect, as one list or tuple."""
        return Literals(*literals)

    def map_members(
        self, f: Callable[[tuple[LiteralSchema[L_], ...]], Sequence[Codec[B, J, SD, SE]]], /
    ) -> UnionSchema[B, J, SD, SE]:
        """The union of the schemas ``f`` makes from the members."""
        return Union(*f(self.members))

    def transform[L2: LiteralValue](
        self, to: list[L2] | tuple[L2, ...], /
    ) -> UnionSchema[L2, L_, Never, Never]:
        """The union of each member decoded as the literal of ``to`` at its
        position (Effect's ``Literals.transform``); ``to`` holds one literal
        per member, else ``ValueError``."""
        members = self.members
        if len(to) != len(members):
            raise ValueError(
                f"Literals.transform takes one literal per member: {len(members)}, got {len(to)}"
            )
        return Union(*(member.transform(t) for member, t in zip(members, to, strict=True)))


@overload
def Literals[L: LiteralValue](literals: list[L] | tuple[L, ...], /) -> LiteralsSchema[L]: ...
@overload
def Literals[L: LiteralValue](*literals: L) -> LiteralsSchema[L]: ...
def Literals(*literals: Any) -> LiteralsSchema[Any]:
    """Accepts any of ``literals`` (Effect's ``Literals``, a union of
    ``Literal`` members): ``Expected "a" | "b"`` otherwise. The literals are
    given as arguments or, as in Effect, as one list or tuple."""
    literals = one_or_many(literals)
    return LiteralsSchema(ast.Union(tuple(ast.Literal(lit) for lit in literals)), literals)


@dataclass(frozen=True, slots=True, eq=False)
class EnumSchema(Bottom[E_co, str | int | float, Never, Never], Generic[E_co]):
    """The members of the Python enum ``enums``, encoded as their values."""

    enums: type[E_co]


def Enum[E: enum.Enum](enums: type[E], /) -> EnumSchema[E]:
    """Decodes a value of ``enums`` (or a member) to its member and encodes
    a member to its value (Effect's ``Enum``, whose members are their
    values). Values must be strings or finite numbers, else ``TypeError`` /
    ``ValueError``."""
    return EnumSchema(ast.Enum(enums), enums)
