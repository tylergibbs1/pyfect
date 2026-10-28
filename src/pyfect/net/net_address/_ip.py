"""IP addresses: strict parsing, canonical formatting and classification.

An address is the standard library's ``ipaddress.IPv4Address`` or
``IPv6Address``; the parsers here are Effect's, stricter than
``ipaddress`` (no zone identifiers, no brackets) and failing with a
``NetAddressError`` that names the rejected part. Classification follows
Effect's bit tests, which differ from ``ipaddress``'s properties in places
(``::ffff:127.0.0.1`` is not a loopback address here).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from ipaddress import IPv4Address, IPv6Address
from typing import Literal, NewType, overload

from pyfect.net._errors import NetAddressError, address_error
from pyfect.result import Err, Ok, Result

type IpAddress = IPv4Address | IPv6Address
type IpFamily = Literal["IPv4", "IPv6"]
type Ipv4Octets = tuple[int, int, int, int]
type Ipv6Segments = tuple[int, int, int, int, int, int, int, int]
type Bytes = bytes | bytearray | memoryview
type Ipv4AddressInput = IPv4Address | str | Ipv4Octets | Bytes
type Ipv6AddressInput = IPv6Address | str | Ipv6Segments | Bytes
type IpAddressInput = Ipv4AddressInput | Ipv6AddressInput

ScopedIpv6Literal = NewType("ScopedIpv6Literal", str)
"""An IPv6 address with a zone, ``fe80::1%eth0``: canonical address text, a
numeric zone without leading zeros."""

type ScopedIpv6LiteralInput = ScopedIpv6Literal | str

ipv4_loopback = IPv4Address("127.0.0.1")
ipv6_loopback = IPv6Address("::1")
loopback_addresses: tuple[IPv4Address, IPv6Address] = (ipv4_loopback, ipv6_loopback)
ipv4_unspecified = IPv4Address(0)
ipv6_unspecified = IPv6Address(0)
ipv4_broadcast = IPv4Address(0xFFFFFFFF)

_DECIMAL_OCTET = re.compile(r"[0-9]{1,3}")
_HEX_SEGMENT = re.compile(r"[0-9a-fA-F]{1,4}")
_DIGITS = re.compile(r"[0-9]+")
_ZONE_FORBIDDEN = re.compile(r"[%\[\]/\s\x00-\x1f\x7f-\x9f]")


def width(address: IpAddress) -> Literal[32, 128]:
    """The address's bit width."""
    return 32 if isinstance(address, IPv4Address) else 128


def family_of(address: IpAddress) -> IpFamily:
    return "IPv4" if isinstance(address, IPv4Address) else "IPv6"


def all_in_range(values: Sequence[object], top: int) -> bool:
    return all(isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= top for n in values)


def ipv4_from_octets(octets: Ipv4Octets) -> Result[IPv4Address, NetAddressError]:
    if len(octets) != 4 or not all_in_range(octets, 255):
        return address_error(octets, "octets must be integers from 0 through 255")
    return Ok(IPv4Address(bytes(octets)))


def ipv6_from_segments(segments: Ipv6Segments) -> Result[IPv6Address, NetAddressError]:
    if len(segments) != 8 or not all_in_range(segments, 0xFFFF):
        return address_error(segments, "segments must be integers from 0 through 65535")
    value = 0
    for segment in segments:
        value = (value << 16) | segment
    return Ok(IPv6Address(value))


def ipv4_from_bytes_unsafe(data: Bytes) -> IPv4Address:
    """The address of 4 bytes (copied)."""
    return IPv4Address(bytes(data[:4]))


def ipv6_from_bytes_unsafe(data: Bytes) -> IPv6Address:
    """The address of 16 bytes (copied)."""
    return IPv6Address(bytes(data[:16]))


def ipv4_from_string(text: str) -> Result[IPv4Address, NetAddressError]:
    """Strict dotted decimal: four octets, no leading zeros."""
    parts = text.split(".")
    if len(parts) != 4 or not all(_DECIMAL_OCTET.fullmatch(p) for p in parts):
        return address_error(text, "expected exactly four decimal octets")
    if any(len(p) > 1 and p[0] == "0" for p in parts):
        return address_error(text, "leading zeroes are not allowed")
    octets = [int(p) for p in parts]
    if any(o > 255 for o in octets):
        return address_error(text, "octets must be at most 255")
    return Ok(IPv4Address(bytes(octets)))


