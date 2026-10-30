"""JSON as the framers and schema getters read and write it: ``JSON.parse`` and
``JSON.stringify`` semantics on top of the ``json`` module."""

from __future__ import annotations

import json
import re
from typing import Never

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None
"""A parsed JSON value."""

PARSE_ERRORS = (ValueError, RecursionError)
"""What ``parse`` raises for text that is not JSON (``JSONDecodeError`` is a
``ValueError``)."""

STRINGIFY_ERRORS = (TypeError, ValueError, RecursionError)
"""What ``stringify`` raises for a value with no JSON form."""


def _reject_constant(name: str) -> Never:
    raise ValueError(f"{name} is not valid JSON")


def parse(text: str) -> Json:
    """``json.loads`` without the ``NaN`` / ``Infinity`` extensions. Text
    that is not JSON raises ``ValueError``, also when it nests too deeply
    to decode (where ``json.loads`` raises ``RecursionError``)."""
    try:
        value: Json = json.loads(text, parse_constant=_reject_constant)
    except RecursionError as cause:
        raise ValueError("JSON is nested too deeply") from cause
    return value


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _escape_surrogate(match: re.Match[str]) -> str:
    return f"\\u{ord(match.group()):04x}"


def stringify(value: object) -> str:
    """Compact JSON, non-ASCII kept as is but lone surrogates escaped
    (``"\\ud83d"``, as ``JSON.stringify`` writes them, so the text encodes to
    UTF-8); ``NaN`` and infinities raise."""
    text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return _LONE_SURROGATE.sub(_escape_surrogate, text)
