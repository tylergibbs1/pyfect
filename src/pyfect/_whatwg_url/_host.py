"""The URL Standard's host parser: domains (through IDNA), IPv4 and IPv6
addresses and opaque hosts, each given back serialized."""

from __future__ import annotations

from pyfect._whatwg_url import _idna, _percent

_FORBIDDEN_HOST = frozenset("\x00\t\n\r #/:<>?@[\\]^|")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | _percent.C0_CONTROL | frozenset("%\x7f")
_RADIX_DIGITS = {
    8: frozenset("01234567"),
    10: frozenset("0123456789"),
    16: frozenset("0123456789abcdefABCDEF"),
}
_TOO_BIG = 1 << 40  # past every IPv4 part limit


def parse(text: str, opaque: bool) -> str | None:  # noqa: PLR0911
    """``text`` as a host, serialized; ``None`` on failure. ``opaque`` is
    for the hosts of non-special URLs."""
    if text.startswith("["):
        if not text.endswith("]"):
            return None
        address = _ipv6(text[1:-1])
        return None if address is None else f"[{_ipv6_serialize(address)}]"
    if opaque:
        if any(ch in _FORBIDDEN_HOST for ch in text):
            return None
        return _percent.encode(text, _percent.C0_CONTROL)
    domain = _percent.decode(text).decode("utf-8", "replace")
    ascii_domain = _domain_to_ascii(domain)
    if ascii_domain is None or any(ch in _FORBIDDEN_DOMAIN for ch in ascii_domain):
        return None
    if _ends_in_number(ascii_domain):
        address = _ipv4(ascii_domain)
        return None if address is None else _ipv4_serialize(address)
    return ascii_domain


def _domain_to_ascii(domain: str) -> str | None:
    """An ASCII domain is only lowercased; any other goes through IDNA."""
    result = domain.lower() if domain.isascii() else _idna.to_ascii(domain)
    return result or None


def _ipv4_number(part: str) -> int | None:
    digits, radix = part, 10
    if part[:2] in ("0x", "0X"):
        digits, radix = part[2:], 16
    elif len(part) > 1 and part[0] == "0":
        digits, radix = part[1:], 8
    if digits == "":
        return 0
    if any(ch not in _RADIX_DIGITS[radix] for ch in digits):
        return None
    digits = digits.lstrip("0") or "0"
    return _TOO_BIG if len(digits) > 12 else int(digits, radix)


def _ends_in_number(domain: str) -> bool:
    parts = domain.split(".")
    if parts[-1] == "":
        if len(parts) == 1:
            return False
        parts.pop()
    last = parts[-1]
    if last != "" and all(ch in _RADIX_DIGITS[10] for ch in last):
        return True
    return last != "" and _ipv4_number(last) is not None


def _ipv4(domain: str) -> int | None:
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    if len(parts) > 4:
        return None
    numbers: list[int] = []
    for part in parts:
        number = _ipv4_number(part) if part else None
        if number is None:
            return None
        numbers.append(number)
    *head, last = numbers
    if any(n > 255 for n in head) or last >= 256 ** (5 - len(numbers)):
        return None
    return last + sum(n * 256 ** (3 - i) for i, n in enumerate(head))


def _ipv4_serialize(address: int) -> str:
    return ".".join(str((address >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _ipv4_in_ipv6(text: str, i: int, address: list[int], piece: int) -> int | None:
    """The dotted IPv4 tail of an IPv6 address from ``text[i:]`` into
    ``address`` from ``piece``; the next piece, ``None`` on failure."""
    if piece > 6:
        return None
    seen = 0
    while i < len(text):
        if seen > 0:
            if text[i] != "." or seen == 4:
                return None
            i += 1
        start = i
        while i < len(text) and text[i] in _RADIX_DIGITS[10]:
            i += 1
        digits = text[start:i]
        if not 0 < len(digits) <= 3 or (len(digits) > 1 and digits[0] == "0"):
            return None
        if int(digits) > 255:
            return None
        address[piece] = address[piece] * 0x100 + int(digits)
        seen += 1
        if seen in (2, 4):
            piece += 1
    return piece if seen == 4 else None


def _ipv6(text: str) -> list[int] | None:  # noqa: PLR0911, PLR0912
    address = [0] * 8
    piece, compress, i = 0, None, 0
    end = len(text)
    if text.startswith(":"):
        if not text.startswith("::"):
            return None
        i, piece = 2, 1
        compress = piece
    while i < end:
        if piece == 8:
            return None
        if text[i] == ":":
            if compress is not None:
                return None
            i += 1
            piece += 1
            compress = piece
            continue
        value = length = 0
        while length < 4 and i < end and _percent.is_hex(text[i]):
            value = value * 16 + int(text[i], 16)
            i += 1
            length += 1
        if i < end and text[i] == ".":
            if length == 0:
                return None
            tail = _ipv4_in_ipv6(text, i - length, address, piece)
            if tail is None:
                return None
            piece = tail
            break
        if i < end and text[i] == ":":
            i += 1
            if i >= end:
                return None
        elif i < end:
            return None
        address[piece] = value
        piece += 1
    if compress is not None:
        swaps = piece - compress
        piece = 7
        while piece != 0 and swaps > 0:
            other = compress + swaps - 1
            address[piece], address[other] = address[other], address[piece]
            piece -= 1
            swaps -= 1
    elif piece != 8:
        return None
    return address


def _ipv6_serialize(address: list[int]) -> str:
    """Lowercase hex pieces, the first longest run of two or more zero
    pieces written ``::``."""
    compress, best, i = None, 1, 0
    while i < 8:
        run = 0
        while i + run < 8 and address[i + run] == 0:
            run += 1
        if run > best:
            compress, best = i, run
        i += run or 1
    out = ""
    ignore_zero = False
    for index, piece in enumerate(address):
        if ignore_zero and piece == 0:
            continue
        ignore_zero = False
        if compress == index:
            out += "::" if index == 0 else ":"
            ignore_zero = True
            continue
        out += f"{piece:x}"
        if index != 7:
            out += ":"
    return out
