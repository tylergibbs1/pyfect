"""The JSON Schema of a tool's parameters or result as MCP lists it
(Effect's ``toolJsonSchema``): MCP wants an object at the root, so the
root is compiled inline even when it has an identifier; a recursive root
keeps its definition and the top-level ``$ref`` is resolved."""

from __future__ import annotations

from pyfect.ai._structured_output_json import resolve_root
from pyfect.json_schema import Document, JsonSchema
from pyfect.schema import Top
from pyfect.schema._jsonschema._annotations import Options, ReferenceCandidate
from pyfect.schema._jsonschema._compile import Compiler
from pyfect.schema._jsonschema._references import References
from pyfect.schema._to_codec_json import to_codec_json_asts


def tool_json_schema(schema: Top, *, strict: bool) -> JsonSchema:
    """``schema``'s JSON Schema, objects closed when ``strict``, its
    definitions under ``$defs``."""
    [node] = to_codec_json_asts([schema.__codec__().ast])
    root = References((), None).candidate(node).ast

    def policy(candidate: ReferenceCandidate) -> str | None:
        if candidate.ast is root and candidate.occurrences == 1:
            return None
        return candidate.identifier

    compiler = Compiler(
        References((node,), policy), Options("error" if strict else "ignore", False, None)
    )
    [out], definitions = compiler.finish([compiler.recur(node, [])])
    resolved = dict(resolve_root(Document("draft-2020-12", out, definitions)))
    if definitions:
        resolved["$defs"] = dict(definitions)
    return resolved
