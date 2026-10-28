"""Ports of Effect's ``net/IpInterface.test.ts``.

Each test's docstring is the Effect test title. An interface is an
``ipaddress.IPv4Interface`` / ``IPv6Interface``; ``format`` stands in for
``toJSON``/``inspect``.

Omitted, with the reason:

- ``decodes and canonically encodes schemas``: ``Schema.IpInterfaceFromString``
  is not ported.
- In ``rejects invalid prefixes and malformed input``, the ``1.5``, ``NaN``
  and ``Infinity`` prefixes: the prefix length is typed ``int``.
"""

from ipaddress import IPv4Interface, IPv6Interface
from typing import Any

import pytest

from pyfect.net import ip_interface as ii
from pyfect.net import ip_network as inet
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


def interface(text: str) -> ii.IpInterface:
    return ok(ii.from_string(text))


def test_serializes() -> None:
    """serializes and inspects canonical strings"""
    for expected in ["192.0.2.1/24", "2001:db8::1/64"]:
        assert ii.format(ii.from_string_unsafe(expected)) == expected


def test_constructor_keeps_address() -> None:
    """retains the address supplied to checked constructors"""
    assert err(ii.make(na.ipv4_loopback, 33)).input == na.ipv4_loopback


def test_forwards_errors() -> None:
    """forwards errors from address and prefix validation"""
    for parse in (ii.from_string, ii.ipv4_from_string):
        assert err(parse("1.2.3.4/+24")).input == "1.2.3.4/+24"
        assert err(parse("010.2.3.4/24")).input == "010.2.3.4"
        assert err(parse("1.2.3.4/33")).input == ip("1.2.3.4")
    for parse in (ii.from_string, ii.ipv6_from_string):
        assert err(parse("::ffff:192.000.2.1/128")).input == "192.000.2.1"


def test_one_representation() -> None:
    """constructs one generic runtime representation"""
    assert isinstance(ii.make_unsafe(na.ipv4_unspecified, 0), IPv4Interface)
    assert isinstance(ii.make_unsafe(na.ipv6_unspecified, 0), IPv6Interface)


def test_bare_addresses() -> None:
    """defaults bare addresses to full-width prefixes"""
    assert ii.format(interface("192.0.2.1")) == "192.0.2.1/32"
    assert ii.format(interface("2001:db8::1")) == "2001:db8::1/128"


def test_keeps_host_bits() -> None:
    """parses prefixes and preserves host bits"""
    assert ii.format(interface("192.0.2.1/24")) == "192.0.2.1/24"
    assert ii.format(interface("2001:0DB8:0000:0000:0000:0000:0000:0001/64")) == "2001:db8::1/64"


def test_rejects_invalid() -> None:
    """rejects invalid prefixes and malformed input"""
    address = ip("10.1.2.3")
    for prefix in [-1, 33]:
        err(ii.make(address, prefix))
    assert isinstance(err(ii.make(address, -1)), NetAddressError)
    assert (
        err(ii.from_string("1.2.3.4/+24")).message
        == "prefix length must be an unpadded ASCII decimal integer"
    )
    err(ii.from_string("1.2.3.4", prefix="required"))
    err(ii.ipv4_from_string("::1/128"))
    err(ii.ipv6_from_string("127.0.0.1/32"))


def test_equality() -> None:
    """uses address and prefix equality with matching hashes"""
    first = interface("2001:0DB8:0:0:0:0:0:1/64")
    second = interface("2001:db8::1/64")
    assert first == second
    assert hash(first) == hash(second)
    assert first != interface("2001:db8::1/65")


def test_containing_network() -> None:
    """converts to the canonical containing network"""
    assert inet.format(inet.from_interface(interface("10.1.2.3/8"))) == "10.0.0.0/8"


def test_throwing_counterparts() -> None:
    """provides throwing counterparts"""
    assert ii.format(ii.from_string_unsafe("10.1.2.3/8")) == "10.1.2.3/8"
    with pytest.raises(NetAddressError):
        ii.make_unsafe(ip("10.1.2.3"), 33)


def test_from_input_strings() -> None:
    """parses strings with options and returns values unchanged"""
    ipv4 = ok(ii.ipv4_from_string("192.0.2.1/24"))
    ipv6 = ok(ii.ipv6_from_string("2001:db8::1/64"))
    assert ok(ii.from_input("192.0.2.1/24")) == ipv4
    assert ok(ii.ipv4_from_input("192.0.2.1/24")) == ipv4
    assert ok(ii.ipv6_from_input("2001:DB8::1/64")) == ipv6
    assert ok(ii.from_input("192.0.2.1")).network.prefixlen == 32
    assert ok(ii.from_input(ipv6)) is ipv6
    assert ok(ii.ipv4_from_input(ipv4)) is ipv4
    assert ok(ii.ipv6_from_input(ipv6)) is ipv6
    err(ii.from_input("192.0.2.1", prefix="required"))
    err(ii.ipv4_from_input("2001:db8::1/64"))
    err(ii.ipv6_from_input("192.0.2.1/24"))


def test_from_input_parts() -> None:
    """converts an address and prefix length"""
    ipv4 = interface("192.0.2.1/24")
    ipv6 = interface("2001:db8::1/64")
    assert ok(ii.from_input({"address": (192, 0, 2, 1), "prefix_length": 24})) == ipv4
    assert ok(ii.ipv4_from_input({"address": "192.0.2.1", "prefix_length": 24})) == ipv4
    v6 = ok(na.ipv6_from_string("2001:db8::1"))
    assert ok(ii.ipv6_from_input({"address": v6, "prefix_length": 64})) == ipv6
    err(ii.from_input({"address": "192.0.2.1", "prefix_length": 33}))
    err(ii.ipv4_from_input({"address": "2001:db8::1", "prefix_length": 64}))
    err(ii.ipv6_from_input({"address": "192.0.2.1", "prefix_length": 24}))


def test_unsafe_variant() -> None:
    """has an unsafe variant that throws on failure"""
    address = interface("192.0.2.1/24")
    assert ii.from_input_unsafe(address) is address
    assert ii.from_input_unsafe("192.0.2.1").network.prefixlen == 32
    with pytest.raises(NetAddressError):
        ii.from_input_unsafe("192.0.2.1", prefix="required")
