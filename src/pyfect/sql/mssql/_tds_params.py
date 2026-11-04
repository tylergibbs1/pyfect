"""Parameters as pytds sends them: each ``DataType`` as a pytds SQL type,
sized as tedious sizes it, and each value in the form its serializer
takes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from pytds import tds_types  # pyright: ignore[reportMissingTypeStubs]

from pyfect.sql.mssql._driver import TypedValue
from pyfect.sql.mssql.types import DataTypeName, ParameterOptions

_DEFAULT_PRECISION = 18
_DEFAULT_SCALE = 0
_DEFAULT_TIME_SCALE = 7


def _utf16_units(text: str) -> int:
    """``text``'s length as JavaScript counts it (UTF-16 code units), the
    unit SQL Server sizes ``NVARCHAR`` in."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _length(options: ParameterOptions, value: object, maximum: int) -> int | None:
    """The length tedious gives the type: the options', else the value's
    (at least 1), else the type's ``maximum`` (a null, as an output
    parameter's); ``None`` for ``MAX``."""
    if options.length == "max":
        return None
    if options.length is not None:
        return options.length
    if value is None:
        return maximum
    if isinstance(value, memoryview):
        return cast("memoryview[int]", value).nbytes or 1
    if isinstance(value, bytes | bytearray):
        return len(value) or 1
    size = _utf16_units(value if isinstance(value, str) else str(value))
    return size or 1


def _variable(
    sized: Callable[[int], Any], unbounded: Callable[[], Any], maximum: int
) -> Callable[[ParameterOptions, object], Any]:
    def make(options: ParameterOptions, value: object) -> Any:
        length = _length(options, value, maximum)
        return unbounded() if length is None or length > maximum else sized(length)

    return make


def _fixed(sized: Callable[[int], Any], maximum: int) -> Callable[[ParameterOptions, object], Any]:
    return lambda options, value: sized(_length(options, value, maximum) or maximum)


def _plain(make: Callable[[], Any]) -> Callable[[ParameterOptions, object], Any]:
    return lambda _options, _value: make()


def _decimal(options: ParameterOptions, _value: object) -> Any:
    return tds_types.DecimalType(
        precision=options.precision or _DEFAULT_PRECISION,
        scale=_DEFAULT_SCALE if options.scale is None else options.scale,
    )


def _scaled(make: Callable[[int], Any]) -> Callable[[ParameterOptions, object], Any]:
    return lambda options, _value: make(
        _DEFAULT_TIME_SCALE if options.scale is None else options.scale
    )


_SQL_TYPES: dict[DataTypeName, Callable[[ParameterOptions, object], Any]] = {
    "Bit": _plain(tds_types.BitType),
    "TinyInt": _plain(tds_types.TinyIntType),
    "SmallInt": _plain(tds_types.SmallIntType),
    "Int": _plain(tds_types.IntType),
    "BigInt": _plain(tds_types.BigIntType),
    "Real": _plain(tds_types.RealType),
    "Float": _plain(tds_types.FloatType),
    "SmallMoney": _plain(tds_types.SmallMoneyType),
    "Money": _plain(tds_types.MoneyType),
    "Decimal": _decimal,
    "Numeric": _decimal,
    "Char": _fixed(tds_types.CharType, 8000),
    "VarChar": _variable(tds_types.VarCharType, tds_types.VarCharMaxType, 8000),
    "NChar": _fixed(tds_types.NCharType, 4000),
    "NVarChar": _variable(tds_types.NVarCharType, tds_types.NVarCharMaxType, 4000),
    "Text": _plain(tds_types.TextType),
    "NText": _plain(tds_types.NTextType),
    "Binary": _fixed(tds_types.BinaryType, 8000),
    "VarBinary": _variable(tds_types.VarBinaryType, tds_types.VarBinaryMaxType, 8000),
    "Image": _plain(tds_types.ImageType),
    "UniqueIdentifier": _plain(tds_types.UniqueIdentifierType),
    "Xml": _plain(tds_types.XmlType),
    "Date": _plain(tds_types.DateType),
    "Time": _scaled(lambda scale: tds_types.TimeType(precision=scale)),
    "SmallDateTime": _plain(tds_types.SmallDateTimeType),
    "DateTime": _plain(tds_types.DateTimeType),
    "DateTime2": _scaled(lambda scale: tds_types.DateTime2Type(precision=scale)),
    "DateTimeOffset": _scaled(lambda scale: tds_types.DateTimeOffsetType(precision=scale)),
}

_TEXT: frozenset[DataTypeName] = frozenset(
    {"Char", "VarChar", "NChar", "NVarChar", "Text", "NText", "Xml"}
)
_BINARY: frozenset[DataTypeName] = frozenset({"Binary", "VarBinary", "Image"})
_DECIMAL: frozenset[DataTypeName] = frozenset({"Decimal", "Numeric", "SmallMoney", "Money"})
_UTC_WALL_CLOCK: frozenset[DataTypeName] = frozenset({"SmallDateTime", "DateTime", "DateTime2"})


def _value(name: DataTypeName, value: object) -> object:  # noqa: PLR0911
    """``value`` as the serializer of ``name`` takes it. As tedious (with
    ``useUTC``), an aware datetime is sent as its UTC wall clock, and a
    naive one as a UTC time for ``DateTimeOffset``."""
    if value is None:
        return None
    if name in _TEXT and not isinstance(value, str):
        return str(value)
    if name in _BINARY and isinstance(value, bytearray):
        return bytes(value)
    if name in _BINARY and isinstance(value, memoryview):
        return cast("memoryview[int]", value).tobytes()
    if name in _DECIMAL and isinstance(value, int | float) and not isinstance(value, bool):
        return Decimal(str(value))
    if name == "UniqueIdentifier" and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(value, datetime):
        if name in _UTC_WALL_CLOCK and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        if name == "DateTimeOffset" and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        if name == "Date":
            return value.date()
    if name in _UTC_WALL_CLOCK and type(value) is date:
        return datetime(value.year, value.month, value.day)
    return value


def sql_type(parameter: TypedValue) -> Any:
    """The pytds SQL type ``parameter`` is declared as."""
    return _SQL_TYPES[parameter.type.name](parameter.options, parameter.value)


def value(parameter: TypedValue) -> object:
    """The value of ``parameter`` as pytds writes it."""
    return _value(parameter.type.name, parameter.value)


__all__ = ["sql_type", "value"]
