"""Constructor defaults for variant fields (``S.with_constructor_default``,
and Effect's ``VariantSchema.Overrideable``): a value a variant struct's
``make`` fills in for a missing key. Decoding never uses it: a missing key
stays an error there."""

from __future__ import annotations

from typing import Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.schema._constructor_default import WithConstructorDefault, with_constructor_default
from pyfect.schema._schema import Codec


def Overrideable[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /, *, default_value: Effect[T, Never, Never]
) -> WithConstructorDefault[T, E, RD, RE]:
    """``schema`` with ``default_value`` as its constructor default, for
    values the application makes (timestamps) but a caller may set with
    ``override`` (Effect's ``Overrideable``)."""
    require_effect(default_value, "default_value")
    return with_constructor_default(default_value)(schema)


def override[A](value: A, /) -> A:
    """An explicit value for an ``Overrideable`` field (Effect's
    ``Override``). Python has no phantom brand for any ``A``, so it marks the
    intent and returns ``value``."""
    return value
