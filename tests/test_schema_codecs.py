"""Codec edge cases beyond Effect's tests, each value printed by Effect
4.0.6 under Node first."""

from __future__ import annotations

import pytest

from pyfect import schema as S
from pyfect.exit import Failure, Success


@pytest.mark.parametrize(
    ("text", "decoded"),
    [
        ("Zm9v", "foo"),
        ("Zm8", "fo"),
        ("Zg=", "f"),
        ("Zm9v\n", "foo"),
        ("Zm9v\r\nZm9v", "foofoo"),
        ("-_8", "��"),
        ("Zm9v=", None),
        ("Zm8==", None),
        ("Zm9v==", None),
        ("=", None),
        ("==", None),
        ("A", None),
        ("Zm 9v", None),
    ],
)
def test_base64_url_decoding_follows_effect(text: str, decoded: str | None):
    """``Base64Url.decode``: CR / LF dropped, a length (padding included)
    of 1 mod 4 rejected, then padded to a multiple of 4."""
    exit = S.decode_unknown_exit(S.StringFromBase64Url)(text)
    if decoded is None:
        assert isinstance(exit, Failure)
    else:
        assert exit == Success(decoded)
