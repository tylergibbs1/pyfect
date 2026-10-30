"""Model fields (Effect's ``Model``): generated keys, sensitive values,
optional values, SQLite booleans and JSON text columns."""

from __future__ import annotations

from typing import Any, overload

from pyfect.option import Option
from pyfect.schema._codecs import BooleanFromBit, OptionFromNullOr, OptionFromOptionalNullOr
from pyfect.schema._codecs import from_json_string as _from_json_string
from pyfect.schema._primitives import Boolean
from pyfect.schema._schema import Codec
from pyfect.schema._to_codec_json import to_codec_json
from pyfect.schema.model._toolkit import DATABASE, VARIANTS, AnyCodec
from pyfect.schema.variant_schema import Field


def GeneratedByDb[A](schema: Codec[A, Any, Any, Any], /) -> Field[A]:
    """A value the database makes (an auto-increment id): in ``select`` and
    ``json`` only."""
    return Field({"select": schema, "json": schema})


def GeneratedByApp[A](schema: Codec[A, Any, Any, Any], /) -> Field[A]:
    """A value the application makes, never a JSON API's client: in every
    variant but ``json_create`` / ``json_update``."""
    return Field({"select": schema, "insert": schema, "update": schema, "json": schema})


def Sensitive[A](schema: Codec[A, Any, Any, Any], /) -> Field[A]:
    """A value never sent through a JSON API: in the database variants
    only."""
    return Field(dict.fromkeys(DATABASE, schema))


optional_option = OptionFromOptionalNullOr
"""A key that may be missing or ``None``, as an ``Option`` (Effect's
``Model.optionalOption``; Python has one ``None``, so it is
``S.OptionFromOptionalNullOr``)."""


def _option_of(variant: str, schema: AnyCodec) -> AnyCodec:
    return OptionFromNullOr(schema) if variant in DATABASE else OptionFromOptionalNullOr(schema)


@overload
def FieldOption[A](self: Field[A], /) -> Field[Option[A]]: ...
@overload
def FieldOption[A](self: Codec[A, Any, Any, Any], /) -> Field[Option[A]]: ...
def FieldOption(self: Field[Any] | AnyCodec, /) -> Field[Any]:
    """An optional value as an ``Option``: ``None`` in the database
    variants, a missing key or ``None`` in the JSON ones. A field keeps its
    variants; a schema is in all of them."""
    schemas = self.schemas if isinstance(self, Field) else dict.fromkeys(VARIANTS, self)
    return Field({variant: _option_of(variant, s) for variant, s in schemas.items()})


BooleanSqlite: Field[bool] = Field(
    {
        **dict.fromkeys(DATABASE, BooleanFromBit),
        **dict.fromkeys(("json", "json_create", "json_update"), Boolean),
    }
)
"""A boolean stored as ``0`` / ``1`` (SQLite has no boolean type), a
boolean in JSON."""


def JsonFromString[A](schema: Codec[A, Any, Any, Any], /) -> Field[A]:
    """A value stored as JSON text in the database, the value itself in
    JSON."""
    parsed = _from_json_string(to_codec_json(schema))
    return Field(
        {
            **dict.fromkeys(DATABASE, parsed),
            **dict.fromkeys(("json", "json_create", "json_update"), schema),
        }
    )
