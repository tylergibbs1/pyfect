"""INI text to nested dicts (Effect's ``encoding/Ini``, adapted from the
``ini`` 7.0.0 package).

``[a.b]`` sections nest (``\\.`` keeps a literal dot), ``key[]`` collects
values into a list, a key without ``=`` is ``True``, and the values
``true`` / ``false`` / ``null`` become ``True`` / ``False`` / ``None``.
Quoted values are read as JSON strings when they parse; ``;`` and ``#``
start a comment in an unquoted value unless escaped."""

from __future__ import annotations

import json
import re
from typing import Any, cast

_SECTION = re.compile(r"\[([^\]]*)\]\s*")
_PROPERTY = re.compile(r"([^=]+)(=(.*))?", re.DOTALL)
_LINES = re.compile(r"[\r\n]+")
_BLANK_OR_COMMENT = re.compile(r"\s*(?:[;#]|$)")


def _split_sections(value: str) -> list[str]:
    sections: list[str] = []
    start = 0
    index = value.find(".")
    while index != -1:
        if index == 0 or value[index - 1] != "\\":
            sections.append(value[start:index])
            start = index + 1
        index = value.find(".", index + 1)
    sections.append(value[start:])
    return sections


def _key(value: object) -> str:
    """A parsed key as JavaScript's ``String`` writes it."""
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    return json.dumps(value)


def _is_quoted(value: str) -> bool:
    return len(value) >= 2 and (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    )


def _unquote(text: str | None) -> object:
    """The value of ``text``: a quoted one read as JSON when it parses (so
    ``'5'`` is ``5``, as in Effect), an unquoted one up to its comment."""
    value = (text or "").strip()
    if _is_quoted(value):
        if value[0] == "'":
            value = value[1:-1]
        try:
            return json.loads(value)
        except ValueError:
            return value
    escaped = False
    output = ""
    for character in value:
        if escaped:
            output += character if character in ";#\\" else f"\\{character}"
            escaped = False
        elif character in ";#":
            break
        elif character == "\\":
            escaped = True
        else:
            output += character
    if escaped:
        output += "\\"
    return output.strip()


_LITERALS: dict[str, object] = {"true": True, "false": False, "null": None}


def parse(text: str) -> dict[str, Any]:
    """The sections and properties of ``text``."""
    return _nest_sections(_parse_lines(text))


def _parse_lines(text: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    current = output
    for line in _LINES.split(text):
        if len(line) == 0 or _BLANK_OR_COMMENT.match(line):
            continue
        section_match = _SECTION.fullmatch(line)
        if section_match is not None:
            section = _key(_unquote(section_match.group(1)))
            current = cast("dict[str, Any]", output.setdefault(section, {}))
            continue
        property_match = _PROPERTY.fullmatch(line)
        if property_match is None:
            continue
        raw_key = _key(_unquote(property_match.group(1)))
        is_list = len(raw_key) > 2 and raw_key.endswith("[]")
        key = raw_key[:-2] if is_list else raw_key
        raw_value: object = (
            True if property_match.group(2) is None else _unquote(property_match.group(3))
        )
        value = (
            _LITERALS[raw_value]
            if isinstance(raw_value, str) and raw_value in _LITERALS
            else raw_value
        )
        if is_list:
            if key not in current:
                current[key] = []
            elif not isinstance(current[key], list):
                current[key] = [current[key]]
        existing = current.get(key)
        if isinstance(existing, list):
            cast("list[object]", existing).append(value)
        else:
            current[key] = value
    return output


def _nest_sections(output: dict[str, Any]) -> dict[str, Any]:
    """Moves each dotted section (``[a.b]``) under its parents."""
    remove: list[str] = []
    for section in list(output):
        if not isinstance(output[section], dict):
            continue
        parts = _split_sections(section)
        last = parts.pop()
        key = last.replace("\\.", ".")
        current = output
        for part in parts:
            if not isinstance(current.get(part), dict):
                current[part] = {}
            current = cast("dict[str, Any]", current[part])
        if current is output and key == last:
            continue
        current[key] = output[section]
        remove.append(section)
    for section in remove:
        del output[section]
    return output


__all__ = ["parse"]
