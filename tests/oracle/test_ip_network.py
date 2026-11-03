"""Ports of Effect's ``net/IpNetwork.test.ts``.

Each test's docstring is the Effect test title. A network is an
``ipaddress.IPv4Network`` / ``IPv6Network``; ``format`` stands in for
``toJSON``/``inspect``/``toString``; ``network_address`` for ``.address``.

The schema test ``decodes declarations and canonically encodes Schema
strings`` is ported in ``test_schema_net.py``.

Omitted, with the reason:

- In ``rejects invalid prefix lengths and host bits``, the ``1.5``, ``NaN``
  and ``Infinity`` prefixes: the prefix length is typed ``int``.
- The data-last forms in the containment tests: Python calls take both
  arguments.
"""

from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyfect.net import ip_interface as ii
from pyfect.net import ip_network as n
from pyfect.net import net_address as na
from pyfect.net.net_address import NetAddressError
from pyfect.result import Err, Ok, Result


def ok[A](result: Result[A, Any]) -> A:
    assert isinstance(result, Ok), result
    return result.value


def err[E](result: Result[Any, E]) -> E:
    assert isinstance(result, Err), result
    return result.error


ip = na.ip_from_string_unsafe


def network(text: str) -> n.IpNetwork:
    return ok(n.from_string(text))


def test_serializes() -> None:
    """serializes and inspects canonical strings"""
    for expected in ["192.0.2.0/24", "2001:db8::/32"]:
        assert n.format(n.from_string_unsafe(expected)) == expected


def test_constructor_keeps_address() -> None:
    """retains the address supplied to checked constructors"""
    address = na.ipv4_loopback
    assert err(n.make(address, 33)).input == address
    assert err(n.make(address, 8)).input == address
    assert err(n.from_address(address, 33)).input == address


def test_forwards_errors() -> None:
    """forwards errors from address and prefix validation"""
    for parse in (n.from_string, n.ipv4_from_string):
        assert err(parse("1.2.3.4/+24")).input == "1.2.3.4/+24"
        assert err(parse("010.2.3.4/24")).input == "010.2.3.4"
        assert err(parse("1.2.3.4/33")).input == ip("1.2.3.4")
    for parse in (n.from_string, n.ipv6_from_string):
        assert err(parse("::ffff:192.000.2.1/128")).input == "192.000.2.1"


def test_canonical_networks() -> None:
    """constructs immutable canonical networks and preserves family identity"""
    ipv4 = n.make_unsafe(na.ipv4_unspecified, 0)
    ipv6 = n.make_unsafe(na.ipv6_unspecified, 0)
    assert isinstance(ipv4, IPv4Network)
    assert isinstance(ipv6, IPv6Network)
    assert ipv4 != ipv6
    assert n.format(ipv4) == "0.0.0.0/0"
    assert n.format(ipv6) == "::/0"


def test_rejects_invalid() -> None:
    """rejects invalid prefix lengths and host bits"""
    ipv4, ipv6 = ip("10.1.2.3"), ip("2001:db8::1")
    err(n.make(ipv4, 33))
    err(n.from_address(ipv4, 33))
    err(n.make(ipv6, 129))
    assert err(n.from_string("10.1.2.3/8")).input == ipv4
    err(n.make(ipv4, 8))
    err(n.make(ipv6, 32))
    error = err(n.make(ipv4, -1))
    assert isinstance(error, NetAddressError)
    assert error.message == "prefix length must be an integer from 0 through 32"


def test_truncates() -> None:
    """explicitly truncates byte-aligned and partial-byte host addresses"""
    assert n.format(ok(n.from_address(ip("10.1.2.3"), 8))) == "10.0.0.0/8"
    assert n.format(ok(n.from_address(ip("192.0.2.255"), 25))) == "192.0.2.128/25"
    assert n.format(ok(n.from_address(ip("2001:db8:0:1:ffff::1"), 63))) == "2001:db8::/63"
    assert n.format(ok(n.from_address(ip("2001:db8:0:1:ffff::1"), 65))) == "2001:db8:0:1:8000::/65"


