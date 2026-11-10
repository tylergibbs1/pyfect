"""``CsvError`` and the record types of ``pyfect.encoding.csv``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeIs

from pyfect.errors import TaggedError

type Row = tuple[str, ...]
"""A record as its cells."""

type CsvErrorKind = Literal["Syntax", "RecordSize", "Header"]


@dataclass(eq=False)
class CsvError(TaggedError):
    """Decoding CSV failed. ``record`` is one-based and counts the header row
    and blank lines; ``line`` is the one-based physical line where the record
    starts; ``column`` is the one-based cell of a syntax error, else ``None``."""

    kind: CsvErrorKind
    message: str
    record: int
    line: int
    column: int | None = None

    def __str__(self) -> str:
        return self.message


def is_csv_error(value: object) -> TypeIs[CsvError]:
    return isinstance(value, CsvError)
