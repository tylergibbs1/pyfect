"""The URL Standard's percent-encode sets, and percent-encoding and
-decoding over UTF-8."""

from __future__ import annotations

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


def encode(text: str, encode_set: frozenset[str], space_as_plus: bool = False) -> str:
    """``text`` with the characters of ``encode_set`` (and every non-ASCII
    one) percent-encoded as UTF-8."""
    if not any(ch in encode_set or ch > "~" for ch in text):
        return text
    out: list[str] = []
    for ch in text:
        if space_as_plus and ch == " ":
            out.append("+")
        elif ch in encode_set or ch > "~":
            out.extend(f"%{b:02X}" for b in ch.encode("utf-8", "surrogatepass"))
        else:
            out.append(ch)
    return "".join(out)


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
