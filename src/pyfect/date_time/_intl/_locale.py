"""A BCP 47 tag resolved as ``Intl.DateTimeFormat`` resolves it under Node:
checked, canonicalized, matched against ICU's locales (else the default
locale), and its calendar, hour cycle and digits chosen as ICU chooses them."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import cache
from typing import Final, Literal

from pyfect.date_time._intl._data import locale_data, meta

type HourChar = Literal["h", "H", "K", "k"]

_LANGUAGE: Final = re.compile(r"[a-z]{2,3}|[a-z]{5,8}")
_SCRIPT: Final = re.compile(r"[a-z]{4}")
_REGION: Final = re.compile(r"[a-z]{2}|[0-9]{3}")
_VARIANT: Final = re.compile(r"[a-z0-9]{5,8}|[0-9][a-z0-9]{3}")
_SUBTAG: Final = re.compile(r"[a-z0-9]{2,8}")
_UNICODE_KEY: Final = re.compile(r"[a-z0-9][a-z]")
_PRIVATE: Final = re.compile(r"[a-z0-9]{1,8}")
_HOUR_CYCLES: Final[dict[str, HourChar]] = {"h11": "K", "h12": "h", "h23": "H", "h24": "k"}
_PREFERRED: Final[dict[str, HourChar]] = {"h": "h", "H": "H", "K": "K", "k": "k"}
_CALENDAR_IDS: Final = {"gregory": "gregorian", "buddhist": "buddhist", "persian": "persian"}
_ICU_CALENDARS: Final = frozenset(
    (
        *_CALENDAR_IDS,
        *("chinese", "coptic", "dangi", "ethioaa", "ethiopic", "hebrew", "indian", "islamic"),
        *("islamic-civil", "islamic-rgsa", "islamic-tbla", "islamic-umalqura", "islamicc"),
        *("iso8601", "japanese", "roc", "ethiopic-amete-alem"),
    )
)
_INVALID: Final = "Incorrect locale information provided"


@dataclass(frozen=True, slots=True)
class _Tag:
    language: str
    script: str
    region: str
    variants: tuple[str, ...]
    keywords: dict[str, str]

    def base(self) -> str:
        return "-".join(p for p in (self.language, self.script, self.region, *self.variants) if p)


@dataclass(frozen=True, slots=True)
class Resolved:
    """What formatting reads from the locale."""

    data_locale: str
    """The CLDR locale holding the names and patterns."""
    calendar: str
    """The calendar the date is in, and whose names and style patterns are used."""
    generator_calendar: str
    """The calendar whose ``availableFormats`` the pattern generator reads."""
    hour_char: HourChar
    """The locale's hour cycle (``-u-hc`` or its region's preference)."""
    allowed_hours: tuple[str, ...]
    explicit_hour_cycle: bool
    """Whether ``-u-hc`` gave the hour cycle."""
    digits: str
    minus_sign: str
    numbering_system: str
    rules_locale: str


def _starts_with_language_id(text: str) -> bool:
    """V8's ``StartsWithUnicodeLanguageId``, its first check of a tag."""
    tokens = text.lower().split("-")
    if tokens and tokens[-1] == "":
        tokens.pop()  # C++'s getline makes no token after a final "-"
    if not tokens or not re.fullmatch(r"[a-z]{2,3}|[a-z]{5,8}", tokens[0]):
        return False
    index = 2 if len(tokens) > 1 and _SCRIPT.fullmatch(tokens[1]) else 1
    if index < len(tokens) and len(tokens[index]) != 1 and _REGION.fullmatch(tokens[index]):
        index += 1
    for token in tokens[index:]:
        if len(token) == 1 and token.isalnum():
            return True
        if not _VARIANT.fullmatch(token):
            return False
    return True


def _parse(text: str) -> _Tag:
    if not _starts_with_language_id(text):
        raise ValueError(_INVALID)
    try:
        return _parse_valid(text)
    except ValueError:
        raise ValueError(f"Invalid language tag: {text.lower()}") from None


def _parse_valid(text: str) -> _Tag:
    parts = text.lower().split("-")
    if "" in parts:
        raise ValueError(_INVALID)
    index = 0

    def take(pattern: re.Pattern[str]) -> str:
        nonlocal index
        if index < len(parts) and pattern.fullmatch(parts[index]):
            index += 1
            return parts[index - 1]
        return ""

    language = take(_LANGUAGE)
    if not language:
        raise ValueError(_INVALID)
    script = take(_SCRIPT).title()
    region = take(_REGION).upper()
    variants: list[str] = []
    while variant := take(_VARIANT):
        if variant in variants:
            raise ValueError(_INVALID)
        variants.append(variant)
    keywords = _extensions(parts[index:])
    return _Tag(language, script, region, tuple(variants), keywords)


