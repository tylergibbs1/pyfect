"""Checks that change a schema's type (``refine``, ``from_brand``), filter
groups, and reading a schema's annotations.

``refine`` and ``from_brand`` are curried for ``.pipe``: each returns an
object whose ``__call__`` keeps the schema's Encoded type and services free,
so ``.pipe`` checks the schema against them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Never, TypeIs, TypeVar, cast

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


# Explicit covariant parameters: a frozen dataclass's fields would make
# inferred ones invariant (``tests/test_schema_variance.py``).
T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=T_co)
RD_co = TypeVar("RD_co", covariant=True, default=Never)
RE_co = TypeVar("RE_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, eq=False)
class BrandSchema(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """A branded schema (Effect's ``brand``): the node of ``schema``, the
    schema it brands, unchanged; ``identifier`` names the brand."""

    schema: Bottom[object, E_co, RD_co, RE_co]
    identifier: str | None


class FromBrand[A, B]:
    """``from_brand(brand)``: apply with ``.pipe``."""

    __slots__ = ("_brand", "_identifier")

    def __init__(self, brand: Brand[A, B], identifier: str | None) -> None:
        self._brand = brand
        self._identifier = identifier

    def __call__[I, RD, RE](self, schema: Codec[A, I, RD, RE], /) -> BrandSchema[B, I, RD, RE]:
        bottom = schema.__codec__()
        checks = self._brand.checks
        checked = bottom.check(*checks) if checks else bottom
        # A brand is a ``NewType``: the checked value is the branded one.
        return BrandSchema(checked.ast, checked, self._identifier)


def from_brand[A, B](brand: Brand[A, B], /, *, identifier: str | None = None) -> FromBrand[A, B]:
    """The schema's values branded as ``B``, after ``brand``'s checks:
    ``S.Number.pipe(S.from_brand(Brand[float, Int].check(S.is_int())))``.
    A nominal brand adds no check, so it is Effect's ``brand(identifier)``.
    The result keeps the schema it brands (``.schema``) and
    ``identifier`` (``.identifier``), as Effect's ``fromBrand``."""
    return FromBrand(brand, identifier)


def make_filter_group[T](
    first: Check[T], /, *rest: Check[T], **annotations: object
) -> FilterGroup[T]:
    """Several checks as one (Effect's ``makeFilterGroup``)."""
    return FilterGroup((first, *rest), annotations or None)


def resolve_annotations(schema: Top, /) -> Annotations | None:
    """The annotations describing ``schema``: its last check's when it has
    checks, else its own; ``None`` without any."""
    return schema.__codec__().ast.resolve()


def resolve_annotations_key(schema: Top, /) -> Annotations | None:
    """The annotations of the struct key or tuple element holding
    ``schema`` (``annotate_key``); ``None`` without any (Effect's
    ``resolveAnnotationsKey``)."""
    return schema.__codec__().ast.key_annotations
