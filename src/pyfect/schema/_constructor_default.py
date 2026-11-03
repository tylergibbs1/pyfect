"""Constructor defaults (Effect's ``withConstructorDefault`` and ``tag``): the
value ``make`` gives a missing struct key or tuple element. Decoding and
encoding never use it::

    class A(TypedDict):
        _tag: Literal["A"]
        n: float

    schema = S.Struct(A, _tag=S.tag("A"))
    schema.make({"n": 1})  # {"_tag": "A", "n": 1}
    S.Number.pipe(S.with_constructor_default(fx.succeed(0.0)))

The default runs on each ``make`` that needs it, and its value is made in
turn (its own missing keys take their defaults). A default that fails with
an issue fails the ``make``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.effect import succeed
from pyfect.schema import ast
from pyfect.schema._literals import Literal
from pyfect.schema._literals import LiteralValue as LiteralInput
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema.issue import Issue

# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)
T = TypeVar("T")


@dataclass(frozen=True, slots=True, eq=False)
class WithConstructorDefault(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """A schema whose missing key or element ``make`` fills with
    ``default``'s value."""

    default: Effect[T_co, Issue]


class ConstructorDefault(Generic[T]):
    """``with_constructor_default(default)``: apply with ``.pipe`` to a
    schema whose Type is exactly ``default``'s (``T`` is invariant, so a
    default of another type is a type error)."""

    __slots__ = ("_default",)

    def __init__(self, default: Effect[T, Issue]) -> None:
        self._default = default

    @overload
    def __call__[S, E, RD, RE](
        self: ConstructorDefault[Never], schema: Codec[S, E, RD, RE], /
    ) -> WithConstructorDefault[S, E, RD, RE]: ...
    @overload
    def __call__[E, RD, RE](
        self, schema: Codec[T, E, RD, RE], /
    ) -> WithConstructorDefault[T, E, RD, RE]: ...
    def __call__(
        self, schema: Codec[Any, Any, Any, Any], /
    ) -> WithConstructorDefault[Any, Any, Any, Any]:
        # A default that never succeeds (``fx.fail(issue)``) suits any schema.
        node = ast.with_constructor_default(schema.__codec__().ast, self._default)
        return WithConstructorDefault(node, self._default)


def with_constructor_default[T](default: Effect[T, Issue], /) -> ConstructorDefault[T]:
    """The schema, its missing struct key or tuple element filled by
    ``default``'s value in ``make`` / ``make_option`` / ``make_effect``
    (Effect's ``withConstructorDefault``):
    ``S.String.pipe(S.with_constructor_default(fx.succeed("a")))``.
    ``default`` may be asynchronous (then use ``make_effect``) and may fail
    with an ``Issue``."""
    require_effect(default, "default")
    return ConstructorDefault(default)


def tag[L: LiteralInput](literal: L, /) -> WithConstructorDefault[L, L, Never, Never]:
    """``Literal(literal)`` filled in by ``make`` (Effect's ``tag``): a
    tagged struct's ``"_tag"`` field, ``S.Struct(A, _tag=S.tag("A"))``."""
    return with_constructor_default(succeed(literal))(Literal(literal))
