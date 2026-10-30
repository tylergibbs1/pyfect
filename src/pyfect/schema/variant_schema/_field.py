"""Variant fields (Effect's ``VariantSchema.Field``): one logical field's
schema in each variant that has it."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, TypeIs, TypeVar

from pyfect.schema._schema import Codec

A_co = TypeVar("A_co", covariant=True)

type AnyCodec = Codec[Any, Any, Any, Any]


@dataclass(frozen=True, slots=True, eq=False)
class Field(Generic[A_co]):
    """A field's schema per variant; a variant missing from ``schemas``
    leaves the field out of that variant. ``A`` is the field's Type in the
    default variant (the annotation a class field must have)."""

    schemas: Mapping[str, AnyCodec]

    def pipe[B](self, f: Callable[[Field[A_co]], B], /) -> B:
        """``f(self)``: ``S.Int.pipe(model.field_only(["select"]))`` and so on."""
        return f(self)


def is_field(value: object) -> TypeIs[Field[Any]]:
    """``value`` is a variant field (Effect's ``isField``)."""
    return isinstance(value, Field)
