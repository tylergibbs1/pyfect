"""The variant toolkit (Effect's ``VariantSchema.make``): structs, fields,
classes and unions over one fixed set of variants."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, overload

from pyfect.schema._literals import Union as SchemaUnion
from pyfect.schema._literals import UnionSchema
from pyfect.schema._schema import Codec, is_schema
from pyfect.schema.variant_schema._class import Class as VariantClass
from pyfect.schema.variant_schema._class import VariantAttribute
from pyfect.schema.variant_schema._field import AnyCodec
from pyfect.schema.variant_schema._field import Field as VariantField
from pyfect.schema.variant_schema._struct import Definition, HasVariants, extract
from pyfect.schema.variant_schema._struct import Struct as VariantStruct


@dataclass(frozen=True, slots=True, eq=False)
class VariantUnionSchema(UnionSchema[Any, Any, Any, Any]):
    """A union of the members' default variants (Effect's
    ``VariantSchema.Union``); ``variants[name]`` is the union of their
    ``name`` variants."""

    variants: Mapping[str, UnionSchema[Any, Any, Any, Any]]


class FieldOnly:
    """``field_only(keys)(schema)``: ``schema`` in the ``keys`` variants."""

    __slots__ = ("keys",)

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys

    def __call__[A](self, schema: Codec[A, Any, Any, Any], /) -> VariantField[A]:
        return VariantField(dict.fromkeys(self.keys, schema))


class FieldEvolve:
    """``field_evolve(mapping)(self)``: each named variant's schema mapped."""

    __slots__ = ("mapping", "variants")

    def __init__(
        self, variants: tuple[str, ...], mapping: Mapping[str, Callable[[AnyCodec], AnyCodec]]
    ) -> None:
        self.variants = variants
        self.mapping = mapping

    def __call__(self, field: VariantField[Any] | AnyCodec, /) -> VariantField[Any]:
        schemas = (
            field.schemas
            if isinstance(field, VariantField)
            else dict.fromkeys(self.variants, field)
        )
        evolved = {
            variant: self.mapping[variant](schema) if variant in self.mapping else schema
            for variant, schema in schemas.items()
        }
        return VariantField(evolved)


@dataclass(frozen=True, slots=True, eq=False)
class VariantSchema:
    """A toolkit for ``variants``, whose ``default_variant`` is the schema
    of its classes. Make one with ``make``."""

    variants: tuple[str, ...]
    default_variant: str
    Class: type[VariantClass] = field(init=False)

    def __post_init__(self) -> None:
        attributes: dict[str, object] = {v: VariantAttribute(v) for v in self.variants}
        base = type("Class", (VariantClass,), {"__variant_set__": self, **attributes})
        object.__setattr__(self, "Class", base)

    def _known(self, keys: Sequence[str]) -> tuple[str, ...]:
        if isinstance(keys, str):
            raise TypeError("variant keys are a sequence of names, not a string")
        unknown = [key for key in keys if key not in self.variants]
        if unknown:
            raise ValueError(f"unknown variant {unknown[0]!r} (variants: {self.variants})")
        return tuple(keys)

    def Struct(self, fields: Mapping[str, Definition | None], /) -> VariantStruct:
        """Field definitions (Effect's ``Struct``); ``None`` leaves a key out."""
        for value in fields.values():
            if isinstance(value, VariantField):
                self._known(list(value.schemas))
        return VariantStruct(fields)

    def Field(self, **schemas: AnyCodec | None) -> VariantField[Any]:
        """A field's schema per variant; ``None`` or a missing variant
        leaves it out of that variant."""
        self._known(list(schemas))
        return VariantField({k: v for k, v in schemas.items() if v is not None})

    def field_only(self, keys: Sequence[str], /) -> FieldOnly:
        """A field in the ``keys`` variants only (Effect's ``FieldOnly``)."""
        return FieldOnly(self._known(keys))

    def field_except(self, keys: Sequence[str], /) -> FieldOnly:
        """A field in every variant but ``keys`` (Effect's ``FieldExcept``)."""
        excluded = self._known(keys)
        return FieldOnly(tuple(v for v in self.variants if v not in excluded))

    @overload
    def field_evolve(
        self, mapping: Mapping[str, Callable[[AnyCodec], AnyCodec]], /
    ) -> FieldEvolve: ...
    @overload
    def field_evolve(
        self,
        field: VariantField[Any] | AnyCodec,
        mapping: Mapping[str, Callable[[AnyCodec], AnyCodec]],
        /,
    ) -> VariantField[Any]: ...
    def field_evolve(self, *args: Any) -> FieldEvolve | VariantField[Any]:
        """Each named variant's schema of a field (or of a schema in every
        variant) mapped (Effect's ``fieldEvolve``); a variant the field
        lacks stays out."""
        if len(args) == 1:
            return FieldEvolve(self.variants, self._mapping(args[0]))
        return FieldEvolve(self.variants, self._mapping(args[1]))(args[0])

    def _mapping(
        self, mapping: Mapping[str, Callable[[AnyCodec], AnyCodec]]
    ) -> Mapping[str, Callable[[AnyCodec], AnyCodec]]:
        self._known(list(mapping))
        return mapping

    def Union(self, members: Sequence[HasVariants], /) -> VariantUnionSchema:
        """The union of the members' default variants (a class is its own),
        with ``variants`` holding the union of each variant."""
        defaults = [
            m if is_schema(m) else extract(m, self.default_variant, is_default=True)
            for m in members
        ]
        union = SchemaUnion(*defaults)
        variants = {v: SchemaUnion(*(extract(m, v) for m in members)) for v in self.variants}
        return VariantUnionSchema(union.ast, union.members, variants)

    def extract(self, struct: HasVariants, variant: str, /) -> Any:
        """``variant``'s struct schema; the default variant of a class is
        the class itself."""
        self._known([variant])
        return extract(struct, variant, is_default=variant == self.default_variant)


def make(*, variants: Sequence[str], default_variant: str) -> VariantSchema:
    """A toolkit for ``variants`` (Effect's ``VariantSchema.make``)."""
    if isinstance(variants, str) or default_variant not in variants:
        raise ValueError(f"default_variant {default_variant!r} is not one of {variants!r}")
    return VariantSchema(tuple(variants), default_variant)


__all__ = ["FieldEvolve", "FieldOnly", "VariantSchema", "VariantUnionSchema", "make"]