def _parse_ipv6_segments(text: str) -> Result[list[int], NetAddressError]:  # noqa: PLR0911
    if "[" in text or "]" in text or "%" in text:
        return address_error(
            text, "brackets and zone identifiers are not valid in a bare IPv6 address"
        )
    halves = text.split("::")
    if len(halves) > 2:
        return address_error(text, "only one compression marker is allowed")
    compressed = len(halves) == 2
    head = [] if halves[0] == "" else halves[0].split(":")
    tail = halves[1].split(":") if compressed and halves[1] != "" else []
    if "" in head or "" in tail:
        return address_error(text, "empty segments are only valid in the compression marker")
    trailing = tail[-1] if tail else head[-1] if head else ""
    embedded: list[int] = []
    if "." in trailing:
        if compressed and not tail:
            return address_error(text, "embedded IPv4 syntax must be trailing")
        match ipv4_from_string(trailing):
            case Err() as error:
                return error
            case Ok(address):
                value = int(address)
                embedded = [value >> 16, value & 0xFFFF]
        (tail if tail else head).pop()
    explicit = len(head) + len(tail) + len(embedded)
    if explicit >= 8 if compressed else explicit != 8:
        return address_error(
            text,
            "compression must replace at least one segment"
            if compressed
            else "expected eight segments",
        )
    if not all(_HEX_SEGMENT.fullmatch(p) for p in (*head, *tail)):
        return address_error(text, "segments must contain one through four hexadecimal digits")
    return Ok(
        [
            *(int(p, 16) for p in head),
            *([0] * (8 - explicit)),
            *(int(p, 16) for p in tail),
            *embedded,
        ]
    )


def ipv6_from_string(text: str) -> Result[IPv6Address, NetAddressError]:
    """IPv6 text, compressed or not, with an optional trailing embedded
    IPv4 address; no brackets or zone."""

    def to_address(segments: list[int]) -> IPv6Address:
        return IPv6Address(sum(s << (16 * (7 - i)) for i, s in enumerate(segments)))

    return _parse_ipv6_segments(text).map(to_address)


def ip_from_string(text: str) -> Result[IpAddress, NetAddressError]:
    """IPv6 when the text holds a colon, else IPv4."""
    parsed: Result[IpAddress, NetAddressError] = (
        ipv6_from_string(text) if ":" in text else ipv4_from_string(text)
    )
    return parsed


def ip_from_string_unsafe(text: str) -> IpAddress:
    return ip_from_string(text).get_or_raise()


def _octets_or_segments(value: Sequence[int]) -> Result[IpAddress, NetAddressError] | None:
    if len(value) == 4:
        return ipv4_from_octets((value[0], value[1], value[2], value[3]))
    if len(value) == 8:
        return ipv6_from_segments(
            (value[0], value[1], value[2], value[3], value[4], value[5], value[6], value[7])
        )
    return None


def ip_from_input(value: IpAddressInput) -> Result[IpAddress, NetAddressError]:
    """An address, its text, 4 octets, 8 segments, or 4 or 16 bytes."""
    if isinstance(value, IPv4Address | IPv6Address):
        return Ok(value)
    if isinstance(value, str):
        return ip_from_string(value)
    if isinstance(value, bytes | bytearray | memoryview):
        if len(value) == 4:
            return Ok(ipv4_from_bytes_unsafe(value))
        if len(value) == 16:
            return Ok(ipv6_from_bytes_unsafe(value))
    else:
        parsed = _octets_or_segments(value)
        if parsed is not None:
            return parsed
    return address_error(
        value, "expected an IP address, string, 4 octets, 8 segments, or 4 or 16 bytes"
    )


def ip_from_input_unsafe(value: IpAddressInput) -> IpAddress:
    return ip_from_input(value).get_or_raise()


def ipv4_from_input(value: Ipv4AddressInput) -> Result[IPv4Address, NetAddressError]:
    if isinstance(value, IPv4Address):
        return Ok(value)
    if isinstance(value, str):
        return ipv4_from_string(value)
    if len(value) == 4:
        if isinstance(value, bytes | bytearray | memoryview):
            return Ok(ipv4_from_bytes_unsafe(value))
        return ipv4_from_octets(value)
    return address_error(value, "expected an IPv4 address, string, 4 octets, or 4 bytes")


def ipv6_from_input(value: Ipv6AddressInput) -> Result[IPv6Address, NetAddressError]:
    if isinstance(value, IPv6Address):
        return Ok(value)
    if isinstance(value, str):
        return ipv6_from_string(value)
    if isinstance(value, bytes | bytearray | memoryview):
        if len(value) == 16:
            return Ok(ipv6_from_bytes_unsafe(value))
    elif len(value) == 8:
        return ipv6_from_segments(value)
    return address_error(value, "expected an IPv6 address, string, 8 segments, or 16 bytes")


