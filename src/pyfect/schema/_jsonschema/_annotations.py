"""The options of JSON Schema generation, and the JSON Schema keywords a
node's annotations give (``title``, ``description``, ...)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeIs, cast

from pyfect.json_schema import JsonSchema
from pyfect.schema import ast

type OnExcessProperty = Literal["ignore", "error"]


@dataclass(frozen=True, slots=True)
class ReferenceCandidate:
    """What a reference policy decides on: a node that may become a
    definition, how often it occurs, and its identifier (if any)."""

    ast: ast.AST
    occurrences: int
    identifier: str | None


type ReferencePolicy = Callable[[ReferenceCandidate], str | None]
"""The definition key of a candidate, or ``None`` to inline it (a
recursive one is then still a definition, keyed by its kind)."""


@dataclass(frozen=True, slots=True)
class Options:
    on_excess_property: OnExcessProperty = "ignore"
    generate_descriptions: bool = False
    include_annotation_key: Callable[[str], bool] | None = None


_STRING_KEYWORDS = {
    "title": "title",
    "description": "description",
    "format": "format",
    "content_encoding": "contentEncoding",
    "content_media_type": "contentMediaType",
}
_BOOLEAN_KEYWORDS = {"read_only": "readOnly", "write_only": "writeOnly"}
_EXCLUDED = frozenset(
    {
        *_STRING_KEYWORDS,
        *_BOOLEAN_KEYWORDS,
        "default",
        "examples",
        "content_schema",
        "representation",
        "arbitrary_constraint",
        "to_json_schema",
        "to_code",
        "to_equivalence",
        "to_formatter",
        "to_codec",
        "to_codec_json",
        "to_codec_string_tree",
        "to_codec_iso",
        "to_codec_arbitrary",
    }
)


def to_json(value: object) -> object:
    """A JSON value as JSON Schema holds it: tuples as lists, mappings as dicts."""
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in cast("Sequence[object]", value)]
    if isinstance(value, Mapping):
        return {k: to_json(v) for k, v in cast("Mapping[str, object]", value).items()}
    return value


def _is_sequence(value: object) -> TypeIs[Sequence[object]]:
    return isinstance(value, (list, tuple))


def collect(annotations: ast.Annotations | None, options: Options) -> JsonSchema:
    """The JSON Schema keywords of ``annotations``."""
    if not annotations:
        return {}
    out: JsonSchema = {}
    for key, keyword in _STRING_KEYWORDS.items():
        value = annotations.get(key)
        if isinstance(value, str):
            out[keyword] = value
    for key, keyword in _BOOLEAN_KEYWORDS.items():
        value = annotations.get(key)
        if isinstance(value, bool):
            out[keyword] = value
    expected = annotations.get("expected")
    if "description" not in out and options.generate_descriptions and isinstance(expected, str):
        out["description"] = expected
    if "default" in annotations and ast.is_json(annotations["default"]):
        out["default"] = to_json(annotations["default"])
    examples = annotations.get("examples")
    if _is_sequence(examples) and ast.is_json(examples):
        out["examples"] = to_json(examples)
    if "content_schema" in annotations and ast.is_json(annotations["content_schema"]):
        out["contentSchema"] = to_json(annotations["content_schema"])
    include = options.include_annotation_key
    if include is not None:
        for key, value in annotations.items():
            if (
                key not in _EXCLUDED
                and not key.startswith("~")
                and include(key)
                and ast.is_json(value)
            ):
                out[key] = to_json(value)
    return out
