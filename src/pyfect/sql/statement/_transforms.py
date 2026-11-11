"""Row transforms (renaming result columns) and value kinds."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, cast

type Rows = Sequence[Any]
"""Rows as a driver returns them: mappings, nested lists, or scalars."""


@dataclass(frozen=True, slots=True)
class RowTransforms:
    """Renaming functions made by ``default_transforms``: for one value, one
    row (``object``) and a list of rows (``array``)."""

    value: Callable[[object], object]
    object: Callable[[Mapping[str, object]], dict[str, object]]
    array: Callable[[Rows], list[Any]]


def default_transforms(transformer: Callable[[str], str], nested: bool = True) -> RowTransforms:
    """Rename every key of each row with ``transformer``; with ``nested``
    (the default), also the keys of mappings inside a row and of lists of
    mappings inside a row. Lists, ``None`` and scalars among the rows stay
    as they are."""

    def transform_value(value: object) -> object:
        if isinstance(value, (list, tuple)):
            items = cast("Sequence[object]", value)
            if not items or not isinstance(items[0], Mapping):
                return items
            return array(items)
        if isinstance(value, Mapping):
            return transform_object(value)  # pyright: ignore[reportUnknownArgumentType]
        return value

    def transform_object(obj: Mapping[str, object]) -> dict[str, object]:
        return {transformer(key): transform_value(value) for key, value in obj.items()}

    def transform_array(rows: Rows, values: Callable[[object], object]) -> list[Any]:
        result: list[Any] = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                result.append(transform_array(row, values))  # pyright: ignore[reportUnknownArgumentType]
            elif isinstance(row, Mapping):
                entries: Mapping[str, object] = row  # pyright: ignore[reportUnknownVariableType]
                result.append({transformer(key): values(value) for key, value in entries.items()})
            else:
                result.append(row)
        return result

    def keep(value: object) -> object:
        return value

    def array(rows: Rows) -> list[Any]:
        return transform_array(rows, transform_value if nested else keep)

    return RowTransforms(transform_value, transform_object, array)


type PrimitiveKind = Literal[
    "string", "int", "float", "boolean", "datetime", "date", "null", "bytes"
]


def primitive_kind(value: object) -> PrimitiveKind:  # noqa: PLR0911
    """The kind of a bound value, for drivers that type their parameters;
    other values count as strings."""
    match value:
        case None:
            return "null"
        case bool():
            return "boolean"
        case int():
            return "int"
        case float():
            return "float"
        case str():
            return "string"
        case datetime():
            return "datetime"
        case date():
            return "date"
        case bytes() | bytearray() | memoryview():
            return "bytes"
        case _:
            return "string"


__all__ = ["PrimitiveKind", "RowTransforms", "Rows", "default_transforms", "primitive_kind"]
