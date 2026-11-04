"""SQL Server parameter types (tedious's ``TYPES`` and ``ParameterOptions``,
which Effect's ``@effect/sql-mssql`` takes in ``param``, procedure
parameters and ``parameterTypes``).

A ``DataType`` names the type a parameter is sent as; ``ParameterOptions``
sizes it as tedious's options do: ``length`` for character and binary
types (by default the value's length, up to 4000 characters or 8000 bytes,
then ``MAX``), ``precision`` / ``scale`` for ``Decimal`` / ``Numeric``
(18 and 0) and ``scale`` for ``Time``, ``DateTime2`` and
``DateTimeOffset`` (7)::

    sql("SELECT * FROM people WHERE id = {}", client.param(TYPES.BigInt, 1))
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from pyfect.sql.statement import PrimitiveKind

type DataTypeName = Literal[
    "Bit",
    "TinyInt",
    "SmallInt",
    "Int",
    "BigInt",
    "Real",
    "Float",
    "SmallMoney",
    "Money",
    "Decimal",
    "Numeric",
    "Char",
    "VarChar",
    "NChar",
    "NVarChar",
    "Text",
    "NText",
    "Binary",
    "VarBinary",
    "Image",
    "UniqueIdentifier",
    "Xml",
    "Date",
    "Time",
    "SmallDateTime",
    "DateTime",
    "DateTime2",
    "DateTimeOffset",
]


@dataclass(frozen=True, slots=True)
class DataType:
    """A SQL Server type a parameter is sent as (one of ``TYPES``)."""

    name: DataTypeName


@dataclass(frozen=True, slots=True, kw_only=True)
class ParameterOptions:
    """The size of a parameter's type (tedious's ``ParameterOptions``)."""

    length: int | Literal["max"] | None = None
    precision: int | None = None
    scale: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.length, int) and self.length < 1:
            raise ValueError(f"length must be >= 1, got {self.length}")
        if self.precision is not None and not 1 <= self.precision <= 38:
            raise ValueError(f"precision must be in 1..38, got {self.precision}")
        if self.scale is not None and self.scale < 0:
            raise ValueError(f"scale must be >= 0, got {self.scale}")


class TYPES:
    """The types (tedious's ``TYPES``)."""

    Bit: Final = DataType("Bit")
    TinyInt: Final = DataType("TinyInt")
    SmallInt: Final = DataType("SmallInt")
    Int: Final = DataType("Int")
    BigInt: Final = DataType("BigInt")
    Real: Final = DataType("Real")
    Float: Final = DataType("Float")
    SmallMoney: Final = DataType("SmallMoney")
    Money: Final = DataType("Money")
    Decimal: Final = DataType("Decimal")
    Numeric: Final = DataType("Numeric")
    Char: Final = DataType("Char")
    VarChar: Final = DataType("VarChar")
    NChar: Final = DataType("NChar")
    NVarChar: Final = DataType("NVarChar")
    Text: Final = DataType("Text")
    NText: Final = DataType("NText")
    Binary: Final = DataType("Binary")
    VarBinary: Final = DataType("VarBinary")
    Image: Final = DataType("Image")
    UniqueIdentifier: Final = DataType("UniqueIdentifier")
    Xml: Final = DataType("Xml")
    Date: Final = DataType("Date")
    Time: Final = DataType("Time")
    SmallDateTime: Final = DataType("SmallDateTime")
    DateTime: Final = DataType("DateTime")
    DateTime2: Final = DataType("DateTime2")
    DateTimeOffset: Final = DataType("DateTimeOffset")


type ParameterTypes = Mapping[PrimitiveKind, DataType]
"""The type each kind of plain value is sent as."""

default_parameter_types: Final[ParameterTypes] = {
    "string": TYPES.NVarChar,
    "int": TYPES.BigInt,
    "float": TYPES.Float,
    "boolean": TYPES.Bit,
    "datetime": TYPES.DateTime,
    "date": TYPES.Date,
    "bytes": TYPES.VarBinary,
    "null": TYPES.Bit,
}
"""Effect's ``defaultParameterTypes``: strings as ``NVarChar`` (Unicode),
floats as ``Float`` (JavaScript's numbers), ints as ``BigInt`` (its
bigints), bytes as ``VarBinary``, ``None`` as a ``Bit`` NULL."""


__all__ = [
    "TYPES",
    "DataType",
    "DataTypeName",
    "ParameterOptions",
    "ParameterTypes",
    "default_parameter_types",
]
