"""Base64, Base64Url and hex as Effect's ``effect/encoding`` modules define
them, below both ``pyfect.encoding`` and the schema getters (which
``pyfect.encoding`` imports). Text input is encoded as UTF-8 first
(``TextEncoder``); decoded text is UTF-8 with bad bytes replaced and a
leading byte-order mark dropped (``TextDecoder``)."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Literal

from pyfect._js import text_encode
from pyfect.errors import TaggedError
from pyfect.result import Err, Ok, Result


@dataclass(eq=False)
class EncodingError(TaggedError):
    """Encoding or decoding failed: ``module`` names the encoding,
    ``input`` is what it was given."""

    kind: Literal["Decode", "Encode"]
    module: str
    input: object
    message: str

    def __str__(self) -> str:
        return self.message


type Binary = bytes | bytearray | memoryview | str


def _bytes(value: Binary) -> bytes:
    return text_encode(value) if isinstance(value, str) else bytes(value)


def utf8_text(data: bytes) -> str:
    """``new TextDecoder().decode(data)``."""
    return data.decode("utf-8-sig", errors="replace")


def _fail(module: str, text: str, message: str) -> Err[EncodingError]:
    return Err(EncodingError(kind="Decode", module=module, input=text, message=message))


def _strip_crlf(text: str) -> str:
    return text.replace("\r", "").replace("\n", "")


# --- Base64 ---------------------------------------------------------------------------


def base64_encode(value: Binary) -> str:
    return base64.b64encode(_bytes(value)).decode("ascii")


_BASE64_CHARS = re.compile(r"[A-Za-z0-9+/=]*")
_BASE64_CHAR = re.compile(r"[A-Za-z0-9+/=]")


def base64_decode(text: str) -> Result[bytes, EncodingError]:
    """CR and LF are ignored; the length must be a multiple of 4 and ``=``
    only ends it."""
    stripped = _strip_crlf(text)
    length = len(stripped)
    if length % 4:
        return _fail("Base64", stripped, f"Length must be a multiple of 4, but is {length}")
    index = stripped.find("=")
    if index != -1 and (index < length - 2 or (index == length - 2 and stripped[-1] != "=")):
        return _fail("Base64", stripped, "Found a '=' character, but it is not at the end")
    if not _BASE64_CHARS.fullmatch(stripped):
        bad = next(c for c in stripped if not _BASE64_CHAR.fullmatch(c))
        return _fail("Base64", stripped, f"Invalid character {bad}")
    return Ok(binascii.a2b_base64(stripped))


# --- Base64Url ------------------------------------------------------------------------

_TO_URL = str.maketrans("+/", "-_")
_TO_STANDARD = str.maketrans("-_", "+/")
_BASE64_URL = re.compile(r"[-_A-Za-z0-9]*?={0,2}")


def base64_url_encode(value: Binary) -> str:
    return base64_encode(value).replace("=", "").translate(_TO_URL)


def base64_url_encode_padded(value: Binary) -> str:
    return base64_encode(value).translate(_TO_URL)


def base64_url_decode(text: str) -> Result[bytes, EncodingError]:
    """CR and LF are ignored; the URL alphabet, unpadded or fully padded.
    Non-zero trailing bits in the last character are ignored."""
    stripped = _strip_crlf(text)
    length = len(stripped)
    padded = stripped.endswith("=")
    if padded and length % 4:
        return _fail(
            "Base64Url", stripped, f"Padded length should be a multiple of 4, but is {length}"
        )
    if not padded and length % 4 == 1:
        return _fail(
            "Base64Url",
            stripped,
            f"Unpadded length should not be 1 more than a multiple of 4, but is {length}",
        )
    if not _BASE64_URL.fullmatch(stripped):
        return _fail("Base64Url", stripped, "Invalid input")
    data = stripped.rstrip("=")
    return Ok(binascii.a2b_base64(data.translate(_TO_STANDARD) + "=" * (-len(data) % 4)))


# --- Hex ------------------------------------------------------------------------------

_HEX = re.compile(rb"(?:[0-9a-fA-F]{2})*")


def hex_encode(value: Binary) -> str:
    return _bytes(value).hex()


def hex_decode(text: str) -> Result[bytes, EncodingError]:
    """Two hex digits, either case, per byte."""
    data = text_encode(text)
    if len(data) % 2:
        return _fail("Hex", text, f"Length must be a multiple of 2, but is {len(data)}")
    if not _HEX.fullmatch(data):
        return _fail("Hex", text, "Invalid input")
    return Ok(bytes.fromhex(data.decode("ascii")))