def test_derived_addresses() -> None:
    """requires derived addresses to revalidate refinements"""
    multicast = na.ipv4_from_bytes_unsafe(bytes([224, 0, 0, 1]))
    assert na.is_multicast(multicast)
    direct = n.from_address_unsafe(multicast, 0)
    via_interface = n.from_interface(ii.make_unsafe(multicast, 0))
    for derived in (direct, via_interface):
        assert na.format_ip(derived.network_address) == "0.0.0.0"
        assert not na.is_multicast(derived.network_address)
        last = n.last_address(derived)
        assert na.format_ip(last) == "255.255.255.255"
        assert not na.is_multicast(last)
    broadcast = n.last_address(n.make_unsafe(na.ipv4_unspecified, 0))
    assert not na.is_unspecified(broadcast)
    assert na.is_broadcast(broadcast)
    loopback = ip("::1")
    assert na.is_loopback(loopback)
    for derived in (
        n.from_address_unsafe(loopback, 64),
        n.from_interface(ii.make_unsafe(loopback, 64)),
    ):
        assert na.format_ip(derived.network_address) == "::"
        assert not na.is_loopback(derived.network_address)
        assert na.is_unspecified(derived.network_address)


def test_parses_cidr() -> None:
    """parses strict CIDR and formats canonical address text"""
    assert n.format(network("192.0.2.0/24")) == "192.0.2.0/24"
    assert n.format(network("2001:0DB8:0000:0000:0000:0000:0000:0000/32")) == "2001:db8::/32"
    assert n.format(network("::ffff:192.0.2.0/120")) == "::ffff:192.0.2.0/120"


def test_rejects_malformed() -> None:
    """rejects malformed and non-network CIDR input"""
    for text in [
        "1.2.3.4",
        "1.2.3.4/",
        "/24",
        "1.2.3.4/24/1",
        "1.2.3.4/+24",
        "1.2.3.4/024",
        "1.2.3.4/24 ",
        "1.2.3.4/1e1",
        "1.2.3.4/33",
        "10.1.2.3/8",
        "2001:db8::1/32",
    ]:
        err(n.from_string(text))
    assert (
        err(n.from_string("1.2.3.4/+24")).message
        == "prefix length must be an unpadded ASCII decimal integer"
    )
    err(n.ipv4_from_string("::/0"))
    err(n.ipv6_from_string("0.0.0.0/0"))


def test_equality() -> None:
    """uses numeric equality and matching hashes"""
    first, second = network("2001:0DB8:0:0:0:0:0:0/32"), network("2001:db8::/32")
    assert first == second
    assert hash(first) == hash(second)
    assert first != network("2001:db8::/33")


def test_counts() -> None:
    """computes first, last, and exact address counts"""
    ipv4_all, ipv6_all = network("0.0.0.0/0"), network("::/0")
    assert na.format_ip(n.first_address(ipv4_all)) == "0.0.0.0"
    assert na.format_ip(n.last_address(ipv4_all)) == "255.255.255.255"
    assert n.address_count(ipv4_all) == 1 << 32
    assert na.format_ip(n.last_address(ipv6_all)) == "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"
    assert n.address_count(ipv6_all) == 1 << 128
    ipv4_pair = network("192.0.2.0/31")
    assert na.format_ip(n.last_address(ipv4_pair)) == "192.0.2.1"
    assert n.address_count(ipv4_pair) == 2
    assert na.format_ip(n.last_address(network("192.0.2.128/25"))) == "192.0.2.255"
    ipv6_pair = network("2001:db8::/127")
    assert na.format_ip(n.last_address(ipv6_pair)) == "2001:db8::1"
    assert n.address_count(ipv6_pair) == 2
    assert (
        na.format_ip(n.last_address(network("2001:db8:0:1:8000::/65")))
        == "2001:db8:0:1:ffff:ffff:ffff:ffff"
    )
    host = network("255.255.255.255/32")
    assert na.format_ip(n.last_address(host)) == "255.255.255.255"
    assert n.address_count(host) == 1


def test_contains() -> None:
    """checks address containment in data-first and data-last forms"""
    network_ = network("192.0.2.0/25")
    assert n.contains(network_, ip("192.0.2.0"))
    assert n.contains(network_, ip("192.0.2.64"))
    assert n.contains(network_, ip("192.0.2.127"))
    assert not n.contains(network_, ip("192.0.1.255"))
    assert not n.contains(network_, ip("192.0.2.128"))
    assert not n.contains(network_, ip("::ffff:192.0.2.1"))


