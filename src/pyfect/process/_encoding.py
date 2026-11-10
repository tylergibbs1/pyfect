"""Text to bytes as Node's ``Buffer.from(text, encoding)`` makes them, for
text written to a child's standard input."""

from __future__ import annotations

import base64
import re

from pyfect._js import text_encode
from pyfect.process._command import Encoding

_BASE64_CHARS = re.compile(r"[^A-Za-z0-9+/\-_]")
_HEX_PAIR = re.compile(r"[0-9A-Fa-f]{2}")


def encode(text: str, encoding: Encoding) -> bytes:
    """``text`` as bytes: UTF-8 with lone surrogates as U+FFFD; the low byte
    of each UTF-16 code unit for ``latin1`` / ``binary`` / ``ascii``; UTF-16LE
    code units; base64 of either alphabet, ignoring other characters and
    stopping at ``=``; hex pairs up to the first that is not one."""
    match encoding:
        case "utf8" | "utf-8":
            return text_encode(text)
        case "latin1" | "binary" | "ascii":
            return text.encode("utf-16-le", "surrogatepass")[0::2]
        case "utf16le" | "utf-16le" | "ucs2" | "ucs-2":
            return text.encode("utf-16-le", "surrogatepass")
        case "base64" | "base64url":
            return _base64(text)
        case "hex":
            return _hex(text)


def _base64(text: str) -> bytes:
    body = _BASE64_CHARS.sub("", text.split("=", 1)[0]).replace("-", "+").replace("_", "/")
    body = body[: len(body) - 1] if len(body) % 4 == 1 else body
    # Every character left is in the alphabet, so nothing is skipped.
    return base64.b64decode(body + "=" * (-len(body) % 4), validate=True)


def _hex(text: str) -> bytes:
    out = bytearray()
    for i in range(0, len(text) - 1, 2):
        if not _HEX_PAIR.fullmatch(text, i, i + 2):
            break
        out.append(int(text[i : i + 2], 16))
    return bytes(out)
