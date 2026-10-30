"""RFC 9110 field names and values, as every server sends them: a name is
a token, a value is tab, visible ASCII and obs-text (no other control
character)."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_VALUE = re.compile(r"[\t\x20-\x7e\x80-\xff]*")


def is_token(name: str) -> bool:
    return _TOKEN.fullmatch(name) is not None


def is_field_value(value: str) -> bool:
    return _VALUE.fullmatch(value) is not None
