"""The model toolkit: Effect's ``Model`` variants and its typed field
constructors."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, final, overload

from pyfect.schema._schema import Codec
from pyfect.schema.variant_schema import (
    Definition,
    FieldEvolve,
    FieldOnly,
    VariantSchema,
    VariantUnionSchema,
    make,
)
from pyfect.schema.variant_schema import Field as VariantField
from pyfect.schema.variant_schema import HasVariants as _HasVariants
from pyfect.schema.variant_schema import Struct as VariantStruct

type Variant = Literal["select", "insert", "update", "json", "json_create", "json_update"]
"""A model variant: ``select`` (the class), ``insert`` / ``update`` (what
is written to the database), ``json`` / ``json_create`` / ``json_update``
(what a JSON API reads and writes). Effect's ``jsonCreate`` / ``jsonUpdate``
are snake_case."""

type VariantsDatabase = Literal["select", "insert", "update"]
type VariantsJson = Literal["json", "json_create", "json_update"]

VARIANTS: tuple[Variant, ...] = ("select", "insert", "update", "json", "json_create", "json_update")
DATABASE: tuple[Variant, ...] = ("select", "insert", "update")

TOOLKIT: VariantSchema = make(variants=VARIANTS, default_variant="select")


@final
class NotSelected:
    """The default-variant Type of a field the ``select`` variant leaves out:
    no annotation accepts it, so such a field is assigned without one."""


type AnyCodec = Codec[Any, Any, Any, Any]


@overload
def Field[A](
    *,
    select: Codec[A, Any, Any, Any],
    insert: AnyCodec | None = None,
    update: AnyCodec | None = None,
    json: AnyCodec | None = None,
    json_create: AnyCodec | None = None,
    json_update: AnyCodec | None = None,
) -> VariantField[A]: ...
@overload
def Field(
    *,
    insert: AnyCodec | None = None,
    update: AnyCodec | None = None,
    json: AnyCodec | None = None,
    json_create: AnyCodec | None = None,
    json_update: AnyCodec | None = None,
) -> VariantField[NotSelected]: ...
def Field(
    *,
    select: AnyCodec | None = None,
    insert: AnyCodec | None = None,
    update: AnyCodec | None = None,
    json: AnyCodec | None = None,
    json_create: AnyCodec | None = None,
    json_update: AnyCodec | None = None,
) -> VariantField[Any]:
    """A field's schema per variant (Effect's ``Model.Field``); ``None``
    leaves it out of that variant. Without ``select`` the field is not the
    class's (its Type ``NotSelected`` fits no annotation)."""
    return TOOLKIT.Field(
        select=select,
        insert=insert,
        update=update,
        json=json,
        json_create=json_create,
        json_update=json_update,
    )


def field_only(keys: Sequence[Variant], /) -> FieldOnly:
    """``field_only(["select", "json"])(schema)``: a field in those variants
    only (Effect's ``FieldOnly``)."""
    return TOOLKIT.field_only(keys)


def field_except(keys: Sequence[Variant], /) -> FieldOnly:
    """``field_except(["insert"])(schema)``: a field in every variant but
    those (Effect's ``FieldExcept``)."""
    return TOOLKIT.field_except(keys)


def field_evolve(mapping: Mapping[Variant, Callable[[AnyCodec], AnyCodec]], /) -> FieldEvolve:
    """``field_evolve({"json": f})(field)``: the named variants' schemas
    mapped (Effect's ``fieldEvolve``); a variant the field lacks stays out."""
    evolve: dict[str, Callable[[AnyCodec], AnyCodec]] = {**mapping}
    return TOOLKIT.field_evolve(evolve)


def Struct(fields: Mapping[str, Definition | None], /) -> VariantStruct:
    """Model field definitions without a class (Effect's ``Model.Struct``)."""
    return TOOLKIT.Struct(fields)


def Union(members: Sequence[_HasVariants], /) -> VariantUnionSchema:
    """The union of the members' ``select`` variants, with ``variants``
    holding the union of each variant (Effect's ``Model.Union``)."""
    return TOOLKIT.Union(members)
