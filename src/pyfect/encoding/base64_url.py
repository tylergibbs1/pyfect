"""Base64 with the URL-safe alphabet (Effect's ``encoding/Base64Url``):
``encode`` leaves the padding out, ``encode_padded`` keeps it, ``decode``
takes either and returns a ``Result``."""

from __future__ import annotations

from pyfect._binary_codecs import EncodingError, utf8_text
from pyfect._binary_codecs import base64_url_decode as decode
from pyfect._binary_codecs import base64_url_encode as encode
from pyfect._binary_codecs import base64_url_encode_padded as encode_padded
from pyfect.result import Result


def decode_string(text: str) -> Result[str, EncodingError]:
    """``decode``, then the bytes as UTF-8 (bad bytes replaced)."""
    return decode(text).map(utf8_text)


__all__ = ["decode", "decode_string", "encode", "encode_padded"]
