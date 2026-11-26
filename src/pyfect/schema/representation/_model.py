"""The representation document model (Effect's ``SchemaRepresentation``
nodes): plain, comparable data describing a schema's encoded side.

A ``Representation`` is one node per AST kind. Leaf checks are ``Filter``
and groups ``FilterGroup``; a check or a declaration carries its
persistence identity in ``representation`` (an ``id`` and a JSON
``payload``), which ``from_representation`` gives to the reviver of that id.
``annotations`` are the node's live annotations (callbacks included);
``to_json`` keeps only the JSON ones.

Python mappings: ``Symbol`` and ``UniqueSymbol`` have no node (pyfect has no such
schemas), and a property has no ``isMutable`` (mutability is a TypeScript type-level
distinction).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar
from typing import Literal as TypingLiteral

from pyfect.schema.ast import UnionMode

type Annotations = Mapping[str, object]
type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
type LiteralValue = str | int | float | bool
type EnumValue = str | int | float
type PropertyName = str | int | float


@dataclass(frozen=True, slots=True)
class RepresentationAnnotation:
    """The persistence identity of a declaration: the reviver ``id`` and
    its JSON ``payload``."""

    id: str
    payload: Json = None


@dataclass(frozen=True, slots=True)
class CheckRepresentationAnnotation:
    """The persistence identity of a check, with the schemas it depends on
    (``is_property_names``'s key schema)."""

    id: str
    payload: Json = None
    schemas: tuple[Representation, ...] | None = None


@dataclass(frozen=True, slots=True)
class Filter:
    """An opaque leaf check."""

    representation: CheckRepresentationAnnotation | None = None
    annotations: Annotations | None = None
    aborted: bool = False
    tag: ClassVar[TypingLiteral["Filter"]] = "Filter"


@dataclass(frozen=True, slots=True)
class FilterGroup:
    """A non-empty group of checks."""

    checks: tuple[Check, *tuple[Check, ...]]
    representation: CheckRepresentationAnnotation | None = None
    annotations: Annotations | None = None
    tag: ClassVar[TypingLiteral["FilterGroup"]] = "FilterGroup"


type Check = Filter | FilterGroup


@dataclass(frozen=True, slots=True, kw_only=True)
class _Node:
    annotations: Annotations | None = None
    checks: tuple[Check, ...] = ()


@dataclass(frozen=True, slots=True)
class Null(_Node):
    """Schema representation of ``null``."""

    tag: ClassVar[TypingLiteral["Null"]] = "Null"


@dataclass(frozen=True, slots=True)
class Undefined(_Node):
    """Schema representation of ``undefined``."""

    tag: ClassVar[TypingLiteral["Undefined"]] = "Undefined"


@dataclass(frozen=True, slots=True)
class Void(_Node):
    """Schema representation of ``void``."""

    tag: ClassVar[TypingLiteral["Void"]] = "Void"


@dataclass(frozen=True, slots=True)
class ObjectKeyword(_Node):
    """Schema representation of any object."""

    tag: ClassVar[TypingLiteral["ObjectKeyword"]] = "ObjectKeyword"


@dataclass(frozen=True, slots=True)
class Never(_Node):
    """Schema representation of a type with no values."""

    tag: ClassVar[TypingLiteral["Never"]] = "Never"


@dataclass(frozen=True, slots=True)
class Unknown(_Node):
    """Schema representation of any value, typed as unknown."""

    tag: ClassVar[TypingLiteral["Unknown"]] = "Unknown"


@dataclass(frozen=True, slots=True)
class Any(_Node):
    """Schema representation of any value, typed as any."""

    tag: ClassVar[TypingLiteral["Any"]] = "Any"


@dataclass(frozen=True, slots=True)
class Content:
    """What a string holds: its media type and, when the string's value
    is decoded unchanged, the representation of what it encodes."""

    media_type: str
    schema: Representation | None = None


@dataclass(frozen=True, slots=True)
class String(_Node):
    """Schema representation of a string, with its content encoding if any."""

    content: Content | None = field(default=None, kw_only=True)
    tag: ClassVar[TypingLiteral["String"]] = "String"


@dataclass(frozen=True, slots=True)
class Number(_Node):
    """Schema representation of a number."""

    tag: ClassVar[TypingLiteral["Number"]] = "Number"


@dataclass(frozen=True, slots=True)
class Boolean(_Node):
    """Schema representation of a boolean."""

    tag: ClassVar[TypingLiteral["Boolean"]] = "Boolean"


@dataclass(frozen=True, slots=True)
class BigInt(_Node):
    """Schema representation of a big integer."""

    tag: ClassVar[TypingLiteral["BigInt"]] = "BigInt"


@dataclass(frozen=True, slots=True)
class Literal(_Node):
    """One exact value."""

    literal: LiteralValue
    tag: ClassVar[TypingLiteral["Literal"]] = "Literal"


@dataclass(frozen=True, slots=True)
class Enum(_Node):
    """Enum members as ``(name, value)`` pairs."""

    enums: tuple[tuple[str, EnumValue], ...]
    tag: ClassVar[TypingLiteral["Enum"]] = "Enum"


@dataclass(frozen=True, slots=True)
class TemplateLiteral(_Node):
    """Schema representation of a template literal string, from its parts."""

    parts: tuple[Representation, ...]
    tag: ClassVar[TypingLiteral["TemplateLiteral"]] = "TemplateLiteral"


@dataclass(frozen=True, slots=True)
class Element:
    """A tuple element."""

    type: Representation
    is_optional: bool = False
    annotations: Annotations | None = None


@dataclass(frozen=True, slots=True)
class Arrays(_Node):
    """A tuple: its ``elements``, then the ``rest`` (one node: an array)."""

    elements: tuple[Element, ...] = ()
    rest: tuple[Representation, ...] = ()
    tag: ClassVar[TypingLiteral["Arrays"]] = "Arrays"


@dataclass(frozen=True, slots=True)
class PropertySignature:
    """A property of an object representation: its name, type and whether it is optional."""

    name: PropertyName
    type: Representation
    is_optional: bool = False
    annotations: Annotations | None = None


@dataclass(frozen=True, slots=True)
class IndexSignature:
    """An index signature of an object representation: key type and value type."""

    parameter: Representation
    type: Representation


@dataclass(frozen=True, slots=True)
class Objects(_Node):
    """Schema representation of an object: its properties and index signatures."""

    property_signatures: tuple[PropertySignature, ...] = ()
    index_signatures: tuple[IndexSignature, ...] = ()
    tag: ClassVar[TypingLiteral["Objects"]] = "Objects"


@dataclass(frozen=True, slots=True)
class Union(_Node):
    """Schema representation of a union of types."""

    types: tuple[Representation, ...]
    mode: UnionMode = "any_of"
    tag: ClassVar[TypingLiteral["Union"]] = "Union"


@dataclass(frozen=True, slots=True)
class Declaration(_Node):
    """An opaque declaration; ``representation`` names its reviver."""

    type_parameters: tuple[Representation, ...] = ()
    representation: RepresentationAnnotation | None = field(default=None, kw_only=True)
    tag: ClassVar[TypingLiteral["Declaration"]] = "Declaration"


@dataclass(frozen=True, slots=True)
class Suspend:
    """A lazily resolved node (it has no checks of its own)."""

    thunk: Representation
    annotations: Annotations | None = None
    tag: ClassVar[TypingLiteral["Suspend"]] = "Suspend"


@dataclass(frozen=True, slots=True)
class Reference:
    """A named definition of the document's ``references``."""

    ref: str
    tag: ClassVar[TypingLiteral["Reference"]] = "Reference"


type Representation = (
    Declaration
    | Reference
    | Suspend
    | Null
    | Undefined
    | Void
    | ObjectKeyword
    | Never
    | Unknown
    | Any
    | String
    | Number
    | Boolean
    | BigInt
    | Literal
    | Enum
    | TemplateLiteral
    | Arrays
    | Objects
    | Union
)

type References = Mapping[str, Representation]


@dataclass(frozen=True, slots=True)
class Document:
    """One representation and the definitions it refers to."""

    representation: Representation
    references: References = field(default_factory=dict[str, "Representation"])


@dataclass(frozen=True, slots=True)
class MultiDocument:
    """Several representations sharing their definitions."""

    representations: tuple[Representation, *tuple[Representation, ...]]
    references: References = field(default_factory=dict[str, "Representation"])


def to_multi_document(document: Document) -> MultiDocument:
    """``document`` as a multi-document of one root (Effect's
    ``toMultiDocument``)."""
    return MultiDocument((document.representation,), document.references)
