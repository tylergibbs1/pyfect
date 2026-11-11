"""``console.table``'s box drawing, as Node draws it."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence

_INDEX = "(index)"
_VALUES = "Values"


def text(value: object) -> str:
    """How the console writes a logged item: strings as they are, anything
    else by ``repr``."""
    return value if isinstance(value, str) else repr(value)


def _fields(row: object) -> dict[object, object] | None:
    """A row's cells by column, or ``None`` for a scalar row."""
    if isinstance(row, Mapping):
        return dict(row)  # pyright: ignore[reportUnknownArgumentType]
    if isinstance(row, Iterable) and not isinstance(row, (str, bytes, bytearray)):
        return dict(enumerate(row))  # pyright: ignore[reportUnknownArgumentType]
    return None


def format_table(data: object, properties: Sequence[str] | None) -> str | None:
    """The table Node's ``console.table`` draws for ``data``, or ``None``
    when ``data`` is not tabular (a scalar or a string).

    A mapping's keys index its rows, any other iterable's positions do.
    Mapping and iterable rows spread into columns; scalar rows go in a
    ``Values`` column. ``properties`` picks the columns (and drops
    ``Values``)."""
    index = _fields(data)
    if index is None:
        return None
    columns: dict[object, dict[int, str]] = {key: {} for key in properties or ()}
    values: dict[int, str] = {}
    for i, row in enumerate(index.values()):
        fields = _fields(row)
        if properties is None and fields is None:
            values[i] = repr(row)
            continue
        for key in properties if properties is not None else (fields or {}):
            cells = columns.setdefault(key, {})
            if fields is not None and key in fields:
                cells[i] = repr(fields[key])
    header = [_INDEX, *(text(key) for key in columns)]
    body: list[list[str]] = [
        [text(key), *(cells.get(i, "") for cells in columns.values())]
        for i, key in enumerate(index)
    ]
    if values:
        header.append(_VALUES)
        for i, row in enumerate(body):
            row.append(values.get(i, ""))
    return _render(header, body)


def _width(cell: str) -> int:
    """Terminal columns, as Node's ``getStringWidth`` counts them: wide
    (CJK, emoji) characters take two, combining marks none."""
    return sum(
        0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        for ch in cell
    )


def _render(header: list[str], body: list[list[str]]) -> str:
    widths = [max(_width(row[c]) for row in [header, *body]) + 2 for c in range(len(header))]

    def rule(left: str, middle: str, right: str) -> str:
        return left + middle.join("─" * w for w in widths) + right

    def line(row: list[str]) -> str:
        cells = (
            f" {cell}{' ' * (w - 1 - _width(cell))}" for cell, w in zip(row, widths, strict=True)
        )
        return "│" + "│".join(cells) + "│"

    return "\n".join(
        [
            rule("┌", "┬", "┐"),
            line(header),
            rule("├", "┼", "┤"),
            *(line(row) for row in body),
            rule("└", "┴", "┘"),
        ]
    )
