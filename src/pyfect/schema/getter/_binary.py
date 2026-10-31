"""Base64, Base64Url and hex getters (Effect's ``encodeBase64``,
``decodeBase64``, ...). Bytes are ``bytes``; a ``str`` input is encoded as
UTF-8 first, and decoded text is UTF-8 with invalid sequences replaced (as
JavaScript's ``TextDecoder``)."""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Callable

from pyfect._js import text_encode
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter._getter import Getter, Transform, TransformEffect
from pyfect.schema.issue import InvalidValue, Issue, reported


def _bytes(value: bytes | str) -> bytes:
    return text_encode(value) if isinstance(value, str) else value


def base64_decode(text: str) -> bytes | None:
    """Effect's ``Base64.decode``: CR / LF ignored, padded, standard alphabet."""
    stripped = text.replace("\r", "").replace("\n", "")
    if len(stripped) % 4:
        return None
    try:
        return base64.b64decode(stripped, validate=True)
    except binascii.Error:
        return None


_BASE64_URL = re.compile(r"[A-Za-z0-9_-]*={0,2}")
_URL_TO_STANDARD = str.maketrans("-_", "+/")


def base64_url_decode(text: str) -> bytes | None:
    """Effect's ``Base64Url.decode``: CR / LF ignored, the URL alphabet, a
    length (padding included) padded up to a multiple of 4."""
    stripped = text.replace("\r", "").replace("\n", "")
    if len(stripped) % 4 == 1 or not _BASE64_URL.fullmatch(stripped):
        return None
    padded = stripped + "=" * (len(stripped) % 4 and 4 - len(stripped) % 4)
    return base64_decode(padded.translate(_URL_TO_STANDARD))


_HEX = re.compile(r"(?:[0-9a-fA-F]{2})*")


def hex_decode(text: str) -> bytes | None:
    return bytes.fromhex(text) if _HEX.fullmatch(text) else None


def base64_encode(value: bytes | str) -> str:
    return base64.b64encode(_bytes(value)).decode("ascii")


def base64_url_encode(value: bytes | str, *, padding: bool = False) -> str:
    out = base64.urlsafe_b64encode(_bytes(value)).decode("ascii")
    return out if padding else out.rstrip("=")


def hex_encode(value: bytes | str) -> str:
    return _bytes(value).hex()


def encode_base64() -> Getter[str, bytes | str]:
    return Transform(base64_encode)


def encode_base64_url(*, padding: bool = False) -> Getter[str, bytes | str]:
    """Unpadded unless ``padding``."""
    return Transform(lambda value: base64_url_encode(value, padding=padding))


def encode_hex() -> Getter[str, bytes | str]:
    return Transform(hex_encode)


def _decoder[T](
    decode: Callable[[str], bytes | None], expected: str, then: Callable[[bytes], T]
) -> Getter[T, str]:
    def run(text: str, options: ParseOptions) -> Exit[T, Issue]:
        out = decode(text)
        if out is None:
            return fail_exit(InvalidValue({"expected": expected}, reported(text, options)))
        return Success(then(out))

    return TransformEffect(run)


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _same(data: bytes) -> bytes:
    return data


def decode_base64() -> Getter[bytes, str]:
    return _decoder(base64_decode, "a valid Base64 string", _same)


def decode_base64_string() -> Getter[str, str]:
    return _decoder(base64_decode, "a valid Base64 string", _text)


def decode_base64_url() -> Getter[bytes, str]:
    return _decoder(base64_url_decode, "a valid Base64Url string", _same)


def decode_base64_url_string() -> Getter[str, str]:
    return _decoder(base64_url_decode, "a valid Base64Url string", _text)


def decode_hex() -> Getter[bytes, str]:
    return _decoder(hex_decode, "a valid hexadecimal string", _same)


def decode_hex_string() -> Getter[str, str]:
    return _decoder(hex_decode, "a valid hexadecimal string", _text)
