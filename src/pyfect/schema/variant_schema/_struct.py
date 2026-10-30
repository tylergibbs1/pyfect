"""Variant structs (Effect's ``VariantSchema.Struct`` and ``extract``):
field definitions from which one struct schema per variant is extracted.

A definition is a schema (in every variant), a ``Field`` (in the variants
it names), a nested variant struct or variant class (extracted with the
same variant), or ``None`` (left out). Extraction is cached on the struct
itself, so a class never reuses its base's variants.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeIs, TypeVar, Unpack, cast, runtime_checkable

from pyfect._core import Effect
from pyfect.effect import succeed
from pyfect.option import Option
from pyfect.run import run_sync
from pyfect.schema import ast
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, is_schema
from pyfect.schema._struct import StructSchema
from pyfect.schema.issue import Issue
from pyfect.schema.variant_schema._defaults import WithConstructorDefault
from pyfect.schema.variant_schema._field import AnyCodec, Field

TD_co = TypeVar("TD_co", bound=Mapping[str, object], covariant=True)

_AnyBottom = Bottom[Any, Any, Any, Any]


@dataclass(frozen=True, slots=True, eq=False)
class VariantStructSchema(StructSchema[TD_co, Any, Any], Generic[TD_co]):
    """One variant's struct: a struct schema whose ``make`` /
    ``make_effect`` fill the keys with a constructor default
    (``with_constructor_default``) before checking the value."""

    def make[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> A:
        filled = _filled(cast("VariantStructSchema[Any]", self), input)
        value = input if filled is None else cast("A", run_sync(filled))
        return _AnyBottom.make(self, value, **options)

    def make_option[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> Option[A]:
        filled = _filled(cast("VariantStructSchema[Any]", self), input)
        value = input if filled is None else cast("A", run_sync(filled))
        return _AnyBottom.make_option(self, value, **options)

    def make_effect[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> Effect[A, Issue]:
        filled = _filled(cast("VariantStructSchema[Any]", self), input)
        if filled is None:
            return _AnyBottom.make_effect(self, input, **options)
        return filled.flat_map(
            lambda value: _AnyBottom.make_effect(self, cast("A", value), **options)
        )


def _filled(schema: VariantStructSchema[Any], input: object) -> Effect[dict[str, object]] | None:
    """``input`` with each missing defaulted key set to its default; ``None``
    when nothing is missing (or ``input`` is no mapping, which the check
    then rejects)."""
    if not isinstance(input, Mapping):
        return None
    given = cast("Mapping[str, object]", input)
    missing = [
        (name, field.default)
        for name, field in schema.fields.items()
        if name not in given and isinstance(field, WithConstructorDefault)
    ]
    if not missing:
        return None
    values = dict(given)
    run: Effect[None] = succeed(None)
    for name, default in missing:
        run = run.and_then(default.map(lambda value, name=name: values.__setitem__(name, value)))
    return run.map(lambda _: values)


def variant_struct_schema(fields: Mapping[str, AnyCodec]) -> VariantStructSchema[Any]:
    """The struct of ``fields``, keys in order."""
    schemas = {name: codec.__codec__() for name, codec in fields.items()}
    node = ast.Objects(tuple(ast.PropertySignature(n, s.ast) for n, s in schemas.items()))
    return VariantStructSchema(node, schemas)


type Definition = AnyCodec | Field[Any] | HasVariants
"""What a variant struct's field may be."""


@runtime_checkable
class HasVariants(Protocol):
    """A variant struct or a variant class: field definitions, and a cache
    of the structs extracted from them."""

    def __variant_fields__(self) -> Mapping[str, Definition]: ...

    def __variant_cache__(self, is_default: bool) -> dict[str, Any]: ...


class Struct:
    """Field definitions shared by every variant (Effect's
    ``VariantSchema.Struct``); a toolkit's ``extract`` gives one variant's
    struct schema."""

    __slots__ = ("_caches", "_fields")

    def __init__(self, fields: Mapping[str, Definition | None]) -> None:
        self._fields = {name: value for name, value in fields.items() if value is not None}
        self._caches: tuple[dict[str, Any], dict[str, Any]] = ({}, {})

    def __variant_fields__(self) -> Mapping[str, Definition]:
        return self._fields

    def __variant_cache__(self, is_default: bool) -> dict[str, Any]:
        return self._caches[is_default]

    def pipe[B](self, f: Callable[[Struct], B], /) -> B:
        return f(self)


def is_struct(value: object) -> TypeIs[HasVariants]:
    """``value`` is a variant struct or a variant class (Effect's
    ``isStruct``)."""
    return isinstance(value, HasVariants)


def fields(self: HasVariants, /) -> Mapping[str, Definition]:
    """The field definitions of a variant struct or class (Effect's
    ``fields``)."""
    return self.__variant_fields__()


def extract(self: HasVariants, variant: str, *, is_default: bool = False) -> Any:
    """``variant``'s struct schema. With ``is_default``, a variant class is
    its own schema, and so is a variant class nested in it."""
    if is_default and is_schema(self):
        return self
    cache = self.__variant_cache__(is_default)
    found = cache.get(variant)
    if found is not None:
        return found
    selected: dict[str, AnyCodec] = {}
    for key, value in self.__variant_fields__().items():
        if isinstance(value, HasVariants):
            keep = is_default and is_schema(value)
            selected[key] = cast("AnyCodec", value) if keep else extract(value, variant)
        elif isinstance(value, Field):
            schema = value.schemas.get(variant)
            if schema is not None:
                selected[key] = schema
        else:
            selected[key] = value
    schema = variant_struct_schema(selected)
    cache[variant] = schema
    return schema


def schema_of_definition(value: Definition, variant: str) -> AnyCodec | None:
    """The schema a definition has in ``variant`` (``None``: left out)."""
    if isinstance(value, HasVariants):
        return cast("AnyCodec", value) if is_schema(value) else extract(value, variant)
    if isinstance(value, Field):
        return value.schemas.get(variant)
    return value


__all__ = [
    "Definition",
    "HasVariants",
    "Struct",
    "VariantStructSchema",
    "extract",
    "fields",
    "is_struct",
    "schema_of_definition",
    "variant_struct_schema",
]
