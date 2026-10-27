"""``to_json_schema_document``: the JSON Schema (Draft 2020-12) of a
schema's canonical JSON form (Effect's ``Schema.toJsonSchemaDocument``).

The document describes the encoded side of ``to_codec_json(schema)``:
decode JSON with that codec. It is meant for preliminary validation: the
schema's decoder stays the authority (a check without a JSON Schema
fragment is left out, and an approximation never rejects a valid value).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pyfect.json_schema import Document, MultiDocument
from pyfect.schema._jsonschema._annotations import (
    OnExcessProperty,
    Options,
    ReferenceCandidate,
    ReferencePolicy,
)
from pyfect.schema._jsonschema._checks import CheckContext, CheckOutput, ToJsonSchema
from pyfect.schema._jsonschema._compile import Compiler
from pyfect.schema._jsonschema._references import References
from pyfect.schema._schema import Top
from pyfect.schema._to_codec_json import to_codec_json_asts

__all__ = [
    "CheckContext",
    "CheckOutput",
    "OnExcessProperty",
    "ReferenceCandidate",
    "ReferencePolicy",
    "ToJsonSchema",
    "to_json_schema_document",
    "to_json_schema_multi_document",
]

type Draft2020 = Literal["draft-2020-12"]


def to_json_schema_multi_document(
    schemas: tuple[Top, *tuple[Top, ...]],
    /,
    *,
    on_excess_property: OnExcessProperty = "ignore",
    generate_descriptions: bool = False,
    include_annotation_key: Callable[[str], bool] | None = None,
    reference_policy: ReferencePolicy | None = None,
) -> MultiDocument[Draft2020]:
    """The JSON Schemas of several schemas, sharing their definitions.

    ``on_excess_property="error"`` closes objects to keys the schema does
    not model (as the decoder option of that name does);
    ``generate_descriptions`` describes a check without a ``description``
    by its ``expected`` text; ``include_annotation_key(key)`` admits other
    annotations with JSON values (``"x-..."``); ``reference_policy`` decides
    which nodes become definitions (default: those with an
    ``identifier``)."""
    nodes = to_codec_json_asts([schema.__codec__().ast for schema in schemas])
    references = References(nodes, reference_policy)
    compiler = Compiler(
        references,
        Options(on_excess_property, generate_descriptions, include_annotation_key),
    )
    roots = [compiler.recur(node, []) for node in nodes]
    out, definitions = compiler.finish(roots)
    return MultiDocument("draft-2020-12", tuple(out), definitions)


def to_json_schema_document(
    schema: Top,
    /,
    *,
    on_excess_property: OnExcessProperty = "ignore",
    generate_descriptions: bool = False,
    include_annotation_key: Callable[[str], bool] | None = None,
    reference_policy: ReferencePolicy | None = None,
) -> Document[Draft2020]:
    """The JSON Schema of ``schema``'s canonical JSON form, with its
    definitions apart (see ``to_json_schema_multi_document`` for the
    options)."""
    multi = to_json_schema_multi_document(
        (schema,),
        on_excess_property=on_excess_property,
        generate_descriptions=generate_descriptions,
        include_annotation_key=include_annotation_key,
        reference_policy=reference_policy,
    )
    return Document("draft-2020-12", multi.schemas[0], multi.definitions)