def _extensions(parts: list[str]) -> dict[str, str]:
    """The ``-u-`` keywords of a tag's extensions, checked as ICU checks them."""
    keywords: dict[str, str] = {}
    singletons: set[str] = set()
    index = 0
    while index < len(parts):
        singleton = parts[index]
        if len(singleton) != 1 or singleton in singletons:
            raise ValueError(_INVALID)
        singletons.add(singleton)
        index += 1
        if singleton == "x":
            if index == len(parts) or not all(_PRIVATE.fullmatch(p) for p in parts[index:]):
                raise ValueError(_INVALID)
            break
        start = index
        while index < len(parts) and _SUBTAG.fullmatch(parts[index]):
            index += 1
        if index == start:
            raise ValueError(_INVALID)
        if singleton == "u":
            key = ""
            for subtag in parts[start:index]:
                if _UNICODE_KEY.fullmatch(subtag):
                    key = subtag
                    keywords.setdefault(key, "")
                elif key:
                    keywords[key] = f"{keywords[key]}-{subtag}" if keywords[key] else subtag
    return keywords


def _canonical(tag: _Tag) -> _Tag:
    data = meta()
    language = data.language_aliases.get(tag.language, tag.language)
    script, region = tag.script, tag.region
    if "-" in language:
        language, *rest = language.split("-")
        for subtag in rest:
            if len(subtag) == 4 and not script:
                script = subtag.title()
            elif len(subtag) in (2, 3) and not region:
                region = subtag.upper()
    region = data.territory_aliases.get(region, region)
    return _Tag(language, script, region, tag.variants, tag.keywords)


def _maximized(language: str, script: str, region: str) -> tuple[str, str, str]:
    likely = meta().likely
    for key in (
        f"{language}-{script}-{region}" if script and region else "",
        f"{language}-{region}" if region else "",
        f"{language}-{script}" if script else "",
        language,
        f"und-{script}" if script else "",
        f"und-{region}" if region else "",
    ):
        if key and key in likely:
            found_language, found_script, found_region = likely[key].split("-")
            return (
                language if language != "und" else found_language,
                script or found_script,
                region or found_region,
            )
    return language, script, region


def _lookup(tag: _Tag) -> str | None:
    """RFC 4647 lookup of the tag (without extensions) in ICU's locales."""
    parts = tag.base().split("-")
    available = meta().available
    while parts:
        candidate = "-".join(parts)
        if candidate in available:
            return candidate
        parts.pop()
        if parts and len(parts[-1]) == 1:
            parts.pop()
    return None


def default_locale() -> str:
    """The locale ICU takes from the environment (``LC_ALL``, ``LC_MESSAGES``,
    ``LANG``), as Node's default; ``C`` and ``POSIX`` are ``en-US``."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "")
        if value:
            break
    else:
        value = ""
    value = value.split(".")[0].split("@")[0]
    if value in ("", "C", "POSIX"):
        return "en-US"
    try:
        tag = _canonical(_parse(value.replace("_", "-")))
    except ValueError:
        return "en-US"
    return _lookup(tag) or "en-US"


def _hour_formats(language: str, region: str) -> tuple[str, tuple[str, ...]]:
    time_data = meta().time_data
    found = time_data.get(f"{language}-{region}") or time_data.get(region)
    if found is None:
        alias = meta().territory_aliases.get(region)
        if alias is not None:
            found = time_data.get(f"{language}-{alias}") or time_data.get(alias)
    return found or ("H", ("H",))


def resolve(text: str | None) -> Resolved:
    """The locale ``Intl.DateTimeFormat`` uses for ``text``; ``None``, or a
    locale ICU lacks, is the environment's."""
    return _resolve(text, default_locale())


@cache
def _resolve(text: str | None, default: str) -> Resolved:
    tag = _canonical(_parse(default if text is None else text))
    found = _lookup(tag)
    if found is None:
        found = default
        keywords: dict[str, str] = {}
    else:
        keywords = tag.keywords
    matched = _canonical(_parse(found))
    data = meta()
    data_locale = data.available[found]
    language, _, region = _maximized(matched.language, matched.script, matched.region)
    calendar_id = keywords.get("ca", "")
    if calendar_id == "islamicc":
        calendar_id = "islamic-civil"
    if calendar_id in _ICU_CALENDARS:
        calendar = _CALENDAR_IDS.get(calendar_id)
        if calendar is None:
            raise ValueError(f"the {calendar_id} calendar is not supported")
    else:
        preferred = data.calendars.get(region) or data.calendars["001"]
        calendar = preferred[0] if preferred[0] in ("gregorian", "buddhist", "persian") else None
        if calendar is None:
            raise ValueError(f"the {preferred[0]} calendar is not supported")
    if calendar_id in _ICU_CALENDARS:
        generator_calendar = calendar
    else:
        generator_calendar = data.generator_calendars.get(found, "gregorian")
    preferred_hour, allowed = _hour_formats(language, region)
    explicit = _HOUR_CYCLES.get(keywords.get("hc", ""))
    hour_char: HourChar = explicit or _PREFERRED.get(preferred_hour[:1], "H")
    numbering = keywords.get("nu", "")
    if numbering not in data.digits or numbering in ("native", "traditio", "finance"):
        numbering = ""
    numbering = numbering or locale_data(data_locale).numbering_system
    digits = data.digits.get(numbering, "0123456789")
    return Resolved(
        data_locale=data_locale,
        calendar=calendar,
        generator_calendar=generator_calendar,
        hour_char=hour_char,
        allowed_hours=allowed,
        explicit_hour_cycle=explicit is not None,
        digits=digits,
        minus_sign=locale_data(data_locale).minus_signs.get(numbering, "-"),
        numbering_system=numbering,
        rules_locale=matched.base(),
    )
