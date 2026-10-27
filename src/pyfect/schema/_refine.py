"""Checks that change a schema's type (``refine``, ``from_brand``), filter
groups, and reading a schema's annotations.

``refine`` and ``from_brand`` are curried for ``.pipe``: each returns an
object whose ``__call__`` keeps the schema's Encoded type and services free,
so ``.pipe`` checks the schema against them."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeIs, cast

from pyfect.schema._schema import Bottom, Codec, Top
from pyfect.schema.ast import Annotations, Check, Filter, FilterGroup, make_filter_by_guard

if TYPE_CHECKING:
    from pyfect.brand import Brand


class Refine[A, B]:
    """``refine(guard)``: apply with ``.pipe``."""

    __slots__ = ("_filter",)

    def __init__(self, filter: Filter[A]) -> None:
        self._filter = filter

    def __call__[I, RD, RE](self, schema: Codec[A, I, RD, RE], /) -> Bottom[B, I, RD, RE]:
        checked = schema.__codec__().check(self._filter)
        # The guard holds for every value the checked schema gives.
        return cast("Bottom[B, I, RD, RE]", Bottom(checked.ast))


def refine[A, B](guard: Callable[[A], TypeIs[B]], /, **annotations: object) -> Refine[A, B]:
    """Narrow a schema's type to what ``guard`` accepts, checking it as the
    last step; a value it rejects fails with ``"Expected <expected>"``
    (``expected=`` annotation, else ``<filter>``) and stops the checks."""
    return Refine(make_filter_by_guard(guard, annotations or None))


class FromBrand[A, B]:
    """``from_brand(brand)``: apply with ``.pipe``."""

    __slots__ = ("_brand",)

    def __init__(self, brand: Brand[A, B]) -> None:
        self._brand = brand

    def __call__[I, RD, RE](self, schema: Codec[A, I, RD, RE], /) -> Bottom[B, I, RD, RE]:
        bottom = schema.__codec__()
        checks = self._brand.checks
        checked = bottom.check(*checks) if checks else bottom
        # A brand is a ``NewType``: the checked value is the branded one.
        return cast("Bottom[B, I, RD, RE]", Bottom(checked.ast))


def from_brand[A, B](brand: Brand[A, B], /) -> FromBrand[A, B]:
    """The schema's values branded as ``B``, after ``brand``'s checks:
    ``S.Number.pipe(S.from_brand(Brand[float, Int].check(S.is_int())))``.
    A nominal brand adds no check."""
    return FromBrand(brand)


def make_filter_group[T](
    first: Check[T], /, *rest: Check[T], **annotations: object
) -> FilterGroup[T]:
    """Several checks as one (Effect's ``makeFilterGroup``)."""
    return FilterGroup((first, *rest), annotations or None)


def resolve_annotations(schema: Top, /) -> Annotations | None:
    """The annotations describing ``schema``: its last check's when it has
    checks, else its own; ``None`` without any."""
    return schema.__codec__().ast.resolve()
