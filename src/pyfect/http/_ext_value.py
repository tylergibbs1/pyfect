"""RFC 8187 extended parameter values (``title*=UTF-8''Gr%C3%BC%C3%9Fe``), shared by
``Content-Disposition`` and ``Link`` parsing."""

from __future__ import annotations

import re
from urllib.parse import unquote_to_bytes

_EXT_VALUE = re.compile(
    r"^(utf-8|iso-8859-1)'[a-z0-9-]*+'((?:%[0-9a-f]{2}|[!#$&+.^_`|~\w-]++)*+)$",
    re.IGNORECASE | re.ASCII,
)
_PCT_ENCODED = re.compile(r"%([0-9a-f]{2})", re.IGNORECASE)


def decode_ext_value(value: str) -> str | None:
    """The text of an extended value; ``None`` when it is malformed or not valid UTF-8.
    ISO-8859-1 is decoded byte by byte."""
    match = _EXT_VALUE.match(value)
    if match is None:
        return None
    if match[1].lower() == "iso-8859-1":
        return _PCT_ENCODED.sub(lambda m: chr(int(m[1], 16)), match[2])
    try:
        return unquote_to_bytes(match[2]).decode("utf-8")
    except UnicodeDecodeError:
        return None
