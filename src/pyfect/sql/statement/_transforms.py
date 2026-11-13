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

    keys = _KeyTransform(transformer, nested)
    return RowTransforms(keys.transform_value, keys.transform_object, keys.array)


class _KeyTransform:
    __slots__ = ("nested", "transformer")

    def __init__(self, transformer: Callable[[str], str], nested: bool) -> None:
        self.transformer = transformer
        self.nested = nested

    def transform_value(self, value: object) -> object:
        if isinstance(value, (list, tuple)):
            items = cast("Sequence[object]", value)
            if not items or not isinstance(items[0], Mapping):
                return items
            return self.array(items)
        if isinstance(value, Mapping):
            return self.transform_object(value)  # pyright: ignore[reportUnknownArgumentType]
        return value

    def transform_object(self, obj: Mapping[str, object]) -> dict[str, object]:
        transformer = self.transformer
        return {transformer(key): self.transform_value(value) for key, value in obj.items()}

    def transform_array(self, rows: Rows, values: Callable[[object], object]) -> list[Any]:
        transformer = self.transformer
        result: list[Any] = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                result.append(self.transform_array(row, values))  # pyright: ignore[reportUnknownArgumentType]
            elif isinstance(row, Mapping):
                entries: Mapping[str, object] = row  # pyright: ignore[reportUnknownVariableType]
                result.append({transformer(key): values(value) for key, value in entries.items()})
            else:
                result.append(row)
        return result

    def array(self, rows: Rows) -> list[Any]:
        return self.transform_array(rows, self.transform_value if self.nested else _keep)


def _keep(value: object) -> object:
    return value


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
