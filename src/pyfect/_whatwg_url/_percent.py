"""The URL Standard's percent-encode sets, and percent-encoding and
-decoding over UTF-8."""

from __future__ import annotations

import re
from functools import cache

from pyfect._js import text_encode

_HEX = frozenset("0123456789abcdefABCDEF")

C0_CONTROL = frozenset(chr(i) for i in range(0x20))
"""Characters past ``~`` are always encoded, so no set lists them."""
FRAGMENT = C0_CONTROL | frozenset(' "<>`')
QUERY = C0_CONTROL | frozenset(' "#<>')
SPECIAL_QUERY = QUERY | frozenset("'")
PATH = QUERY | frozenset("?^`{}")
USERINFO = PATH | frozenset("/:;=@[\\]|")
COMPONENT = USERINFO | frozenset("$%&+,")
FORM = COMPONENT | frozenset("!'()~")


_PAST_TILDE = re.compile("[\x7f-\U0010ffff]+")


@cache
def _ascii_table(encode_set: frozenset[str], space_as_plus: bool) -> dict[int, str]:
    """What each ASCII character of ``encode_set`` becomes, for ``str.translate``."""
    table = {ord(ch): f"%{ord(ch):02X}" for ch in encode_set}
    if space_as_plus:
        table[ord(" ")] = "+"
    return table


def _escape_run(match: re.Match[str]) -> str:
    return "%" + text_encode(match[0]).hex("%").upper()


def encode(text: str, encode_set: frozenset[str], space_as_plus: bool = False) -> str:
    """``text`` with the characters of ``encode_set`` (and every non-ASCII
    one) percent-encoded as UTF-8 (a lone surrogate as U+FFFD, as the URL
    Standard's UTF-8 encode writes it)."""
    # The ASCII characters first, which leaves only ASCII behind them, then
    # each run of characters past ``~``: two passes in C, not one per character.
    return _PAST_TILDE.sub(_escape_run, text.translate(_ascii_table(encode_set, space_as_plus)))


def decode(text: str) -> bytes:
    """``text`` as UTF-8 with its ``%XX`` escapes decoded; any other ``%``
    stays as written."""
    raw = text.encode("utf-8", "surrogatepass")
    if b"%" not in raw:
        return raw
    out = bytearray()
    i = 0
    while i < len(raw):
        byte = raw[i]
        hex_digits = raw[i + 1 : i + 3].decode("latin-1")
        if byte == 0x25 and len(hex_digits) == 2 and set(hex_digits) <= _HEX:
            out.append(int(hex_digits, 16))
            i += 3
        else:
            out.append(byte)
            i += 1
    return bytes(out)


def is_hex(ch: str) -> bool:
    return ch in _HEX
