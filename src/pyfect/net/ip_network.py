"""CIDR networks (Effect's ``IpNetwork``): the standard library's
``ipaddress.IPv4Network`` / ``IPv6Network``, always canonical (no host
bits).

``make`` rejects an address with host bits; ``from_address`` clears them.
``from_string`` parses strict CIDR text. ``first_address``,
``last_address``, ``address_count``, ``contains``, ``contains_network`` and
``overlaps`` compare only networks of one family; across families they are
``False``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import overload

from pyfect.net import ip_interface
from pyfect.net._errors import NetAddressError, address_error
from pyfect.net.ip_interface import IpInterface, IpInterfaceParts, Prefix
from pyfect.net.net_address._ip import (
    IpAddress,
    IpAddressInput,
    Ipv4AddressInput,
    Ipv6AddressInput,
    format_ip,
    ip_from_input,
    ip_from_string,
)
from pyfect.net.net_address._ip import ipv4_from_input as ipv4_address_from_input
from pyfect.net.net_address._ip import ipv4_from_string as parse_ipv4
from pyfect.net.net_address._ip import ipv6_from_input as ipv6_address_from_input
from pyfect.net.net_address._ip import ipv6_from_string as parse_ipv6
from pyfect.result import Err, Ok, Result

type IpNetwork = IPv4Network | IPv6Network
type IpNetworkParts[A = IpAddressInput] = IpInterfaceParts[A]
type IpNetworkInput = IpNetwork | str | IpInterfaceParts[IpAddressInput]
type Ipv4NetworkInput = IPv4Network | str | IpInterfaceParts[Ipv4AddressInput]
type Ipv6NetworkInput = IPv6Network | str | IpInterfaceParts[Ipv6AddressInput]


def _network(address: IpAddress, prefix_length: int) -> IpNetwork:
    if isinstance(address, IPv4Address):
        return IPv4Network((address, prefix_length), strict=False)
    return IPv6Network((address, prefix_length), strict=False)


@overload
def make(address: IPv4Address, prefix_length: int) -> Result[IPv4Network, NetAddressError]: ...
@overload
def make(address: IPv6Address, prefix_length: int) -> Result[IPv6Network, NetAddressError]: ...
@overload
def make(address: IpAddress, prefix_length: int) -> Result[IpNetwork, NetAddressError]: ...
def make(address: IpAddress, prefix_length: int) -> Result[IpNetwork, NetAddressError]:
    """The network ``address/prefix_length``; an address with host bits set
    is rejected."""

    def check(value: IpInterface) -> Result[IpNetwork, NetAddressError]:
        network = _network(address, value.network.prefixlen)
        if network.network_address != address:
            return address_error(address, "address has non-zero host bits")
        return Ok(network)

    return ip_interface.make(address, prefix_length).flat_map(check)


@overload
def make_unsafe(address: IPv4Address, prefix_length: int) -> IPv4Network: ...
@overload
def make_unsafe(address: IPv6Address, prefix_length: int) -> IPv6Network: ...
@overload
def make_unsafe(address: IpAddress, prefix_length: int) -> IpNetwork: ...
def make_unsafe(address: IpAddress, prefix_length: int) -> IpNetwork:
    return make(address, prefix_length).get_or_raise()


@overload
def from_address(
    address: IPv4Address, prefix_length: int
) -> Result[IPv4Network, NetAddressError]: ...
@overload
def from_address(
    address: IPv6Address, prefix_length: int
) -> Result[IPv6Network, NetAddressError]: ...
@overload
def from_address(address: IpAddress, prefix_length: int) -> Result[IpNetwork, NetAddressError]: ...
def from_address(address: IpAddress, prefix_length: int) -> Result[IpNetwork, NetAddressError]:
    """The network containing ``address`` with ``prefix_length``: host bits
    cleared."""
    return ip_interface.make(address, prefix_length).map(
        lambda value: _network(address, value.network.prefixlen)
    )


@overload
def from_address_unsafe(address: IPv4Address, prefix_length: int) -> IPv4Network: ...
@overload
def from_address_unsafe(address: IPv6Address, prefix_length: int) -> IPv6Network: ...
@overload
def from_address_unsafe(address: IpAddress, prefix_length: int) -> IpNetwork: ...
def from_address_unsafe(address: IpAddress, prefix_length: int) -> IpNetwork:
    return from_address(address, prefix_length).get_or_raise()


def from_interface(interface: IpInterface) -> IpNetwork:
    """The canonical network an interface address is on."""
    return interface.network


def _parse[A: IpAddress](
    text: str, parse: Callable[[str], Result[A, NetAddressError]]
) -> Result[tuple[A, int], NetAddressError]:
    match ip_interface.split_prefix(text, "required"):
        case Err() as error:
            return error
        case Ok((address_text, length)):
            return parse(address_text).map(lambda address: (address, length))


def ipv4_from_string(text: str) -> Result[IPv4Network, NetAddressError]:
    return _parse(text, parse_ipv4).flat_map(lambda p: make(p[0], p[1]))


def ipv6_from_string(text: str) -> Result[IPv6Network, NetAddressError]:
    return _parse(text, parse_ipv6).flat_map(lambda p: make(p[0], p[1]))


def from_string(text: str) -> Result[IpNetwork, NetAddressError]:
    """Strict CIDR: ``address/prefix`` with no host bits."""
    return _parse(text, ip_from_string).flat_map(lambda p: make(p[0], p[1]))


def from_string_unsafe(text: str) -> IpNetwork:
    return from_string(text).get_or_raise()


def _parts[I, A: IpAddress](
    value: Mapping[str, object], to_address: Callable[[I], Result[A, NetAddressError]]
) -> Result[tuple[A, int], NetAddressError]:
    if "address" not in value or "prefix_length" not in value:
        return address_error(value, "expected an address and prefix length")
    length = value["prefix_length"]
    return to_address(value["address"]).map(lambda address: (address, length))  # pyright: ignore


def from_input(value: IpNetworkInput) -> Result[IpNetwork, NetAddressError]:
    match value:
        case IPv4Network() | IPv6Network():
            return Ok(value)
        case str():
            return from_string(value)
        case _:
            return _parts(value, ip_from_input).flat_map(lambda p: make(p[0], p[1]))


def from_input_unsafe(value: IpNetworkInput) -> IpNetwork:
    return from_input(value).get_or_raise()


def ipv4_from_input(value: Ipv4NetworkInput) -> Result[IPv4Network, NetAddressError]:
    match value:
        case IPv4Network():
            return Ok(value)
        case str():
            return ipv4_from_string(value)
        case _:
            return _parts(value, ipv4_address_from_input).flat_map(lambda p: make(p[0], p[1]))


def ipv6_from_input(value: Ipv6NetworkInput) -> Result[IPv6Network, NetAddressError]:
    match value:
        case IPv6Network():
            return Ok(value)
        case str():
            return ipv6_from_string(value)
        case _:
            return _parts(value, ipv6_address_from_input).flat_map(lambda p: make(p[0], p[1]))


def format(network: IpNetwork) -> str:
    """``address/prefix`` with the canonical address text."""
    return f"{format_ip(network.network_address)}/{network.prefixlen}"


@overload
def first_address(network: IPv4Network) -> IPv4Address: ...
@overload
def first_address(network: IPv6Network) -> IPv6Address: ...
def first_address(network: IpNetwork) -> IpAddress:
    return network.network_address


@overload
def last_address(network: IPv4Network) -> IPv4Address: ...
@overload
def last_address(network: IPv6Network) -> IPv6Address: ...
def last_address(network: IpNetwork) -> IpAddress:
    return network.broadcast_address


def address_count(network: IpNetwork) -> int:
    return network.num_addresses


def contains(network: IpNetwork, address: IpAddress) -> bool:
    """Whether ``address`` is in ``network`` (never across families)."""
    return network.version == address.version and address in network


def contains_network(network: IpNetwork, other: IpNetwork) -> bool:
    """Whether every address of ``other`` is in ``network``."""
    return network.prefixlen <= other.prefixlen and contains(network, other.network_address)


def overlaps(network: IpNetwork, other: IpNetwork) -> bool:
    """Whether the two networks share an address."""
    if network.prefixlen <= other.prefixlen:
        return contains(network, other.network_address)
    return contains(other, network.network_address)


__all__ = [
    "IpNetwork",
    "IpNetworkInput",
    "IpNetworkParts",
    "Ipv4NetworkInput",
    "Ipv6NetworkInput",
    "Prefix",
    "address_count",
    "contains",
    "contains_network",
    "first_address",
    "format",
    "from_address",
    "from_address_unsafe",
    "from_input",
    "from_input_unsafe",
    "from_interface",
    "from_string",
    "from_string_unsafe",
    "ipv4_from_input",
    "ipv4_from_string",
    "ipv6_from_input",
    "ipv6_from_string",
    "last_address",
    "make",
    "make_unsafe",
    "overlaps",
]
