"""Revivers: how ``from_representation`` rebuilds an opaque declaration or
check from its persistence identity (Effect's ``DeclarationReviver``,
``FilterReviver``, ``FilterGroupReviver``).

A reviver has the ``id`` it answers, a ``payload_schema`` (the payload is
decoded with its JSON codec first) and ``revive``, given the payload, the
revived schemas the node holds and the node's annotations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Never, TypeVar

from pyfect.schema._schema import Bottom, Codec, Top
from pyfect.schema.ast import Annotations, Filter, FilterGroup

type PayloadSchema[P] = Codec[P, Any, Never, Never]

type AnySchema = Bottom[object, object, object, object]
"""A revived schema: its node is known, its types are not (Effect's
``Schema.Top``)."""


P_co = TypeVar("P_co", covariant=True)


@dataclass(frozen=True, slots=True)
class DeclarationInput(Generic[P_co]):
    payload: P_co
    type_parameters: tuple[AnySchema, ...]
    annotations: Annotations | None


@dataclass(frozen=True, slots=True)
class CheckInput(Generic[P_co]):
    payload: P_co
    schemas: tuple[AnySchema, ...]
    """The revived schemas of the check's ``representation.schemas``."""
    annotations: Annotations | None


@dataclass(frozen=True, slots=True)
class DeclarationReviver[P]:
    id: str
    payload_schema: PayloadSchema[P]
    revive: Callable[[DeclarationInput[P]], Top]
    kind: ClassVar[str] = "declaration"


@dataclass(frozen=True, slots=True)
class FilterReviver[P]:
    id: str
    payload_schema: PayloadSchema[P]
    revive: Callable[[CheckInput[P]], Filter[Any]]
    kind: ClassVar[str] = "filter"


@dataclass(frozen=True, slots=True)
class FilterGroupReviver[P]:
    id: str
    payload_schema: PayloadSchema[P]
    revive: Callable[[CheckInput[P]], FilterGroup[Any]]
    kind: ClassVar[str] = "filter_group"


type AnyReviver = DeclarationReviver[Any] | FilterReviver[Any] | FilterGroupReviver[Any]


def make_reviver_declaration[P](
    id: str, payload_schema: PayloadSchema[P], revive: Callable[[DeclarationInput[P]], Top], /
) -> DeclarationReviver[P]:
    """A declaration reviver, its payload type read from ``payload_schema``."""
    return DeclarationReviver(id, payload_schema, revive)


def make_reviver_filter[P](
    id: str, payload_schema: PayloadSchema[P], revive: Callable[[CheckInput[P]], Filter[Any]], /
) -> FilterReviver[P]:
    """A filter reviver, its payload type read from ``payload_schema``."""
    return FilterReviver(id, payload_schema, revive)


def make_reviver_filter_group[P](
    id: str,
    payload_schema: PayloadSchema[P],
    revive: Callable[[CheckInput[P]], FilterGroup[Any]],
    /,
) -> FilterGroupReviver[P]:
    """A filter group reviver, its payload type read from ``payload_schema``."""
    return FilterGroupReviver(id, payload_schema, revive)
