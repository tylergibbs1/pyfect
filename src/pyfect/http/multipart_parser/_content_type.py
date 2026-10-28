"""``Content-Type`` and ``Content-Disposition`` parsing (from
fastify/fast-content-type-parse, as Effect has it)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote_to_bytes

_QUOTED = (
    r'"(?:[\t\u0020\u0021\u0023-\u005b\u005d-\u007e\u0080-\U0010ffff]'
    r'|\\[\t\u0020-\U0010ffff])*"'
)
_TOKEN = r"[!#$%&'*+.^\w`|~-]+"
_PARAM = re.compile(rf"; *({_TOKEN})=({_QUOTED}|{_TOKEN}) *", re.ASCII)
_DISPOSITION_PARAM = re.compile(
    rf";[ \t]*({_TOKEN})[ \t]*=[ \t]*({_QUOTED}|{_TOKEN})[ \t]*", re.ASCII
)
_QUOTED_PAIR = re.compile(r"\\([\t\u0020-\U0010ffff])")
_MEDIA_TYPE = re.compile(r"^[!#$%&'*+.^\w|~-]+/[!#$%&'*+.^\w|~-]+$", re.ASCII)
_DISPOSITION_TYPE = re.compile(r"^[!#$%&'*+.^\w|~-]+$", re.ASCII)
_EXT_VALUE = re.compile(
    r"^(utf-8|iso-8859-1)'[a-z0-9-]*'((?:%[0-9a-f]{2}|[!#$&+.^_`|~\w-])*)$",
    re.IGNORECASE | re.ASCII,
)
_PCT_ENCODED = re.compile(r"%([0-9a-f]{2})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ContentType:
    value: str = ""
    parameters: dict[str, str] = field(default_factory=dict[str, str])


def parse(header: str | None) -> ContentType:
    """The lowercased media type and its parameters; an invalid header is
    ``ContentType()`` (an empty type)."""
    if header is None:
        return ContentType()
    index = header.find(";")
    media = header[:index].strip() if index != -1 else header.strip()
    if _MEDIA_TYPE.match(media) is None:
        return ContentType()
    parameters: dict[str, str] = {}
    if index == -1:
        return ContentType(media.lower(), parameters)
    while (match := _PARAM.search(header, index)) is not None:
        if match.start() != index:
            return ContentType()
        index += len(match[0])
        key = match[1].lower()
        value = match[2]
        if value.startswith('"'):
            value = _QUOTED_PAIR.sub(r"\1", value[1:-1])
        parameters[key] = value
    if index != len(header):
        return ContentType()
    return ContentType(media.lower(), parameters)


def _decode_ext_value(value: str) -> str | None:
    match = _EXT_VALUE.match(value)
    if match is None:
        return None
    if match[1].lower() == "iso-8859-1":
        return _PCT_ENCODED.sub(lambda m: chr(int(m[1], 16)), match[2])
    try:
        return unquote_to_bytes(match[2]).decode("utf-8")
    except UnicodeDecodeError:
        return None


@dataclass(frozen=True, slots=True)
class ContentDisposition:
    value: str = ""
    parameters: dict[str, str] = field(default_factory=dict[str, str])
    filename: str | None = None


def parse_disposition(header: str | list[str] | None) -> ContentDisposition | None:  # noqa: PLR0911
    """The disposition type, its parameters and file name (``filename*``
    decoded); ``None`` when invalid, repeated, or a parameter repeats."""
    if header is None:
        return ContentDisposition()
    if not isinstance(header, str):
        return None
    index = header.find(";")
    kind = header[:index].strip() if index != -1 else header.strip()
    if _DISPOSITION_TYPE.match(kind) is None:
        return None
    parameters: dict[str, str] = {}
    if index != -1:
        while (match := _DISPOSITION_PARAM.search(header, index)) is not None:
            if match.start() != index:
                return None
            index += len(match[0])
            key = match[1].lower()
            value = match[2]
            if key in parameters:
                return None
            parameters[key] = value[1:-1] if value.startswith('"') else value
        if index != len(header):
            return None
    filename = parameters.get("filename")
    if "filename*" in parameters:
        filename = _decode_ext_value(parameters["filename*"])
        if filename is None:
            return None
    return ContentDisposition(kind.lower(), parameters, filename)