def scoped_ipv6_literal_from_string(text: str) -> Result[ScopedIpv6Literal, NetAddressError]:
    """``address%zone``, normalized: canonical address text, a numeric zone
    without leading zeros."""
    address, separator, zone = text.partition("%")
    if not separator:
        return address_error(text, "expected an IPv6 zone")
    if not zone or _ZONE_FORBIDDEN.search(zone):
        return address_error(text, "invalid IPv6 scope identifier")
    if _DIGITS.fullmatch(zone):
        if int(zone) > 0xFFFFFFFF:
            return address_error(text, "scope identifier must be an unsigned 32-bit integer")
        zone = str(int(zone))
    return ipv6_from_string(address).map(lambda ip: ScopedIpv6Literal(f"{format_ip(ip)}%{zone}"))


def scoped_ipv6_literal_from_input(
    value: ScopedIpv6LiteralInput,
) -> Result[ScopedIpv6Literal, NetAddressError]:
    return scoped_ipv6_literal_from_string(value)


def is_scoped_ipv6_literal(value: object) -> bool:
    """Whether ``value`` is already a normalized scoped IPv6 literal."""
    if not isinstance(value, str) or "%" not in value:
        return False
    return scoped_ipv6_literal_from_string(value) == Ok(value)


def ipv4_to_octets(address: IPv4Address) -> Ipv4Octets:
    a, b, c, d = address.packed
    return (a, b, c, d)


def ipv6_to_segments(address: IPv6Address) -> Ipv6Segments:
    value = int(address)
    s = [(value >> (16 * (7 - i))) & 0xFFFF for i in range(8)]
    return (s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7])


def ipv6_to_octets(address: IPv6Address) -> tuple[int, ...]:
    return tuple(address.packed)


def is_ipv4_mapped(address: IPv6Address) -> bool:
    return int(address) >> 32 == 0xFFFF


def format_ip(address: IpAddress) -> str:
    """Canonical text: dotted decimal, or RFC 5952 IPv6 (the first longest
    run of two or more zero segments compressed; IPv4-mapped addresses
    dotted)."""
    if isinstance(address, IPv4Address):
        return ".".join(str(o) for o in address.packed)
    segments = ipv6_to_segments(address)
    if is_ipv4_mapped(address):
        return "::ffff:" + ".".join(str(o) for o in address.packed[12:])
    best_start, best_length, start = -1, 0, -1
    for index in range(9):
        if index < 8 and segments[index] == 0:
            if start == -1:
                start = index
        elif start != -1:
            if index - start > best_length:
                best_start, best_length = start, index - start
            start = -1
    if best_length < 2:
        return ":".join(f"{s:x}" for s in segments)
    head = ":".join(f"{s:x}" for s in segments[:best_start])
    tail = ":".join(f"{s:x}" for s in segments[best_start + best_length :])
    return f"{head}::{tail}"


def format_url_host(address: IpAddress) -> str:
    """The address as a URL host: IPv6 in brackets."""
    return format_ip(address) if isinstance(address, IPv4Address) else f"[{format_ip(address)}]"


def is_unspecified(address: IpAddress) -> bool:
    return int(address) == 0


def is_loopback(address: IpAddress) -> bool:
    if isinstance(address, IPv4Address):
        return int(address) >> 24 == 127
    return int(address) == 1


def is_link_local(address: IpAddress) -> bool:
    if isinstance(address, IPv4Address):
        return int(address) >> 16 == 0xA9FE
    return (int(address) >> 112) & 0xFFC0 == 0xFE80


def is_private(address: IPv4Address) -> bool:
    """RFC 1918: 10/8, 172.16/12, 192.168/16."""
    value = int(address)
    return value >> 24 == 10 or (value >> 16) & 0xFFF0 == 0xAC10 or value >> 16 == 0xC0A8


def is_unique_local(address: IPv6Address) -> bool:
    """fc00::/7."""
    return (int(address) >> 120) & 0xFE == 0xFC


def to_ipv4_mapped(address: IPv4Address) -> IPv6Address:
    return IPv6Address((0xFFFF << 32) | int(address))


def from_ipv4_mapped(address: IPv6Address) -> IPv4Address | None:
    """The IPv4 address an IPv4-mapped address holds, or ``None``."""
    return IPv4Address(int(address) & 0xFFFFFFFF) if is_ipv4_mapped(address) else None


@overload
def canonical_ip(address: IPv4Address) -> IPv4Address: ...
@overload
def canonical_ip(address: IPv6Address) -> IpAddress: ...
def canonical_ip(address: IpAddress) -> IpAddress:
    if isinstance(address, IPv6Address):
        mapped = from_ipv4_mapped(address)
        return address if mapped is None else mapped
    return address
