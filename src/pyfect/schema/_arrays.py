"""Sequence schemas: ``Tuple``, ``TupleWithRest``, ``Array``, ``List``,
``NonEmptyArray``, ``UniqueArray``.

Each takes a ``list`` or a ``tuple``. ``Tuple`` and the arrays decode to a
new ``tuple`` (Effect's readonly arrays); ``List`` decodes to a ``list``
(Effect's ``mutable(Array(...))``). A tuple's element wrapped in
``optional_key`` may be missing, at the end only.

Tuples are typed exactly up to eight elements; with an ``optional_key``
element, or more elements, the Type is ``tuple[A, ...]`` of the elements'
Types joined.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, cast, overload

from pyfect.schema import ast
from pyfect.schema._checks_size import is_unique
from pyfect.schema._schema import Bottom, Codec

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
TT_co = TypeVar("TT_co", bound=tuple[object, ...], covariant=True)
TE_co = TypeVar("TE_co", bound=tuple[object, ...], covariant=True)
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)
B = TypeVar("B")
J = TypeVar("J")
SD = TypeVar("SD")
SE = TypeVar("SE")


@dataclass(frozen=True, slots=True)
class OptionalKey(Generic[A_co, I_co, RD_co, RE_co]):
    """A tuple element that may be missing (Effect's ``optionalKey``)."""

    schema: Codec[A_co, I_co, RD_co, RE_co]


def optional_key[A, I, RD, RE](
    schema: Codec[A, I, RD, RE] | OptionalKey[A, I, RD, RE], /
) -> OptionalKey[A, I, RD, RE]:
    """``schema`` as a tuple element that may be missing (an optional one
    stays as it is); it must come after every required element (else
    ``ValueError``)."""
    return schema if isinstance(schema, OptionalKey) else OptionalKey(schema)


type TupleElement[RD = object, RE = object] = (
    Codec[object, object, RD, RE] | OptionalKey[object, object, RD, RE]
)
"""What a tuple holds: an element's schema, or one wrapped in ``optional_key``."""


def _element(element: TupleElement) -> ast.Element:
    if isinstance(element, OptionalKey):
        return ast.Element(element.schema.__codec__().ast, optional=True)
    return ast.Element(element.__codec__().ast)


@dataclass(frozen=True, slots=True, eq=False)
class TupleSchema(Bottom[TT_co, TE_co, RD_co, RE_co], Generic[TT_co, TE_co, RD_co, RE_co]):
    """A tuple; ``elements`` are its schemas, in order."""

    elements: tuple[TupleElement[RD_co, RE_co], ...]

    def map_elements(
        self,
        f: Callable[
            [tuple[TupleElement[RD_co, RE_co], ...]],
            Sequence[Codec[B, J, SD, SE] | OptionalKey[B, J, SD, SE]],
        ],
        /,
        *,
        unsafe_preserve_checks: bool = False,
    ) -> TupleSchema[tuple[B, ...], tuple[J, ...], SD, SE]:
        """The tuple of the elements ``f`` makes from these (Effect's
        ``mapElements``). Its checks are dropped unless
        ``unsafe_preserve_checks`` (they may not hold for the new elements)."""
        elements = tuple(f(self.elements))
        checks = self.ast.checks if unsafe_preserve_checks else None
        node = ast.Arrays(tuple(map(_element, elements)), checks=checks)
        return TupleSchema(node, elements)


type _Tuple[T: tuple[object, ...], E: tuple[object, ...], RD, RE] = TupleSchema[T, E, RD, RE]


@overload
def Tuple() -> _Tuple[tuple[()], tuple[()], Never, Never]: ...
@overload
def Tuple[A1, I1, RD, RE](e1: Codec[A1, I1, RD, RE], /) -> _Tuple[tuple[A1], tuple[I1], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, RD, RE](
    e1: Codec[A1, I1, RD, RE], e2: Codec[A2, I2, RD, RE], /
) -> _Tuple[tuple[A1, A2], tuple[I1, I2], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, RD, RE](
    e1: Codec[A1, I1, RD, RE], e2: Codec[A2, I2, RD, RE], e3: Codec[A3, I3, RD, RE], /
) -> _Tuple[tuple[A1, A2, A3], tuple[I1, I2, I3], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4, RD, RE](
    e1: Codec[A1, I1, RD, RE],
    e2: Codec[A2, I2, RD, RE],
    e3: Codec[A3, I3, RD, RE],
    e4: Codec[A4, I4, RD, RE],
    /,
) -> _Tuple[tuple[A1, A2, A3, A4], tuple[I1, I2, I3, I4], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4, A5, I5, RD, RE](
    e1: Codec[A1, I1, RD, RE],
    e2: Codec[A2, I2, RD, RE],
    e3: Codec[A3, I3, RD, RE],
    e4: Codec[A4, I4, RD, RE],
    e5: Codec[A5, I5, RD, RE],
    /,
) -> _Tuple[tuple[A1, A2, A3, A4, A5], tuple[I1, I2, I3, I4, I5], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4, A5, I5, A6, I6, RD, RE](
    e1: Codec[A1, I1, RD, RE],
    e2: Codec[A2, I2, RD, RE],
    e3: Codec[A3, I3, RD, RE],
    e4: Codec[A4, I4, RD, RE],
    e5: Codec[A5, I5, RD, RE],
    e6: Codec[A6, I6, RD, RE],
    /,
) -> _Tuple[tuple[A1, A2, A3, A4, A5, A6], tuple[I1, I2, I3, I4, I5, I6], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4, A5, I5, A6, I6, A7, I7, RD, RE](
    e1: Codec[A1, I1, RD, RE],
    e2: Codec[A2, I2, RD, RE],
    e3: Codec[A3, I3, RD, RE],
    e4: Codec[A4, I4, RD, RE],
    e5: Codec[A5, I5, RD, RE],
    e6: Codec[A6, I6, RD, RE],
    e7: Codec[A7, I7, RD, RE],
    /,
) -> _Tuple[tuple[A1, A2, A3, A4, A5, A6, A7], tuple[I1, I2, I3, I4, I5, I6, I7], RD, RE]: ...
@overload
def Tuple[A1, I1, A2, I2, A3, I3, A4, I4, A5, I5, A6, I6, A7, I7, A8, I8, RD, RE](
    e1: Codec[A1, I1, RD, RE],
    e2: Codec[A2, I2, RD, RE],
    e3: Codec[A3, I3, RD, RE],
    e4: Codec[A4, I4, RD, RE],
    e5: Codec[A5, I5, RD, RE],
    e6: Codec[A6, I6, RD, RE],
    e7: Codec[A7, I7, RD, RE],
    e8: Codec[A8, I8, RD, RE],
    /,
) -> _Tuple[
    tuple[A1, A2, A3, A4, A5, A6, A7, A8], tuple[I1, I2, I3, I4, I5, I6, I7, I8], RD, RE
]: ...
@overload
def Tuple[A, I, RD, RE](
    *elements: Codec[A, I, RD, RE] | OptionalKey[A, I, RD, RE],
) -> _Tuple[tuple[A, ...], tuple[I, ...], RD, RE]: ...
def Tuple(*elements: TupleElement) -> TupleSchema[Any, Any, Any, Any]:
    """A tuple of one value per element (Effect's ``Tuple``): a missing
    element is a ``Missing key`` issue, an extra position ``Expected no
    excess property``."""
    return TupleSchema(ast.Arrays(tuple(map(_element, elements))), elements)


@dataclass(frozen=True, slots=True, eq=False)
class TupleWithRestSchema(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """A tuple's elements, then ``rest[0]`` any number of times, then the
    other ``rest`` schemas."""

    schema: TupleSchema[Any, Any, RD_co, RE_co]
    rest: tuple[Codec[object, object, RD_co, RE_co], ...]


type _Rest[T, E, RD, RE] = TupleWithRestSchema[T, E, RD, RE]


@overload
def TupleWithRest[B, J, RD, RE](
    schema: TupleSchema[tuple[()], tuple[()], RD, RE], rest: Codec[B, J, RD, RE], /
) -> _Rest[tuple[B, ...], tuple[J, ...], RD, RE]: ...
@overload
def TupleWithRest[A1, I1, B, J, RD, RE](
    schema: TupleSchema[tuple[A1], tuple[I1], RD, RE], rest: Codec[B, J, RD, RE], /
) -> _Rest[tuple[A1, *tuple[B, ...]], tuple[I1, *tuple[J, ...]], RD, RE]: ...
@overload
def TupleWithRest[A1, I1, A2, I2, B, J, RD, RE](
    schema: TupleSchema[tuple[A1, A2], tuple[I1, I2], RD, RE], rest: Codec[B, J, RD, RE], /
) -> _Rest[tuple[A1, A2, *tuple[B, ...]], tuple[I1, I2, *tuple[J, ...]], RD, RE]: ...
@overload
def TupleWithRest[A1, I1, A2, I2, A3, I3, B, J, RD, RE](
    schema: TupleSchema[tuple[A1, A2, A3], tuple[I1, I2, I3], RD, RE],
    rest: Codec[B, J, RD, RE],
    /,
) -> _Rest[tuple[A1, A2, A3, *tuple[B, ...]], tuple[I1, I2, I3, *tuple[J, ...]], RD, RE]: ...
@overload
def TupleWithRest[B, J, C, K, RD, RE](
    schema: TupleSchema[tuple[()], tuple[()], RD, RE],
    rest: Codec[B, J, RD, RE],
    last: Codec[C, K, RD, RE],
    /,
) -> _Rest[tuple[*tuple[B, ...], C], tuple[*tuple[J, ...], K], RD, RE]: ...
@overload
def TupleWithRest[A1, I1, B, J, C, K, RD, RE](
    schema: TupleSchema[tuple[A1], tuple[I1], RD, RE],
    rest: Codec[B, J, RD, RE],
    last: Codec[C, K, RD, RE],
    /,
) -> _Rest[tuple[A1, *tuple[B, ...], C], tuple[I1, *tuple[J, ...], K], RD, RE]: ...
@overload
def TupleWithRest[A1, I1, A2, I2, B, J, C, K, RD, RE](
    schema: TupleSchema[tuple[A1, A2], tuple[I1, I2], RD, RE],
    rest: Codec[B, J, RD, RE],
    last: Codec[C, K, RD, RE],
    /,
) -> _Rest[tuple[A1, A2, *tuple[B, ...], C], tuple[I1, I2, *tuple[J, ...], K], RD, RE]: ...
@overload
def TupleWithRest[A, I, RD, RE](
    schema: TupleSchema[tuple[A, ...], tuple[I, ...], RD, RE],
    rest: Codec[A, I, RD, RE],
    /,
    *post: Codec[A, I, RD, RE],
) -> _Rest[tuple[A, ...], tuple[I, ...], RD, RE]: ...
def TupleWithRest(
    schema: TupleSchema[Any, Any, Any, Any],
    rest: Codec[Any, Any, Any, Any],
    /,
    *post: Codec[Any, Any, Any, Any],
) -> TupleWithRestSchema[Any, Any, Any, Any]:
    """``schema``'s elements, then any number of ``rest`` values, then one
    value of each ``post`` schema (Effect's ``TupleWithRest(schema, [rest,
    ...post])``). Its checks are kept. The rest schemas are never optional
    (their type is ``Codec``), and after an optional element no ``post``
    schema may follow (``ValueError``)."""
    rests = (rest, *post)
    node = cast("ast.Arrays", schema.ast)
    arrays = ast.Arrays(
        node.elements,
        tuple(r.__codec__().ast for r in rests),
        node.mutable,
        checks=node.checks,
    )
    return TupleWithRestSchema(arrays, schema, rests)


@dataclass(frozen=True, slots=True, eq=False)
class ArraySchema(
    Bottom[T_co, Sequence[I_co], RD_co, RE_co], Generic[T_co, A_co, I_co, RD_co, RE_co]
):
    """A sequence of ``value``'s values: ``T`` is ``tuple[A, ...]``
    (``Array``), ``tuple[A, *tuple[A, ...]]`` (``NonEmptyArray``) or
    ``list[A]`` (``List``)."""

    value: Codec[A_co, I_co, RD_co, RE_co]


def Array[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> ArraySchema[tuple[A, ...], A, I, RD, RE]:
    """Any number of ``value``'s values, as a ``tuple`` (Effect's
    ``Array``, a readonly array)."""
    return ArraySchema(ast.Arrays((), (value.__codec__().ast,)), value)


def List[A, I, RD, RE](value: Codec[A, I, RD, RE], /) -> ArraySchema[list[A], A, I, RD, RE]:
    """Any number of ``value``'s values, as a ``list`` (Effect's
    ``mutable(Array(...))``)."""
    return ArraySchema(ast.Arrays((), (value.__codec__().ast,), mutable=True), value)


def NonEmptyArray[A, I, RD, RE](
    value: Codec[A, I, RD, RE], /
) -> ArraySchema[tuple[A, *tuple[A, ...]], A, I, RD, RE]:
    """One or more of ``value``'s values, as a ``tuple``: an empty input is
    ``Missing key`` at ``[0]``."""
    node = value.__codec__().ast
    return ArraySchema(ast.Arrays((ast.Element(node),), (node,)), value)


def UniqueArray[A, I, RD, RE](
    value: Codec[A, I, RD, RE], /
) -> ArraySchema[tuple[A, ...], A, I, RD, RE]:
    """``Array(value)`` whose values are all different (``is_unique``)."""
    return Array(value).check(is_unique())