def test_contains_network() -> None:
    """checks network containment and overlap"""
    parent = network("2001:db8::/63")
    child = network("2001:db8:0:1:8000::/65")
    sibling = network("2001:db8:0:1::/65")
    disjoint = network("2001:db8:0:2::/63")
    assert n.contains_network(parent, parent)
    assert n.contains_network(parent, child)
    assert not n.contains_network(child, parent)
    assert n.overlaps(parent, child)
    assert n.overlaps(child, parent)
    assert not n.overlaps(child, sibling)
    assert not n.overlaps(parent, disjoint)
    assert not n.overlaps(parent, network("0.0.0.0/0"))


def test_unsafe_wrappers() -> None:
    """provides checked unsafe wrappers"""
    assert n.format(n.from_address_unsafe(ip("10.1.2.3"), 8)) == "10.0.0.0/8"
    assert n.format(n.from_string_unsafe("10.0.0.0/8")) == "10.0.0.0/8"
    with pytest.raises(NetAddressError):
        n.make_unsafe(ip("10.1.2.3"), 8)
    with pytest.raises(NetAddressError):
        n.from_address_unsafe(ip("10.1.2.3"), 33)
    with pytest.raises(NetAddressError):
        n.from_string_unsafe("10.1.2.3/8")


@given(st.integers(0, 0xFFFFFFFF), st.integers(0, 32))
def test_range_models_ipv4(value: int, prefix: int) -> None:
    """matches independent range models for generated networks"""
    address = IPv4Address(value)
    network_ = ok(n.from_address(address, prefix))
    host_mask = (1 << (32 - prefix)) - 1
    first, last = value & ~host_mask, (value & ~host_mask) | host_mask
    assert ok(n.from_string(n.format(network_))) == network_
    assert int(n.first_address(network_)) == first
    assert int(n.last_address(network_)) == last
    assert n.address_count(network_) == 2 ** (32 - prefix)
    assert n.contains(network_, address)


@given(st.integers(0, (1 << 128) - 1), st.integers(0, 128))
def test_range_models_ipv6(value: int, prefix: int) -> None:
    """matches independent range models for generated networks"""
    address = IPv6Address(value)
    network_ = ok(n.from_address(address, prefix))
    host_mask = (1 << (128 - prefix)) - 1
    assert ok(n.from_string(n.format(network_))) == network_
    assert int(n.first_address(network_)) == value & ~host_mask
    assert int(n.last_address(network_)) == value | host_mask
    assert n.address_count(network_) == 1 << (128 - prefix)
    assert n.contains(network_, address)


def test_from_input_strings() -> None:
    """parses strings and returns values unchanged"""
    ipv4 = ok(n.ipv4_from_string("192.0.2.0/24"))
    ipv6 = ok(n.ipv6_from_string("2001:db8::/32"))
    assert ok(n.from_input("192.0.2.0/24")) == ipv4
    assert ok(n.ipv4_from_input("192.0.2.0/24")) == ipv4
    assert ok(n.ipv6_from_input("2001:DB8::/32")) == ipv6
    assert ok(n.from_input(ipv6)) is ipv6
    assert ok(n.ipv4_from_input(ipv4)) is ipv4
    assert ok(n.ipv6_from_input(ipv6)) is ipv6
    err(n.from_input("192.0.2.1/24"))
    err(n.ipv4_from_input("2001:db8::/32"))
    err(n.ipv6_from_input("192.0.2.0/24"))


def test_from_input_parts() -> None:
    """converts an address and prefix length"""
    ipv4, ipv6 = network("192.0.2.0/24"), network("2001:db8::/32")
    assert ok(n.from_input({"address": (192, 0, 2, 0), "prefix_length": 24})) == ipv4
    assert ok(n.ipv4_from_input({"address": "192.0.2.0", "prefix_length": 24})) == ipv4
    assert ok(n.ipv6_from_input({"address": "2001:db8::", "prefix_length": 32})) == ipv6
    err(n.from_input({"address": "192.0.2.1", "prefix_length": 24}))
    err(n.ipv4_from_input({"address": "2001:db8::", "prefix_length": 32}))
    err(n.ipv6_from_input({"address": "192.0.2.0", "prefix_length": 24}))


def test_unsafe_variant() -> None:
    """has an unsafe variant that throws on failure"""
    prefix = network("192.0.2.0/24")
    assert n.from_input_unsafe(prefix) is prefix
    assert n.from_input_unsafe("192.0.2.0/24") == prefix
    with pytest.raises(NetAddressError):
        n.from_input_unsafe("192.0.2.1/24")
