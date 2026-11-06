"""``from_json_schema_document`` / ``from_json_schema_multi_document``: runtime
schemas from JSON Schema Draft 2020-12 (Effect's ``fromJsonSchemaDocument``).

A best-effort translation: ``_translate`` reads each schema object into the
import nodes of ``_nodes``, ``_intersect`` normalizes them (``allOf``, siblings
of ``$ref``, ``enum`` and ``const``), and only ``_finalize`` builds schemas.
What has no equivalent raises ``RepresentationError`` naming the source path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pyfect.json_schema import Document, JsonSchema, MultiDocument
from pyfect.json_schema._api import Draft2020
from pyfect.schema.issue import Path
from pyfect.schema.representation._import._finalize import Finalizer, ImportedSchema
from pyfect.schema.representation._import._js_order import js_ordered
from pyfect.schema.representation._import._keywords import PatternMode
from pyfect.schema.representation._import._translate import Options, Translator

__all__ = [
    "ImportedSchema",
    "PatternMode",
    "from_json_schema_document",
    "from_json_schema_multi_document",
]


def _import(
    schemas: tuple[JsonSchema, ...],
    definitions: dict[str, JsonSchema],
    path: Callable[[int], Path],
    options: Options,
) -> tuple[ImportedSchema, ...]:
    translator = Translator(definitions, options)
    finalizer = Finalizer(translator)
    return tuple(
        finalizer.root(translator.schema(schema, path(index), is_root=True))
        for index, schema in enumerate(schemas)
    )


def from_json_schema_document(
    document: Document[Draft2020],
    /,
    *,
    on_enter: Callable[[JsonSchema], JsonSchema] | None = None,
    patterns: PatternMode = "error",
    include_annotation_key: Callable[[str], bool] | None = None,
) -> ImportedSchema:
    """The schema ``document`` describes. ``on_enter`` replaces each schema
    object before it is read; ``patterns`` says what a ``pattern`` or
    ``patternProperties`` does: ``"error"`` rejects it, ``"ignore"`` skips it,
    ``"apply"`` enforces it (for trusted documents only, as a regular
    expression may run for an unbounded time). ``include_annotation_key``
    selects other keys to keep as annotations."""
    options = Options(on_enter, patterns, include_annotation_key)
    schema, definitions = js_ordered((document.schema, document.definitions))
    return _import((schema,), definitions, lambda _: ("schema",), options)[0]


def from_json_schema_multi_document(
    document: MultiDocument[Draft2020],
    /,
    *,
    on_enter: Callable[[JsonSchema], JsonSchema] | None = None,
    patterns: PatternMode = "error",
    include_annotation_key: Callable[[str], bool] | None = None,
) -> tuple[ImportedSchema, *tuple[ImportedSchema, ...]]:
    """The schemas of ``document``'s roots, sharing their definitions; only
    definitions a root reaches are read. Options as
    ``from_json_schema_document``."""
    options = Options(on_enter, patterns, include_annotation_key)
    schemas, definitions = js_ordered((document.schemas, document.definitions))
    out = _import(schemas, definitions, lambda i: ("schemas", i), options)
    return cast("tuple[ImportedSchema, *tuple[ImportedSchema, ...]]", out)
