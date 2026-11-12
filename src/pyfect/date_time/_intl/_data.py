"""The CLDR data ``Intl.DateTimeFormat`` formats with under Node, from
``cldr.zip`` (written by ``scripts/gen_intl_cldr.py``): the release Node's ICU
is built from, so the names and patterns are the ones Effect prints.

The archive holds each locale as what it changes in its parent's data; it is
read here once, into typed values.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any, Final, cast

from pyfect._json_text import parse

type _Json = dict[str, Any]

STYLES: Final = ("full", "long", "medium", "short")


@dataclass(frozen=True, slots=True)
class Meta:
    """Versions, the locales ICU has, and CLDR's supplemental data."""

    node: str
    icu: str
    cldr: str
    tz: str
    available: dict[str, str]
    """Each tag ICU accepts, and the CLDR locale holding its data."""
    generator_calendars: dict[str, str]
    """The calendar ICU's pattern generator reads per tag, where not Gregorian."""
    likely: dict[str, str]
    parents: dict[str, str]
    time_data: dict[str, tuple[str, tuple[str, ...]]]
    """Region (or ``language-REGION``): the preferred and the allowed hour formats."""
    calendars: dict[str, tuple[str, ...]]
    day_period_rules: dict[str, dict[str, dict[str, str]]]
    digits: dict[str, str]
    metazones: dict[str, tuple[tuple[str, str, str], ...]]
    """ICU's: per zone, the metazone and the UTC minutes it starts and ends
    (``1970-01-01 00:00``)."""
    language_aliases: dict[str, str]
    territory_aliases: dict[str, str]


@dataclass(frozen=True, slots=True)
class CalendarData:
    months: dict[str, dict[str, tuple[str, ...]]]
    """Context (``format``, ``stand-alone``), then width, then the twelve names."""
    days: dict[str, dict[str, tuple[str, ...]]]
    """Context, then width, then the names from Sunday."""
    day_periods: dict[str, dict[str, dict[str, str]]]
    eras: dict[str, dict[int, str]]
    date_formats: tuple[str, ...]
    time_formats: tuple[str, ...]
    date_time_formats: tuple[str, ...]
    at_time: tuple[str, ...]
    available_formats: tuple[tuple[str, str], ...]
    """Skeleton and pattern, in the order ICU reads them: the locale's own
    first, then each parent's."""
    append_items: dict[str, str]


@dataclass(frozen=True, slots=True)
class LocaleData:
    calendars: dict[str, CalendarData]
    fields: dict[str, str]
    zone_formats: dict[str, str]
    zones: dict[str, dict[str, dict[str, str]]]
    metazones: dict[str, dict[str, dict[str, str]]]
    numbering_system: str
    minus_signs: dict[str, str]
    """Per numbering system."""


@cache
def _read(name: str) -> _Json:
    with (
        resources.files(__package__).joinpath("cldr.zip").open("rb") as file,
        zipfile.ZipFile(file) as archive,
    ):
        return cast("_Json", parse(archive.read(name)))


@cache
def meta() -> Meta:
    data = _read("meta.json")
    return Meta(
        node=data["node"],
        icu=data["icu"],
        cldr=data["cldr"],
        tz=data["tz"],
        available=data["available"],
        generator_calendars=data["generatorCalendars"],
        likely=data["likely"],
        parents=data["parents"],
        time_data={
            key: (preferred, tuple(allowed))
            for key, (preferred, allowed) in data["timeData"].items()
        },
        calendars={key: tuple(value) for key, value in data["calendars"].items()},
        day_period_rules=data["dayPeriodRules"],
        digits=data["digits"],
        metazones={
            key: tuple((name, start, end) for name, start, end in value)
            for key, value in data["metazones"].items()
        },
        language_aliases=data["languageAliases"],
        territory_aliases=data["territoryAliases"],
    )


def parent(locale: str) -> str | None:
    """CLDR's parent of a data locale; ``und`` (root) has none."""
    if locale == "und":
        return None
    found = meta().parents.get(locale)
    if found is not None:
        return found
    return locale.rsplit("-", 1)[0] if "-" in locale else "und"


def chain(locale: str) -> list[str]:
    """``locale``, its parent, and so on to root."""
    found: list[str] = []
    current: str | None = locale
    while current is not None:
        found.append(current)
        current = parent(current)
    return found


def _merge(base: _Json, change: _Json) -> _Json:
    merged = dict(base)
    for key, value in change.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], cast("_Json", value))
        else:
            merged[key] = value
    return merged


@cache
def _diff(locale: str) -> _Json:
    return _read(f"locales/{locale}.json")


@cache
def _resolved(locale: str) -> _Json:
    up = parent(locale)
    return _diff(locale) if up is None else _merge(_resolved(up), _diff(locale))


def _calendar(locale: str, name: str) -> CalendarData:
    data = _resolved(locale)["calendars"][name]
    return CalendarData(
        months=_contexts(data["months"]),
        days=_contexts(data["days"]),
        day_periods=data["dayPeriods"],
        eras=_eras(data["eras"]),
        date_formats=tuple(data["dateFormats"]),
        time_formats=tuple(data["timeFormats"]),
        date_time_formats=tuple(data["dateTimeFormats"]),
        at_time=tuple(data["atTime"]),
        available_formats=tuple(
            (skeleton, pattern) for skeleton, pattern in data["availableFormats"]
        ),
        append_items=data["appendItems"],
    )


def _eras(table: _Json) -> dict[str, dict[int, str]]:
    return {width: dict(enumerate(cast("list[str]", names))) for width, names in table.items()}


def _contexts(table: _Json) -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        context: {width: tuple(names) for width, names in widths.items()}
        for context, widths in table.items()
    }


@cache
def locale_data(locale: str) -> LocaleData:
    """The data of a CLDR locale (a value of ``Meta.available``)."""
    data = _resolved(locale)
    return LocaleData(
        calendars={name: _calendar(locale, name) for name in data["calendars"]},
        fields=data["fields"],
        zone_formats=data["zoneFormats"],
        zones=data["zones"],
        metazones=data["metazones"],
        numbering_system=data["numberingSystem"],
        minus_signs=data["minusSigns"],
    )
