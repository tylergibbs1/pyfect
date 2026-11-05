"""The value encoding of 2026-07-28's HTTP routing headers (``Mcp-Name``,
``Mcp-Param-*``)."""

from __future__ import annotations

import base64
import binascii
import re

_BASE64_PREFIX = "=?base64?"
_BASE64_SUFFIX = "?="
_PLAIN_HEADER = re.compile(r"^[\t\x20-\x7e]*$")


def decode_routing_header(value: str) -> str | None:
    """A routing header's value: plain visible ASCII as is, else UTF-8
    Base64 between ``=?base64?`` and ``?=`` (``None`` when malformed)."""
    if not (value.startswith(_BASE64_PREFIX) and value.endswith(_BASE64_SUFFIX)):
        return value if _PLAIN_HEADER.match(value) else None
    encoded = value[len(_BASE64_PREFIX) : -len(_BASE64_SUFFIX)]
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
