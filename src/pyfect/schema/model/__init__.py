"""Models (Effect's ``effect/schema/Model``): one class for a table's row
and the variants a database and a JSON API read and write::

    from pyfect.schema import model as Model


    class UserInsert(TypedDict):
        name: str
        created_at: NotRequired[datetime]


    class User(Model.Class[UserInsert]):
        id: int = Model.field(Model.GeneratedByDb(S.Int))
        name: str
        created_at: datetime = Model.field(Model.DateTimeInsert)
        password: str = Model.field(Model.Sensitive(S.String))  # left out of the JSON variants


    User  # the select variant
    User.insert.make({"name": "Ada"})  # created_at set to now
    User.json  # what a JSON API sends

The variants are ``select``, ``insert``, ``update``, ``json``,
``json_create`` and ``json_update``. A field annotated plainly is in every
variant; ``Model.field(...)`` gives a variant field (``GeneratedByDb``,
``Sensitive``, ``FieldOption``, ``DateTimeInsert``, ``field_only([...])``,
...), whose ``select`` Type the annotation must be. A field the
``select`` variant leaves out is assigned without an annotation.
``pyfect.sql.model`` makes repositories of models. The variants' Types are
the TypedDicts given as ``Model.Class``'s type arguments (see ``Class``).
"""

from pyfect.schema.model._class import Class, ModelVariants, extract, fields
from pyfect.schema.model._dates import (
    Date,
    DateTimeFromDateWithNow,
    DateTimeFromNumberWithNow,
    DateTimeInsert,
    DateTimeInsertFromDate,
    DateTimeInsertFromNumber,
    DateTimeUpdate,
    DateTimeUpdateFromDate,
    DateTimeUpdateFromNumber,
    DateTimeWithNow,
    DateWithNow,
)
from pyfect.schema.model._fields import (
    BooleanSqlite,
    FieldOption,
    GeneratedByApp,
    GeneratedByDb,
    JsonFromString,
    Sensitive,
    optional_option,
)
from pyfect.schema.model._toolkit import (
    Field,
    NotSelected,
    Struct,
    Union,
    Variant,
    VariantsDatabase,
    VariantsJson,
    field_evolve,
    field_except,
    field_only,
)
from pyfect.schema.model._uuid import (
    UuidV4BytesInsert,
    UuidV4BytesWithGenerate,
    UuidV4Insert,
    UuidV4WithGenerate,
    UuidV7Insert,
    UuidV7WithGenerate,
)
from pyfect.schema.variant_schema import Overrideable, field, override

__all__ = [
    "BooleanSqlite",
    "Class",
    "Date",
    "DateTimeFromDateWithNow",
    "DateTimeFromNumberWithNow",
    "DateTimeInsert",
    "DateTimeInsertFromDate",
    "DateTimeInsertFromNumber",
    "DateTimeUpdate",
    "DateTimeUpdateFromDate",
    "DateTimeUpdateFromNumber",
    "DateTimeWithNow",
    "DateWithNow",
    "Field",
    "FieldOption",
    "GeneratedByApp",
    "GeneratedByDb",
    "JsonFromString",
    "ModelVariants",
    "NotSelected",
    "Overrideable",
    "Sensitive",
    "Struct",
    "Union",
    "UuidV4BytesInsert",
    "UuidV4BytesWithGenerate",
    "UuidV4Insert",
    "UuidV4WithGenerate",
    "UuidV7Insert",
    "UuidV7WithGenerate",
    "Variant",
    "VariantsDatabase",
    "VariantsJson",
    "extract",
    "field",
    "field_evolve",
    "field_except",
    "field_only",
    "fields",
    "optional_option",
    "override",
]
