"""Effect's ``String.configCase``: CONSTANT_CASE that keeps digit groups
(``"api-v2 xml"`` is ``"API_V2_XML"``)."""

from __future__ import annotations

import re

_SPLIT = (re.compile(r"([a-z0-9])([A-Z])"), re.compile(r"([A-Z])([A-Z][a-z])"))
_STRIP = re.compile(r"[^A-Za-z0-9]+")


def config_case(text: str) -> str:
    """Upper-case words joined by ``_``. Not idempotent, as in Effect:
    ``"field2value"`` gives ``"FIELD2VALUE"``, which gives ``"FIELD2_VALUE"``."""
    result = text
    for split in _SPLIT:
        result = split.sub("\\1\0\\2", result)
    result = _STRIP.sub("\0", result).strip("\0")
    if not result:
        return ""
    return "_".join(part.upper() for part in result.split("\0"))
