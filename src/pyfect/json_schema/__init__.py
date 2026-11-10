"""JSON Schema documents across dialects (Effect's ``JsonSchema``).

Every conversion goes through Draft 2020-12: read a schema with one of the
``from_schema_*`` functions into a ``Document`` (the root schema and its
definitions, kept apart), then write it out with ``to_document_draft_07``,
``to_document_draft_04`` or ``to_multi_document_open_api_3_1``::

    from pyfect import json_schema

    doc = json_schema.from_schema_draft_07({"type": "array", "items": [{"type": "string"}]})
    doc.schema  # {"type": "array", "prefixItems": [{"type": "string"}]}
    json_schema.to_document_draft_07(doc).schema  # back to Draft-07

References (``$ref``) are relocated to where their targets land, schema
resources (``$id``) included. A keyword that cannot be carried over without
changing what the schema accepts raises ``ValueError`` with Effect's message.
Schemas are plain dicts; inputs are never mutated.
"""

from pyfect.json_schema._api import (
    from_schema_draft_07,
    from_schema_draft_2020_12,
    from_schema_open_api_3_0,
    from_schema_open_api_3_1,
    to_document_draft_04,
    to_document_draft_07,
    to_document_draft_07_with_definitions_path,
    to_multi_document_open_api_3_1,
)
from pyfect.json_schema._model import (
    META_SCHEMA_URI_DRAFT_04,
    META_SCHEMA_URI_DRAFT_07,
    META_SCHEMA_URI_DRAFT_2020_12,
    VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP,
    Definitions,
    Dialect,
    Document,
    JsonSchema,
    MultiDocument,
    Type,
    get_reference_key,
    rewrite_refs,
    sanitize_open_api_components_schemas_key,
)
from pyfect.json_schema._openapi import to_multi_document_components

__all__ = [
    "META_SCHEMA_URI_DRAFT_04",
    "META_SCHEMA_URI_DRAFT_07",
    "META_SCHEMA_URI_DRAFT_2020_12",
    "VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP",
    "Definitions",
    "Dialect",
    "Document",
    "JsonSchema",
    "MultiDocument",
    "Type",
    "from_schema_draft_07",
    "from_schema_draft_2020_12",
    "from_schema_open_api_3_0",
    "from_schema_open_api_3_1",
    "get_reference_key",
    "rewrite_refs",
    "sanitize_open_api_components_schemas_key",
    "to_document_draft_04",
    "to_document_draft_07",
    "to_document_draft_07_with_definitions_path",
    "to_multi_document_components",
    "to_multi_document_open_api_3_1",
]
