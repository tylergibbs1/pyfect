"""The references metrics read: the registry that owns every series, and
the attributes added to every update in scope."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pyfect.context import Context, Reference
from pyfect.metric._state import MetricType

type Attributes = Mapping[str, str] | Sequence[tuple[str, str]]
"""Metric attributes: a mapping, or ``(name, value)`` pairs."""

type MetricKey = tuple[MetricType, str, str | None, tuple[tuple[str, str], ...]]
"""A series: kind, id, description and the attributes sorted by name."""


@dataclass(frozen=True, slots=True)
class Hooks:
    """How a series is read and changed. Each takes the updating fiber's
    context."""

    get: Callable[[Context], Any]
    update: Callable[[Any, Context], None]
    modify: Callable[[Any, Context], None]


@dataclass(frozen=True, slots=True)
class Metadata:
    """A registry entry: the series' identity and its hooks."""

    id: str
    type: MetricType
    description: str | None
    attributes: Mapping[str, str] | None
    hooks: Hooks


type Registry = dict[MetricKey, Metadata]


class MetricRegistry(Reference[Registry]):
    """The series of every metric updated in scope. One process-wide dict
    by default; provide a fresh ``{}`` to keep metrics apart."""

    @classmethod
    def default(cls) -> Registry:
        return {}


_NO_ATTRIBUTES: Mapping[str, str] = MappingProxyType({})


class CurrentMetricAttributes(Reference[Mapping[str, str]]):
    """Attributes added to every metric updated in scope. They win over a
    metric's own attributes; ``with_attributes`` wins over them."""

    @classmethod
    def default(cls) -> Mapping[str, str]:
        return _NO_ATTRIBUTES


def to_record(attributes: Attributes | None) -> dict[str, str] | None:
    return None if attributes is None else dict(attributes)


def merge(first: Attributes | None, second: Attributes | None) -> dict[str, str]:
    """``second`` over ``first``; a name keeps the place it first had."""
    return {**(to_record(first) or {}), **(to_record(second) or {})}


def make_key(
    kind: MetricType, id: str, description: str | None, attributes: Mapping[str, str]
) -> MetricKey:
    return (kind, id, description, tuple(sorted(attributes.items())))
