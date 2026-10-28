"""String checks (Effect's ``isTrimmed``, ``isPattern``, ``isUUID``, ...).

Each takes annotations as keyword arguments, merged over its defaults
(``S.is_trimmed(message="no spaces")``). Patterns are Python regular
expressions, tested with ``search`` as JavaScript's ``RegExp.test``; the
built-in ones match JavaScript's (``$`` ends the string, ``\\d`` is ASCII).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from pyfect._js import trim
from pyfect.logger._text import json_quote
from pyfect.schema.ast import Filter, filter_of

type UUIDVersion = Literal[1, 2, 3, 4, 5, 6, 7, 8]


def string_filter(
    predicate: Callable[[str], bool],
    expected: str | None,
    representation: str,
    payload: object,
    annotations: dict[str, object],
) -> Filter[str]:
    """A built-in string filter: Effect's ``expected`` text and
    ``representation`` (id and payload), under the caller's annotations."""
    defaults: dict[str, object] = {
        "representation": {"id": f"effect/schema/{representation}", "payload": payload}
    }
    if expected is not None:
        defaults["expected"] = expected
    return filter_of(predicate, {**defaults, **annotations})


def _search(regex: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda s: regex.search(s) is not None


def js_regex(source: str) -> re.Pattern[str]:
    """A JavaScript pattern of Effect's as Python reads it: ``$`` only at
    the very end, ASCII ``\\d``."""
    return re.compile(source.replace("$", r"\Z"), re.ASCII)


def is_pattern(pattern: re.Pattern[str] | str, /, **annotations: object) -> Filter[str]:
    """A string ``pattern`` finds a match in (``re.search``)."""
    regex = re.compile(pattern) if isinstance(pattern, str) else pattern
    return _pattern(regex, regex.pattern, annotations)


def _pattern(regex: re.Pattern[str], source: str, annotations: dict[str, object]) -> Filter[str]:
    return string_filter(
        _search(regex),
        f"a string matching the RegExp {source}",
        "isPattern",
        {"source": source, "flags": regex.flags},
        annotations,
    )


def is_trimmed(**annotations: object) -> Filter[str]:
    """A string with no leading or trailing whitespace (JavaScript's)."""
    return string_filter(
        lambda s: trim(s) == s,
        "a string with no leading or trailing whitespace",
        "isTrimmed",
        None,
        annotations,
    )


_FINITE_PATTERN = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?"
_FINITE = re.compile(rf"^{_FINITE_PATTERN}\Z", re.ASCII)
_BIGINT = re.compile(r"^-?\d+\Z", re.ASCII)


def is_string_finite(**annotations: object) -> Filter[str]:
    """A string spelling a finite number (``"1"``, ``"-.5E+5"``)."""
    return string_filter(
        _search(_FINITE),
        "a string representing a finite number",
        "isStringFinite",
        None,
        annotations,
    )


def is_string_big_int(**annotations: object) -> Filter[str]:
    """A string spelling an integer (``"-12"``; no ``+``)."""
    return string_filter(
        _search(_BIGINT),
        "a string representing a bigint",
        "isStringBigInt",
        None,
        annotations,
    )


_ANY_UUID = (
    "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
    "|00000000-0000-0000-0000-000000000000|[fF]{8}-[fF]{4}-[fF]{4}-[fF]{4}-[fF]{12})$"
)


def is_uuid(version: UUIDVersion | None = None, /, **annotations: object) -> Filter[str]:
    """A UUID (any version, or the nil and max UUIDs), or one of ``version``."""
    source = (
        _ANY_UUID
        if version is None
        else f"^([0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-{version}[0-9a-fA-F]{{3}}"
        "-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$"
    )
    return string_filter(
        _search(js_regex(source)),
        "a UUID" if version is None else f"a UUID v{version}",
        "isUUID",
        {"version": version},
        annotations,
    )


_GUID = "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
_ULID = "^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$"


def is_guid(**annotations: object) -> Filter[str]:
    return string_filter(_search(js_regex(_GUID)), "a GUID", "isGUID", None, annotations)


def is_ulid(**annotations: object) -> Filter[str]:
    """A ULID; it fails with the pattern's text, as in Effect."""
    return string_filter(
        _search(js_regex(_ULID)),
        f"a string matching the RegExp {_ULID}",
        "isULID",
        None,
        annotations,
    )


_BASE64 = re.compile(r"[0-9a-zA-Z+/]*={0,2}")
_BASE64_URL = re.compile(r"[0-9a-zA-Z\-_]*={0,2}")


def is_base64(**annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: len(s) % 4 == 0 and _BASE64.fullmatch(s) is not None,
        "a base64 encoded string",
        "isBase64",
        None,
        annotations,
    )


def is_base64_url(**annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: (
            _BASE64_URL.fullmatch(s) is not None
            and (len(s) % 4 == 0 if s.endswith("=") else len(s) % 4 != 1)
        ),
        "a base64url encoded string",
        "isBase64Url",
        None,
        annotations,
    )


def is_starting_with(prefix: str, /, **annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: s.startswith(prefix),
        f"a string starting with {json_quote(prefix)}",
        "isStartingWith",
        {"startsWith": prefix},
        annotations,
    )


def is_ending_with(suffix: str, /, **annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: s.endswith(suffix),
        f"a string ending with {json_quote(suffix)}",
        "isEndingWith",
        {"endsWith": suffix},
        annotations,
    )


def is_including(part: str, /, **annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: part in s,
        f"a string including {json_quote(part)}",
        "isIncluding",
        {"includes": part},
        annotations,
    )


def is_uppercased(**annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: s.upper() == s,
        "a string with all characters in uppercase",
        "isUppercased",
        None,
        annotations,
    )


def is_lowercased(**annotations: object) -> Filter[str]:
    return string_filter(
        lambda s: s.lower() == s,
        "a string with all characters in lowercase",
        "isLowercased",
        None,
        annotations,
    )


def is_capitalized(**annotations: object) -> Filter[str]:
    """A string whose first character (if any) is uppercase."""
    return string_filter(
        lambda s: s[:1].upper() == s[:1],
        "a string with the first character in uppercase",
        "isCapitalized",
        None,
        annotations,
    )


def is_uncapitalized(**annotations: object) -> Filter[str]:
    """A string whose first character (if any) is lowercase."""
    return string_filter(
        lambda s: s[:1].lower() == s[:1],
        "a string with the first character in lowercase",
        "isUncapitalized",
        None,
        annotations,
    )
