"""Variant classes (Effect's ``VariantSchema.Class``): a schema class of
the default variant whose other variants are extracted from the same
field definitions::

    class User(Model.Class):
        id: int = Model.field(Model.GeneratedByDb(S.Int))  # select and json only
        name: str                                          # every variant
        password = Model.Sensitive(S.String)  # not in select: no annotation

An annotated field is a field of the class (the default variant), its
schema given by ``field(...)`` or derived from the annotation; a variant
field that the default variant leaves out is assigned without an
annotation, so the class does not have it. A subclass extends: a field it
redefines replaces the inherited one in every variant.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import dataclasses
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, cast, dataclass_transform, overload

from pyfect.schema._class import _SCHEMA, _annotation, _shape_of
from pyfect.schema._class import Class as SchemaClass
from pyfect.schema._class import field as schema_field
from pyfect.schema._schema import Codec
from pyfect.schema.variant_schema._field import AnyCodec, Field
from pyfect.schema.variant_schema._struct import (
    Definition,
    Struct,
    VariantStructSchema,
    extract,
)

_VARIANT = "pyfect.schema.variant_schema"
"""The ``dataclasses.Field.metadata`` key of a field's variant definition."""


@overload
def field[A](spec: Field[A], /) -> A: ...
@overload
def field(spec: Struct, /) -> Mapping[str, object]: ...
@overload
def field[A](spec: Codec[A, Any, Any, Any], /) -> A: ...
def field(spec: Field[Any] | Struct | AnyCodec, /) -> Any:
    """A variant class field defined by a variant field, a nested variant
    struct or a schema (one that may need services); the class's
    annotation must be its Type in the default variant."""
    return dataclasses.field(metadata={_VARIANT: spec})


class VariantSet(Protocol):
    """The variants a toolkit defines."""

    @property
    def variants(self) -> tuple[str, ...]: ...

    @property
    def default_variant(self) -> str: ...


@dataclass(frozen=True, slots=True)
class _Annotated:
    """A field defined by its annotation, read on first use (so it may
    refer to classes defined later)."""

    owner: type[Class]
    name: str

    def resolve(self) -> Definition:
        annotation = _annotation(self.owner, self.name)
        if isinstance(annotation, type) and issubclass(annotation, Class):
            return annotation
        return _shape_of(self.owner).schemas[self.name]


@dataclass_transform(
    kw_only_default=True, frozen_default=True, field_specifiers=(field, schema_field)
)
class Class(SchemaClass):
    """A variant class base; a toolkit's ``Class`` (``Model.Class``) is the
    one to subclass. See ``pyfect.schema.variant_schema``."""

    __variant_set__: ClassVar[VariantSet]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        variant_set = cast("VariantSet | None", getattr(cls, "__variant_set__", None))
        if variant_set is None:
            raise TypeError(f"{cls.__name__}: subclass a toolkit's Class (Model.Class, ...)")
        default = variant_set.default_variant
        annotated = inspect.get_annotations(cls)
        unannotated = _take_unannotated(cls, annotated, default)
        _set_default_schemas(cls, annotated, default)
        super().__init_subclass__(**kwargs)
        own: dict[str, object] = {}
        for f in dataclasses.fields(cast("Any", cls)):
            if f.name in annotated:
                own[f.name] = f.metadata.get(_VARIANT) or _Annotated(cls, f.name)
        own.update(unannotated)
        type.__setattr__(cls, "_variant_own", own)

    @classmethod
    def __variant_fields__(cls) -> Mapping[str, Definition]:
        merged: dict[str, object] = {}
        for klass in reversed(cls.__mro__):
            merged.update(klass.__dict__.get("_variant_own", {}))
        return {
            name: value.resolve() if isinstance(value, _Annotated) else cast("Definition", value)
            for name, value in merged.items()
        }

    @classmethod
    def __variant_cache__(cls, is_default: bool) -> dict[str, Any]:
        name = "_variant_default_cache" if is_default else "_variant_cache"
        cache = cls.__dict__.get(name)
        if cache is None:
            cache = {}
            type.__setattr__(cls, name, cache)
        return cast("dict[str, Any]", cache)


def _take_unannotated(
    cls: type, annotated: Mapping[str, object], default: str
) -> dict[str, object]:
    """The variant fields assigned without an annotation, removed from the
    class (it does not have them)."""
    found: dict[str, object] = {}
    for name, value in list(vars(cls).items()):
        spec = (
            cast("dataclasses.Field[Any]", value).metadata.get(_VARIANT)
            if name not in annotated and isinstance(value, dataclasses.Field)
            else None
        )
        if spec is not None:
            if isinstance(spec, Field) and default not in cast("Field[Any]", spec).schemas:
                raise TypeError(
                    f"{cls.__name__}.{name} is not in the {default!r} variant: "
                    "assign the variant field without field(...)"
                )
            raise TypeError(
                f"{cls.__name__}.{name} is in the {default!r} variant: annotate it with its type"
            )
        if name in annotated or not isinstance(value, (Field, Struct)):
            continue
        if isinstance(value, Struct) or default in value.schemas:
            raise TypeError(
                f"{cls.__name__}.{name} is in the {default!r} variant: annotate it with its type"
            )
        found[name] = value
        delattr(cls, name)
    return found


def _set_default_schemas(cls: type, annotated: Mapping[str, object], default: str) -> None:
    """Give each ``field(...)`` field its default variant's schema, the one
    the class itself decodes with."""
    for name in annotated:
        value = vars(cls).get(name)
        if not isinstance(value, dataclasses.Field):
            continue
        spec = cast("dataclasses.Field[Any]", value).metadata.get(_VARIANT)
        if spec is None:
            continue
        if isinstance(spec, Field):
            schema = cast("Field[Any]", spec).schemas.get(default)
            if schema is None:
                raise TypeError(
                    f"{cls.__name__}.{name} is not in the {default!r} variant: "
                    "assign it without an annotation"
                )
        elif isinstance(spec, Struct):
            schema = extract(spec, default)
        else:
            schema = spec
        setattr(cls, name, dataclasses.field(metadata={_SCHEMA: schema, _VARIANT: spec}))


class VariantAttribute:
    """``Cls.<variant>``: the variant's struct, annotated with the class's
    identifier (``User.insert``)."""

    __slots__ = ("variant",)

    def __init__(self, variant: str) -> None:
        self.variant = variant

    def __get__(self, instance: object, owner: type[Class]) -> VariantStructSchema[Any]:
        attributes = owner.__dict__.get("_variant_attributes")
        if attributes is None:
            attributes = {}
            type.__setattr__(owner, "_variant_attributes", attributes)
        found = cast("dict[str, VariantStructSchema[Any]]", attributes).get(self.variant)
        if found is None:
            name = f"{_shape_of(owner).identifier}.{self.variant}"
            schema = cast("VariantStructSchema[Any]", extract(owner, self.variant))
            found = schema.annotate(identifier=name, title=name)
            attributes[self.variant] = found
        return found
