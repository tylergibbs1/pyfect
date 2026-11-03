"""Hexadecimal text (Effect's ``encoding/Hex``): ``encode`` writes lowercase,
``decode`` reads either case and returns a ``Result``, ``random`` makes
random lowercase hex (not cryptographically secure: use ``Crypto`` for
secrets)."""

from __future__ import annotations

import random as random_

from pyfect._binary_codecs import EncodingError, utf8_text
from pyfect._binary_codecs import hex_decode as decode
from pyfect._binary_codecs import hex_encode as encode
from pyfect.result import Result


def decode_string(text: str) -> Result[str, EncodingError]:
    """``decode``, then the bytes as UTF-8 (bad bytes replaced)."""
    return decode(text).map(utf8_text)


def random(length: int) -> str:
    """``length`` random hex digits, rounded down to a multiple of 8;
    ``length`` is taken modulo ``2**32`` as Effect's ``length >>> 3``."""
    words = (length % 2**32) >> 3
    return "".join(f"{random_.getrandbits(32):08x}" for _ in range(words))


__all__ = ["decode", "decode_string", "encode", "random"]
