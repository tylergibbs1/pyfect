"""Constructor defaults (Effect's ``withConstructorDefault`` and
``VariantSchema.Overrideable``): a value a variant struct's ``make`` fills
in for a missing key. Decoding never uses it: a missing key stays an
error there."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Never, TypeVar

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.schema._schema import Bottom, Codec

T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True, eq=False)
class WithConstructorDefault(Bottom[T_co, E_co, RD_co, RE_co], Generic[T_co, E_co, RD_co, RE_co]):
    """A schema whose missing key ``make`` fills with ``default``'s value."""

    default: Effect[T_co, Never, Never]


def with_constructor_default[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], default: Effect[T, Never, Never], /
) -> WithConstructorDefault[T, E, RD, RE]:
    """``schema``, its key filled by ``default`` when a variant struct's
    ``make`` / ``make_effect`` does not get it (Effect's
    ``withConstructorDefault``)."""
    require_effect(default, "default")
    return WithConstructorDefault(schema.__codec__().ast, default)


def Overrideable[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /, *, default_value: Effect[T, Never, Never]
) -> WithConstructorDefault[T, E, RD, RE]:
    """``schema`` with ``default_value`` as its constructor default, for
    values the application makes (timestamps) but a caller may set with
    ``override`` (Effect's ``Overrideable``)."""
    require_effect(default_value, "default_value")
    return with_constructor_default(schema, default_value)


def override[A](value: A, /) -> A:
    """An explicit value for an ``Overrideable`` field (Effect's
    ``Override``). Python has no phantom brand for any ``A``, so it marks the
    intent and returns ``value``."""
    return value
