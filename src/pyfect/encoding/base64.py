"""Base64 with the standard alphabet and padding (Effect's
``encoding/Base64``). ``encode`` takes bytes or text (encoded as UTF-8);
``decode`` ignores CR and LF and returns a ``Result``::

    base64.encode("hello")          # "aGVsbG8="
    base64.decode("aGVsbG8=")       # Ok(b"hello")
    base64.decode_string("8J+Riw==")  # Ok("👋")
"""

from __future__ import annotations

from pyfect._binary_codecs import Binary, EncodingError, utf8_text
from pyfect._binary_codecs import base64_decode as decode
from pyfect._binary_codecs import base64_encode as encode
from pyfect.result import Result


def decode_string(text: str) -> Result[str, EncodingError]:
    """``decode``, then the bytes as UTF-8 (bad bytes replaced)."""
    return decode(text).map(utf8_text)


__all__ = ["Binary", "decode", "decode_string", "encode"]
