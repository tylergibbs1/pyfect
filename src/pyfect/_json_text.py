"""JSON as the framers and schema getters read and write it: ``JSON.parse`` and
``JSON.stringify`` semantics on top of the ``json`` module."""

from __future__ import annotations

import json
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
    """``json.loads`` without the ``NaN`` / ``Infinity`` extensions."""
    value: Json = json.loads(text, parse_constant=_reject_constant)
    return value


def stringify(value: object) -> str:
    """Compact JSON, non-ASCII kept as is; ``NaN`` and infinities raise."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
