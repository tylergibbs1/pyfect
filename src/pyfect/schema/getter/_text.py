"""String getters (Effect's ``trim``, ``capitalize``, ``snakeToCamel``,
``split``, ``splitKeyValue``, ``encodeUriComponent``, ...)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote, unquote

from pyfect._js import trim as js_trim
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter._getter import Getter, Transform, TransformEffect
from pyfect.schema.issue import InvalidValue, Issue, reported


def capitalize_text(text: str) -> str:
    return text[:1].upper() + text[1:]


def uncapitalize_text(text: str) -> str:
    return text[:1].lower() + text[1:]


def snake_to_camel_text(text: str) -> str:
    """Effect's ``String.snakeToCamel``: each ``_`` upper-cases the next
    character and is dropped."""
    if not text or (len(text) % 2 == 0 and text.strip("_") == ""):
        return ""
    out = [text[0]]
    i = 1
    while i < len(text):
        if text[i] == "_":
            i += 1
            out.append(text[i : i + 1].upper())
        else:
            out.append(text[i])
        i += 1
    return "".join(out)


_UPPER = re.compile(r"([A-Z])")


def camel_to_snake_text(text: str) -> str:
    """Effect's ``String.camelToSnake``."""
    return _UPPER.sub(r"_\1", text).lower()


def trim() -> Getter[str, str]:
    """Whitespace removed from both ends, as JavaScript's ``trim``."""
    return Transform(js_trim)


def capitalize() -> Getter[str, str]:
    return Transform(capitalize_text)


def uncapitalize() -> Getter[str, str]:
    return Transform(uncapitalize_text)


def snake_to_camel() -> Getter[str, str]:
    return Transform(snake_to_camel_text)


def camel_to_snake() -> Getter[str, str]:
    return Transform(camel_to_snake_text)


def to_lower_case() -> Getter[str, str]:
    return Transform(str.lower)


def to_upper_case() -> Getter[str, str]:
    return Transform(str.upper)


def split(*, separator: str = ",") -> Getter[Sequence[str], str]:
    """The parts between ``separator``s; ``""`` has none (Effect's ``split``)."""
    return Transform(lambda text: () if text == "" else tuple(text.split(separator)))


def split_key_value(
    *,
    separator: str = ",",
    key_value_separator: str = "=",
    trim: bool = False,
    keep_empty_values: bool = False,
) -> Getter[dict[str, str], str]:
    """``"a=1,b=2"`` as ``{"a": "1", "b": "2"}`` (Effect's ``splitKeyValue``): a pair
    without ``key_value_separator`` or with an empty key is skipped, and one with an empty
    value unless ``keep_empty_values`` (then its value is ``""``); ``trim`` trims keys and
    values first. An empty ``key_value_separator`` takes a pair's first two characters."""

    def run(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for pair in text.split(separator):
            if key_value_separator == "":
                key, value = pair[:1], pair[1:2]
            else:
                index = pair.find(key_value_separator)
                if index == -1:
                    continue
                key, value = pair[:index], pair[index + len(key_value_separator) :]
            if trim:
                key, value = js_trim(key), js_trim(value)
            if key == "" or (value == "" and not keep_empty_values):
                continue
            out[key] = value
        return out

    return Transform(run)


def join_key_value(
    *, separator: str = ",", key_value_separator: str = "="
) -> Getter[str, Mapping[str, str]]:
    """The inverse of ``split_key_value`` (Effect's ``joinKeyValue``)."""
    return Transform(
        lambda pairs: separator.join(f"{k}{key_value_separator}{v}" for k, v in pairs.items())
    )


_URI_SAFE = "-_.!~*'()"
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def encode_uri_component() -> Getter[str, str]:
    """JavaScript's ``encodeURIComponent`` (Effect's ``encodeUriComponent``);
    a lone surrogate raises, a defect."""
    return Transform(lambda text: quote(text, safe=_URI_SAFE))


def decode_uri_component() -> Getter[str, str]:
    """JavaScript's ``decodeURIComponent``; a malformed escape is an
    ``InvalidValue`` (Effect's ``decodeUriComponent``)."""

    def run(text: str, options: ParseOptions) -> Exit[str, Issue]:
        if not _BAD_ESCAPE.search(text):
            try:
                return Success(unquote(text, errors="strict"))
            except UnicodeDecodeError:
                pass
        expected = {"expected": "a valid URI component"}
        return fail_exit(InvalidValue(expected, reported(text, options)))

    return TransformEffect(run)
