"""Model dates and timestamps (Effect's ``Model.Date``, ``DateTimeInsert``,
``DateTimeUpdate``, ...): timestamps the application sets when a row is
inserted or updated, unless the caller gives one with ``override``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Never

from pyfect.date_time import now
from pyfect.schema import transformation as T
from pyfect.schema._codecs import DateTimeUtcFromDate, DateTimeUtcFromMillis, DateTimeUtcFromString
from pyfect.schema._primitives import String
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._values import DateTimeUtc
from pyfect.schema.getter import date_time_utc_from_input, transform
from pyfect.schema.variant_schema import Field, Overrideable, WithConstructorDefault


def _remove_time(value: datetime) -> datetime:
    """Midnight UTC of the value's UTC date (Effect's ``DateTime.removeTime``)."""
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def _format_iso_date(value: datetime) -> str:
    """``YYYY-MM-DD`` (Effect's ``DateTime.formatIsoDate``)."""
    return value.astimezone(UTC).date().isoformat()


Date: DecodeToSchema[datetime, str] = String.pipe(
    decode_to(
        DateTimeUtc,
        T.Transformation(date_time_utc_from_input().map(_remove_time), transform(_format_iso_date)),
    )
)
"""A date (``YYYY-MM-DD``) as the UTC ``datetime`` of its midnight."""

DateWithNow: WithConstructorDefault[datetime, str, Never, Never] = Overrideable(
    Date, default_value=now().map(_remove_time)
)
DateTimeWithNow: WithConstructorDefault[datetime, str, Never, Never] = Overrideable(
    DateTimeUtcFromString, default_value=now()
)
DateTimeFromDateWithNow: WithConstructorDefault[datetime, datetime, Never, Never] = Overrideable(
    DateTimeUtcFromDate, default_value=now()
)
DateTimeFromNumberWithNow: WithConstructorDefault[datetime, int, Never, Never] = Overrideable(
    DateTimeUtcFromMillis, default_value=now()
)

DateTimeInsert: Field[datetime] = Field(
    {"select": DateTimeUtcFromString, "insert": DateTimeWithNow, "json": DateTimeUtcFromString}
)
"""A creation timestamp stored as ISO text: set to now when inserted."""

DateTimeInsertFromDate: Field[datetime] = Field(
    {
        "select": DateTimeUtcFromDate,
        "insert": DateTimeFromDateWithNow,
        "json": DateTimeUtcFromString,
    }
)
"""A creation timestamp the driver reads as a ``datetime``."""

DateTimeInsertFromNumber: Field[datetime] = Field(
    {
        "select": DateTimeUtcFromMillis,
        "insert": DateTimeFromNumberWithNow,
        "json": DateTimeUtcFromMillis,
    }
)
"""A creation timestamp stored as epoch milliseconds."""

DateTimeUpdate: Field[datetime] = Field(
    {
        "select": DateTimeUtcFromString,
        "insert": DateTimeWithNow,
        "update": DateTimeWithNow,
        "json": DateTimeUtcFromString,
    }
)
"""An update timestamp stored as ISO text: set to now when inserted or
updated."""

DateTimeUpdateFromDate: Field[datetime] = Field(
    {
        "select": DateTimeUtcFromDate,
        "insert": DateTimeFromDateWithNow,
        "update": DateTimeFromDateWithNow,
        "json": DateTimeUtcFromString,
    }
)
"""An update timestamp the driver reads as a ``datetime``."""

DateTimeUpdateFromNumber: Field[datetime] = Field(
    {
        "select": DateTimeUtcFromMillis,
        "insert": DateTimeFromNumberWithNow,
        "update": DateTimeFromNumberWithNow,
        "json": DateTimeUtcFromMillis,
    }
)
"""An update timestamp stored as epoch milliseconds."""
