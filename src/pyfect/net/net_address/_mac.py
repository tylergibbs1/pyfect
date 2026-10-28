"""MAC addresses, and the classifications shared with IP addresses."""

from __future__ import annotations

import re
from dataclasses import dataclass
from ipaddress import IPv4Address

from pyfect.net._errors import NetAddressError, address_error
from pyfect.net.net_address._ip import IpAddress, all_in_range, is_unspecified
from pyfect.result import Ok, Result

type MacAddressOctets = tuple[int, int, int, int, int, int]
type MacAddressInput = MacAddress | str | MacAddressOctets

_MAC = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


@dataclass(frozen=True, slots=True)
class MacAddress:
    """Six octets; ``str`` gives the canonical lowercase, colon-separated
    form. Build one with ``mac_address_from_string`` / ``_from_octets``."""

    packed: bytes

    def __post_init__(self) -> None:
        if len(self.packed) != 6:
            raise NetAddressError("a MAC address has six octets", self.packed)

    def __str__(self) -> str:
        return format_mac_address(self)

    def __repr__(self) -> str:
        return f"MacAddress({format_mac_address(self)!r})"


def mac_address_from_octets(octets: MacAddressOctets) -> Result[MacAddress, NetAddressError]:
    if len(octets) != 6 or not all_in_range(octets, 255):
        return address_error(octets, "octets must be integers from 0 through 255")
    return Ok(MacAddress(bytes(octets)))


def mac_address_from_string(text: str) -> Result[MacAddress, NetAddressError]:
    """Six two-digit hexadecimal octets separated by colons, any case."""
    if not _MAC.fullmatch(text):
        return address_error(text, "expected six two-digit hexadecimal octets separated by colons")
    return Ok(MacAddress(bytes(int(part, 16) for part in text.split(":"))))


def mac_address_from_string_unsafe(text: str) -> MacAddress:
    return mac_address_from_string(text).get_or_raise()


def mac_address_from_input(value: MacAddressInput) -> Result[MacAddress, NetAddressError]:
    if isinstance(value, MacAddress):
        return Ok(value)
    if isinstance(value, str):
        return mac_address_from_string(value)
    return mac_address_from_octets(value)


def mac_address_from_input_unsafe(value: MacAddressInput) -> MacAddress:
    return mac_address_from_input(value).get_or_raise()


def mac_address_to_octets(address: MacAddress) -> MacAddressOctets:
    a, b, c, d, e, f = address.packed
    return (a, b, c, d, e, f)


def format_mac_address(address: MacAddress) -> str:
    return ":".join(f"{byte:02x}" for byte in address.packed)


def is_mac_broadcast(address: MacAddress) -> bool:
    return address.packed == b"\xff" * 6


def is_mac_multicast(address: MacAddress) -> bool:
    """The group bit (the low bit of the first octet) is set."""
    return address.packed[0] & 1 != 0


def is_mac_unicast(address: MacAddress) -> bool:
    return address.packed[0] & 1 == 0


def is_mac_locally_administered(address: MacAddress) -> bool:
    return address.packed[0] & 2 != 0


def is_mac_universally_administered(address: MacAddress) -> bool:
    return address.packed[0] & 2 == 0


def is_multicast(address: IpAddress | MacAddress) -> bool:
    """224/4, ff00::/8, or a MAC address with the group bit set."""
    if isinstance(address, MacAddress):
        return is_mac_multicast(address)
    if isinstance(address, IPv4Address):
        return int(address) >> 28 == 0xE
    return int(address) >> 120 == 0xFF


def is_broadcast(address: IPv4Address | MacAddress) -> bool:
    """255.255.255.255 or ff:ff:ff:ff:ff:ff."""
    if isinstance(address, MacAddress):
        return is_mac_broadcast(address)
    return int(address) == 0xFFFFFFFF


def is_unicast(address: IpAddress | MacAddress) -> bool:
    """Not multicast, unspecified or the IPv4 broadcast address (which says
    nothing about reachability); a MAC address without the group bit."""
    if isinstance(address, MacAddress):
        return is_mac_unicast(address)
    if is_multicast(address) or is_unspecified(address):
        return False
    return not (isinstance(address, IPv4Address) and is_broadcast(address))
