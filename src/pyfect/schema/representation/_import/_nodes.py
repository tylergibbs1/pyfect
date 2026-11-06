"""Import nodes: a JSON Schema being normalized. They keep their source's
annotations, object scopes and paths until ``_finalize`` builds schemas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TypedDict

from pyfect.schema import ast
from pyfect.schema.issue import Path

type Annotations = Mapping[str, object]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportedAnnotations:
    """``annotations`` (standard ones) may describe a value or a group of
    checks; ``custom_annotations`` always describe the value, even when its
    checks simplify away."""

    annotations: Annotations | None = None
    custom_annotations: Annotations | None = None


@dataclass(frozen=True, slots=True)
class Filter:
    filter: ast.Filter[object]
    annotations: Annotations | None = None


@dataclass(frozen=True, slots=True)
class PropertyNames:
    type: Node
    annotations: Annotations | None = None


@dataclass(frozen=True, slots=True)
class FilterGroup:
    checks: tuple[Check, *tuple[Check, ...]]
    annotations: Annotations | None = None


type Check = Filter | PropertyNames | FilterGroup


@dataclass(frozen=True, slots=True, kw_only=True)
class Checked(ImportedAnnotations):
    checks: tuple[Check, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Never(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Unknown(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Null(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class String(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Number(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Boolean(Checked):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class Literal(Checked):
    literal: str | int | float | bool


@dataclass(frozen=True, slots=True)
class Element:
    type: Node
    is_optional: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Arrays(Checked):
    elements: tuple[Element, ...] = ()
    rest: Node | None = None


@dataclass(frozen=True, slots=True)
class Property:
    name: str
    type: Node
    is_optional: bool


@dataclass(frozen=True, slots=True)
class IndexSignature:
    parameter: Node
    type: Node


@dataclass(frozen=True, slots=True)
class ObjectPattern:
    source: str
    parameter: String
    type: Node


@dataclass(frozen=True, slots=True)
class ObjectProperty:
    type: Node | None
    is_optional: bool


@dataclass(frozen=True, slots=True)
class ObjectScope:
    properties: Mapping[str, ObjectProperty]
    has_properties: bool
    patterns: tuple[ObjectPattern, ...]
    additional_properties: Node


@dataclass(frozen=True, slots=True, kw_only=True)
class Objects(Checked):
    property_signatures: tuple[Property, ...] = ()
    index_signature: IndexSignature | None = None
    scopes: tuple[ObjectScope, ...] = ()
    path: Path = field(default=())


@dataclass(frozen=True, slots=True, kw_only=True)
class Union(Checked):
    types: tuple[Node, ...] = ()
    mode: ast.UnionMode | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Reference(ImportedAnnotations):
    ref: str
    path: Path


type Node = (
    Never
    | Unknown
    | Null
    | String
    | Number
    | Boolean
    | Literal
    | Arrays
    | Objects
    | Union
    | Reference
)


class CheckedFields(TypedDict):
    """The fields of a ``Checked`` that intersecting computes."""

    checks: tuple[Check, ...]
    annotations: Annotations | None
    custom_annotations: Annotations | None


NEVER = Never()
UNKNOWN = Unknown()
STRING = String()
"""The parameter of an open index signature: ``_finalize`` recognizes it by
identity."""


def merge_annotations(left: Annotations | None, right: Annotations | None) -> Annotations | None:
    if left is None:
        return right
    if right is None:
        return left
    return {**left, **right}


def annotate(node: Node, source: ImportedAnnotations) -> Node:
    """``node`` with ``source``'s annotations over its own."""
    if source.annotations is None and source.custom_annotations is None:
        return node
    return replace(
        node,
        annotations=merge_annotations(node.annotations, source.annotations),
        custom_annotations=merge_annotations(node.custom_annotations, source.custom_annotations),
    )
