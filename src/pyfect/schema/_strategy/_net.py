"""Strategies of the network declarations (``schema/_net.py``). Effect
gives them none; pyfect's catalog guards need every schema to draw values.
Addresses mix the special ones (loopback, broadcast, multicast, private,
link-local, unique-local, unspecified) with uniform ones, so each
refinement still finds values."""

from __future__ import annotations

from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from typing import Any

from hypothesis import strategies as st

from pyfect.net import host
from pyfect.net import net_address as na

_IPV4_SPECIAL = tuple(
    map(
        IPv4Address,
        (
            "0.0.0.0",
            "127.0.0.1",
            "169.254.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "224.0.0.1",
            "255.255.255.255",
        ),
    )
)
_IPV6_SPECIAL = tuple(map(IPv6Address, ("::", "::1", "fe80::1", "fc00::1", "ff02::1")))
_MAC_SPECIAL = tuple(
    bytes.fromhex(text) for text in ("ffffffffffff", "01005e000001", "020000000001", "001122334455")
)

type _Parameters = tuple[Any, ...]

ipv4 = st.one_of(st.sampled_from(_IPV4_SPECIAL), st.ip_addresses(v=4).map(IPv4Address))
ipv6 = st.one_of(st.sampled_from(_IPV6_SPECIAL), st.ip_addresses(v=6).map(IPv6Address))
_ports = st.integers(0, 0xFFFF)


def mac_addresses(_: _Parameters) -> st.SearchStrategy[na.MacAddress]:
    octets = st.one_of(st.sampled_from(_MAC_SPECIAL), st.binary(min_size=6, max_size=6))
    return octets.map(na.MacAddress)


def ipv4_addresses(_: _Parameters) -> st.SearchStrategy[IPv4Address]:
    return ipv4


def ipv6_addresses(_: _Parameters) -> st.SearchStrategy[IPv6Address]:
    return ipv6


def ip_addresses(_: _Parameters) -> st.SearchStrategy[IPv4Address | IPv6Address]:
    return st.one_of(ipv4, ipv6)


def _ipv4_interface(address: IPv4Address, prefix: int) -> IPv4Interface:
    return IPv4Interface((address, prefix))


def _ipv6_interface(address: IPv6Address, prefix: int) -> IPv6Interface:
    return IPv6Interface((address, prefix))


def _ipv4_network(address: IPv4Address, prefix: int) -> IPv4Network:
    return IPv4Network((address, prefix), strict=False)


def _ipv6_network(address: IPv6Address, prefix: int) -> IPv6Network:
    return IPv6Network((address, prefix), strict=False)


def ipv4_interfaces(_: _Parameters) -> st.SearchStrategy[IPv4Interface]:
    return st.builds(_ipv4_interface, ipv4, st.integers(0, 32))


def ipv6_interfaces(_: _Parameters) -> st.SearchStrategy[IPv6Interface]:
    return st.builds(_ipv6_interface, ipv6, st.integers(0, 128))


def ip_interfaces(p: _Parameters) -> st.SearchStrategy[IPv4Interface | IPv6Interface]:
    return st.one_of(ipv4_interfaces(p), ipv6_interfaces(p))


def ipv4_networks(_: _Parameters) -> st.SearchStrategy[IPv4Network]:
    return st.builds(_ipv4_network, ipv4, st.integers(0, 32))


def ipv6_networks(_: _Parameters) -> st.SearchStrategy[IPv6Network]:
    return st.builds(_ipv6_network, ipv6, st.integers(0, 128))


def ip_networks(p: _Parameters) -> st.SearchStrategy[IPv4Network | IPv6Network]:
    return st.one_of(ipv4_networks(p), ipv6_networks(p))


def inet_v4(_: _Parameters) -> st.SearchStrategy[na.InetAddressV4]:
    return st.builds(na.InetAddressV4, ipv4, _ports)


def inet_v6(_: _Parameters) -> st.SearchStrategy[na.InetAddressV6]:
    scopes = st.one_of(st.just(0), st.integers(0, 0xFFFFFFFF))
    return st.builds(na.InetAddressV6, ipv6, _ports, scopes)


def inet(p: _Parameters) -> st.SearchStrategy[na.InetAddress]:
    return st.one_of(inet_v4(p), inet_v6(p))


def unix_paths(_: _Parameters) -> st.SearchStrategy[na.UnixPathAddress]:
    return st.text().map(na.UnixPathAddress)


def socket_addresses(p: _Parameters) -> st.SearchStrategy[na.SocketAddress]:
    return st.one_of(inet(p), unix_paths(p))


def host_ports(_: _Parameters) -> st.SearchStrategy[host.HostPort]:
    from pyfect.schema._net import Host
    from pyfect.schema._to_strategy import to_strategy

    return st.builds(host.HostPort, to_strategy(Host), _ports)
