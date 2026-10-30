"""An address on a network, with its prefix length (Effect's
``IpInterface``): the standard library's ``ipaddress.IPv4Interface`` /
``IPv6Interface``, host bits kept.

``from_string("192.0.2.1/24")`` parses strictly (an unpadded decimal prefix,
Effect's address rules); a bare address takes the full-width prefix unless
``prefix="required"``. ``format`` writes ``address/prefix`` with
``format_ip``'s canonical address.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from ipaddress import IPv4Address, IPv4Interface, IPv6Address, IPv6Interface
from typing import Literal, TypedDict, overload

from pyfect._digits import parse_digits
from pyfect.net._errors import NetAddressError, address_error
from pyfect.net.net_address._ip import (
    IpAddress,
    IpAddressInput,
    Ipv4AddressInput,
    Ipv6AddressInput,
    format_ip,
    ip_from_input,
    ip_from_string,
    width,
)
from pyfect.net.net_address._ip import ipv4_from_input as ipv4_address_from_input
from pyfect.net.net_address._ip import ipv4_from_string as parse_ipv4
from pyfect.net.net_address._ip import ipv6_from_input as ipv6_address_from_input
from pyfect.net.net_address._ip import (
    ipv6_from_string as parse_ipv6,
)
from pyfect.result import Err, Ok, Result

type IpInterface = IPv4Interface | IPv6Interface
type Prefix = Literal["required", "optional"]


class IpInterfaceParts[A = IpAddressInput](TypedDict):
    address: A
    prefix_length: int


type IpInterfaceInput = IpInterface | str | IpInterfaceParts[IpAddressInput]
type Ipv4InterfaceInput = IPv4Interface | str | IpInterfaceParts[Ipv4AddressInput]
type Ipv6InterfaceInput = IPv6Interface | str | IpInterfaceParts[Ipv6AddressInput]


@overload
def make(address: IPv4Address, prefix_length: int) -> Result[IPv4Interface, NetAddressError]: ...
@overload
def make(address: IPv6Address, prefix_length: int) -> Result[IPv6Interface, NetAddressError]: ...
@overload
def make(address: IpAddress, prefix_length: int) -> Result[IpInterface, NetAddressError]: ...
def make(address: IpAddress, prefix_length: int) -> Result[IpInterface, NetAddressError]:
    top = width(address)
    if not 0 <= prefix_length <= top:
        return address_error(address, f"prefix length must be an integer from 0 through {top}")
    if isinstance(address, IPv4Address):
        return Ok(IPv4Interface((address, prefix_length)))
    return Ok(IPv6Interface((address, prefix_length)))


@overload
def make_unsafe(address: IPv4Address, prefix_length: int) -> IPv4Interface: ...
@overload
def make_unsafe(address: IPv6Address, prefix_length: int) -> IPv6Interface: ...
@overload
def make_unsafe(address: IpAddress, prefix_length: int) -> IpInterface: ...
def make_unsafe(address: IpAddress, prefix_length: int) -> IpInterface:
    return make(address, prefix_length).get_or_raise()


@overload
def split_prefix(
    text: str, prefix: Literal["required"]
) -> Result[tuple[str, int], NetAddressError]: ...
@overload
def split_prefix(text: str, prefix: Prefix) -> Result[tuple[str, int | None], NetAddressError]: ...
def split_prefix(text: str, prefix: Prefix) -> Result[tuple[str, int | None], NetAddressError]:
    """``address/prefix`` split; the prefix ``None`` when optional and
    absent."""
    slash = text.find("/")
    if slash == -1 and prefix != "required":
        return Ok((text, None))
    if slash <= 0 or slash != text.rfind("/") or slash == len(text) - 1:
        return address_error(text, "expected an address and prefix length separated by one slash")
    digits = text[slash + 1 :]
    length = parse_digits(digits, unpadded=True)
    if length is None:
        return address_error(text, "prefix length must be an unpadded ASCII decimal integer")
    return Ok((text[:slash], length))


def _parse[A: IpAddress](
    text: str, prefix: Prefix, parse: Callable[[str], Result[A, NetAddressError]]
) -> Result[tuple[A, int], NetAddressError]:
    match split_prefix(text, prefix):
        case Err() as error:
            return error
        case Ok((address_text, length)):
            return parse(address_text).map(
                lambda address: (address, width(address) if length is None else length)
            )


def ipv4_from_string(
    text: str, *, prefix: Prefix = "optional"
) -> Result[IPv4Interface, NetAddressError]:
    return _parse(text, prefix, parse_ipv4).flat_map(lambda p: make(p[0], p[1]))


def ipv6_from_string(
    text: str, *, prefix: Prefix = "optional"
) -> Result[IPv6Interface, NetAddressError]:
    return _parse(text, prefix, parse_ipv6).flat_map(lambda p: make(p[0], p[1]))


def from_string(text: str, *, prefix: Prefix = "optional") -> Result[IpInterface, NetAddressError]:
    return _parse(text, prefix, ip_from_string).flat_map(lambda p: make(p[0], p[1]))


def from_string_unsafe(text: str, *, prefix: Prefix = "optional") -> IpInterface:
    return from_string(text, prefix=prefix).get_or_raise()


def _parts[I, A: IpAddress](
    value: Mapping[str, object], to_address: Callable[[I], Result[A, NetAddressError]]
) -> Result[tuple[A, int], NetAddressError]:
    if "address" not in value or "prefix_length" not in value:
        return address_error(value, "expected an address and prefix length")
    length = value["prefix_length"]
    return to_address(value["address"]).map(lambda address: (address, length))  # pyright: ignore


def from_input(
    value: IpInterfaceInput, *, prefix: Prefix = "optional"
) -> Result[IpInterface, NetAddressError]:
    match value:
        case IPv4Interface() | IPv6Interface():
            return Ok(value)
        case str():
            return from_string(value, prefix=prefix)
        case _:
            return _parts(value, ip_from_input).flat_map(lambda p: make(p[0], p[1]))


def from_input_unsafe(value: IpInterfaceInput, *, prefix: Prefix = "optional") -> IpInterface:
    return from_input(value, prefix=prefix).get_or_raise()


def ipv4_from_input(
    value: Ipv4InterfaceInput, *, prefix: Prefix = "optional"
) -> Result[IPv4Interface, NetAddressError]:
    match value:
        case IPv4Interface():
            return Ok(value)
        case str():
            return ipv4_from_string(value, prefix=prefix)
        case _:
            return _parts(value, ipv4_address_from_input).flat_map(lambda p: make(p[0], p[1]))


def ipv6_from_input(
    value: Ipv6InterfaceInput, *, prefix: Prefix = "optional"
) -> Result[IPv6Interface, NetAddressError]:
    match value:
        case IPv6Interface():
            return Ok(value)
        case str():
            return ipv6_from_string(value, prefix=prefix)
        case _:
            return _parts(value, ipv6_address_from_input).flat_map(lambda p: make(p[0], p[1]))


def format(interface: IpInterface) -> str:
    """``address/prefix`` with the canonical address text."""
    return f"{format_ip(interface.ip)}/{interface.network.prefixlen}"


__all__ = [
    "IpInterface",
    "IpInterfaceInput",
    "IpInterfaceParts",
    "Ipv4InterfaceInput",
    "Ipv6InterfaceInput",
    "Prefix",
    "format",
    "from_input",
    "from_input_unsafe",
    "from_string",
    "from_string_unsafe",
    "ipv4_from_input",
    "ipv4_from_string",
    "ipv6_from_input",
    "ipv6_from_string",
    "make",
    "make_unsafe",
    "split_prefix",
]
