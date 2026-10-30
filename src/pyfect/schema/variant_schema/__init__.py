"""Variant schemas (Effect's ``effect/schema/VariantSchema``): related
schemas for named variants built from one set of field definitions::

    from pyfect.schema import variant_schema as VS

    Test = VS.make(variants=["a", "b"], default_variant="a")
    struct = Test.Struct({"common": S.String, "only_b": Test.field_only(["b"])(S.Number)})
    Test.extract(struct, "b")  # the struct schema of common and only_b

    class User(Test.Class):
        id: int = VS.field(Test.field_only(["a"])(S.Int))
        name: str

    Test.extract(User, "b")  # the struct schema of name; User is the "a" schema

``pyfect.schema.model`` is the toolkit for database and JSON API models.
Pyright cannot compute a variant's keys from the definitions (no mapped
types), so an extracted struct's Type is a ``Mapping``; ``Model.Class``
takes TypedDicts for its variants (see there).
"""

from pyfect.schema.variant_schema._class import Class, VariantAttribute, field
from pyfect.schema.variant_schema._defaults import (
    Overrideable,
    WithConstructorDefault,
    override,
    with_constructor_default,
)
from pyfect.schema.variant_schema._field import Field, is_field
from pyfect.schema.variant_schema._struct import (
    Definition,
    HasVariants,
    Struct,
    VariantStructSchema,
    extract,
    fields,
    is_struct,
)
from pyfect.schema.variant_schema._toolkit import (
    FieldEvolve,
    FieldOnly,
    VariantSchema,
    VariantUnionSchema,
    make,
)

__all__ = [
    "Class",
    "Definition",
    "Field",
    "FieldEvolve",
    "FieldOnly",
    "HasVariants",
    "Overrideable",
    "Struct",
    "VariantAttribute",
    "VariantSchema",
    "VariantStructSchema",
    "VariantUnionSchema",
    "WithConstructorDefault",
    "extract",
    "field",
    "fields",
    "is_field",
    "is_struct",
    "make",
    "override",
    "with_constructor_default",
]
