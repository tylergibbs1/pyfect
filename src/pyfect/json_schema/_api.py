"""Reading a schema of any supported dialect into a Draft 2020-12
``Document``, and writing one out as Draft-07, Draft-04 or OpenAPI 3.1."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, cast

from pyfect.json_schema._converter import Adapter, Converter
from pyfect.json_schema._draft04 import to_draft_04
from pyfect.json_schema._draft07 import from_draft_07, to_draft_07
from pyfect.json_schema._model import (
    Definitions,
    Document,
    JsonSchema,
    MultiDocument,
    as_object,
    is_object,
)
from pyfect.json_schema._openapi import from_open_api_3_0, from_open_api_3_1, to_open_api_3_1

type Draft2020 = Literal["draft-2020-12"]


def from_schema_draft_2020_12(js: JsonSchema) -> Document[Draft2020]:
    """A Draft 2020-12 schema as a document: its ``$defs`` become the
    definitions (an empty dict when there are none)."""
    schema = {key: value for key, value in js.items() if key != "$defs"}
    defs = js.get("$defs")
    definitions = cast("Definitions", dict(as_object(defs))) if is_object(defs) else {}
    return Document("draft-2020-12", schema, definitions)


def from_schema_draft_07(js: JsonSchema) -> Document[Draft2020]:
    """A Draft-07 schema in Draft 2020-12: tuple ``items`` as
    ``prefixItems``, ``definitions`` as ``$defs``, ``dependencies`` split,
    ``$id`` fragments as ``$anchor``, references relocated. A keyword that
    would gain a meaning in Draft 2020-12 raises ``ValueError``."""
    return from_schema_draft_2020_12(from_draft_07(js))


def from_schema_open_api_3_1(js: JsonSchema) -> Document[Draft2020]:
    """An OpenAPI 3.1 schema in Draft 2020-12: ``#/components/schemas/X``
    references as ``#/$defs/X``, ``example`` folded into ``examples``."""
    return from_schema_draft_2020_12(from_open_api_3_1(js))


def from_schema_open_api_3_0(js: JsonSchema) -> Document[Draft2020]:
    """An OpenAPI 3.0 schema in Draft 2020-12: ``nullable`` as a ``null``
    type or branch, boolean exclusive bounds as numeric ones, ``example`` as
    ``examples``."""
    return from_schema_draft_2020_12(from_open_api_3_0(js))


def _convert_document(
    document: Document[Draft2020],
    adapter: Adapter,
    boolean_adapter: Callable[[bool], object] | None = None,
    definitions_path: Sequence[str] | None = None,
) -> tuple[JsonSchema, Definitions]:
    converter = Converter(adapter, boolean_adapter=boolean_adapter, track_ids=True)
    schema = cast("JsonSchema", converter.convert(document.schema))
    source = ["$defs"] if definitions_path is None else list(definitions_path)
    target = ["definitions"] if definitions_path is None else list(definitions_path)
    definitions = {
        key: cast("JsonSchema", converter.convert(value, [*source, key], [*target, key]))
        for key, value in document.definitions.items()
    }
    converter.finish()
    return schema, definitions


def to_document_draft_07(document: Document[Draft2020]) -> Document[Literal["draft-07"]]:
    """The document in Draft-07. A keyword Draft-07 cannot express raises
    ``ValueError``."""
    return to_document_draft_07_with_definitions_path(document)


def to_document_draft_07_with_definitions_path(
    document: Document[Draft2020], definitions_path: Sequence[str] | None = None
) -> Document[Literal["draft-07"]]:
    """The document in Draft-07 with its definitions located at ``definitions_path``,
    such as ``["components", "schemas"]`` after ``to_multi_document_components``, so
    references into them stay in place (Effect's ``toDocumentDraft07WithDefinitionsPath``);
    by default ``$defs`` become ``definitions``."""
    schema, definitions = _convert_document(
        document, to_draft_07, definitions_path=definitions_path
    )
    return Document("draft-07", schema, definitions)


def _boolean_schema(schema: bool) -> JsonSchema:
    return {} if schema else {"not": {}}


def to_document_draft_04(document: Document[Draft2020]) -> Document[Literal["draft-04"]]:
    """The document in Draft-04: boolean schemas as ``{}`` / ``{"not": {}}``,
    conditionals and ``contains`` lowered to ``anyOf`` / ``allOf`` / ``not``,
    ``const`` as ``enum``. A keyword Draft-04 cannot express raises
    ``ValueError``."""
    schema, definitions = _convert_document(document, to_draft_04, boolean_adapter=_boolean_schema)
    return Document("draft-04", schema, definitions)


def to_multi_document_open_api_3_1(
    multi_document: MultiDocument[Draft2020],
) -> MultiDocument[Literal["openapi-3.1"]]:
    """The documents with their shared definitions as OpenAPI 3.1
    ``components.schemas``: references rewritten, keys OpenAPI forbids
    sanitized (``_1``, ``_2``... on a collision)."""
    return to_open_api_3_1(multi_document)
