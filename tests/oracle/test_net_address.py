"""Ports of Effect's ``net/NetAddress.test.ts``.

Each test's docstring is the Effect test title. IP addresses are
``ipaddress`` values; ``str`` stands in for ``toJSON``/``inspect``.

Omitted, with the reason:

- ``discriminates addresses sharing the common type id``: addresses are
  distinct classes; ``isinstance`` discriminates them.
- ``validates ports``, ``decodes and canonically encodes schemas``,
  ``validates branded address schemas on decode and encode``: the net schemas
  (``Schema.Port``, ``Schema.IpAddress``, ...) are not ported.
- ``copies Buffer constructor inputs``: Node's ``Buffer``; ``copies byte
  constructor inputs`` covers ``bytearray``.
- In ``converts octets, segments, bytes, and parts``, the sparse-array and
  ``address: null`` cases: JavaScript array holes and untyped values; the
  types rule them out.
"""

from ipaddress import IPv4Address, IPv6Address
from typing import Any, cast

import pytest

from pyfect.http import url as u
from pyfect.net import net_address as na
from pyfect.net.net_address import NetAddressError
from pyfect.result import Err, Ok, Result


def ok[A](result: Result[A, Any]) -> A:
    assert isinstance(result, Ok), result
    return result.value


def err[E](result: Result[Any, E]) -> E:
    assert isinstance(result, Err), result
    return result.error


def v4(text: str) -> IPv4Address:
    return ok(na.ipv4_from_string(text))


def v6(text: str) -> IPv6Address:
    return ok(na.ipv6_from_string(text))


ip = na.ip_from_string_unsafe
mac = na.mac_address_from_string_unsafe
inet = na.inet_address_from_string_unsafe


def test_families() -> None:
    """returns and checks address families"""
    ipv4, ipv6 = v4("1.2.3.4"), v6("2001:db8::1")
    assert na.family_of(ipv4) == "IPv4"
    assert na.family_of(ok(na.inet_address_from_string("[::1]:80")).address) == "IPv6"
    assert [a for a in (ipv4, ipv6) if na.is_family(a, "IPv6")] == [ipv6]


def test_widths() -> None:
    """returns IP address widths"""
    assert na.width(v4("1.2.3.4")) == 32
    assert na.width(v6("2001:db8::1")) == 128


def test_ipv4_parses() -> None:
    """parses strict dotted decimal"""
    assert na.format_ip(v4("1.2.3.4")) == "1.2.3.4"
    assert na.ipv4_to_octets(ok(na.ipv4_from_octets((127, 0, 0, 1)))) == (127, 0, 0, 1)


def test_ipv4_rejects() -> None:
    """rejects malformed inputs"""
    for text in [
        "",
        "127.1",
        "127.0.0.1.2",
        ".1.2.3",
        "1..2.3",
        "-1.2.3.4",
        "+1.2.3.4",
        " 1.2.3.4",
        "01.2.3.4",
        "001.002.003.004",
        "0x7f.0.0.1",
        "256.0.0.1",
    ]:
        err(na.ipv4_from_string(text))
    err(na.ipv4_from_octets((0, 0, 0, 256)))
    err(na.ipv4_from_octets(cast(Any, (0, 0, 0, 1.5))))


IPV6_CASES = [
    ("0:0:0:0:0:0:0:0", "::"),
    ("0:0:0:0:0:0:0:1", "::1"),
    ("2001:0DB8:0000:0000:0001:0000:0000:0001", "2001:db8::1:0:0:1"),
    ("2001:db8:0:1:0:0:0:1", "2001:db8:0:1::1"),
    ("2001:0:0:1:0:0:1:1", "2001::1:0:0:1:1"),
    ("::ffff:192.0.2.128", "::ffff:192.0.2.128"),
    ("::192.0.2.128", "::c000:280"),
    ("2001:db8::192.0.2.1", "2001:db8::c000:201"),
]


def test_ipv6_canonical() -> None:
    """uses canonical compression and embedded IPv4 policy"""
    for text, expected in IPV6_CASES:
        parsed = v6(text)
        assert na.format_ip(parsed) == expected
        assert parsed == v6(expected)


def test_ipv6_rejects() -> None:
    """rejects malformed inputs"""
    for text in [
        "",
        ":",
        ":::1",
        "1::2::3",
        "1:2:3:4:5:6:7",
        "1:2:3:4:5:6:7:8:9",
        "1:2:3:4:5:6:7:8::",
        "1:2:3:4:5:6:7::8",
        "gggg::1",
        "[::1]",
        "fe80::1%1",
        "::ffff:999.1.1.1",
        "::ffff:192.000.2.1",
        "::ffff:1.2.3",
        "192.0.2.1::",
    ]:
        err(na.ipv6_from_string(text))
    err(na.ipv6_from_segments((0, 0, 0, 0, 0, 0, 0, 65536)))


def test_ipv6_round_trips() -> None:
    """round trips constructed numeric values"""
    for segments in [
        (0, 0, 0, 0, 0, 0, 0, 0),
        (0x2001, 0xDB8, 0, 1, 2, 3, 4, 5),
        (0xFFFF,) * 8,
    ]:
        value = ok(na.ipv6_from_segments(cast(na.Ipv6Segments, segments)))
        assert v6(na.format_ip(value)) == value


def test_ipv6_equality() -> None:
    """uses numeric equality and hash laws"""
    expanded, compressed = v6("2001:db8:0:0:0:0:0:1"), v6("2001:db8::1")
    assert expanded == compressed
    assert hash(expanded) == hash(compressed)


def test_ipv4_mapped() -> None:
    """converts mapped IPv4 addresses"""
    ipv4 = v4("192.0.2.128")
    mapped = na.to_ipv4_mapped(ipv4)
    assert na.is_ipv4_mapped(mapped)
    assert na.format_ip(mapped) == "::ffff:192.0.2.128"
    assert na.from_ipv4_mapped(mapped) == ipv4
    assert na.from_ipv4_mapped(v6("::1")) is None
    assert na.to_canonical(mapped) == ipv4
    assert na.to_canonical(ipv4) == ipv4


def test_ipv6_octets() -> None:
    """returns IPv6 octets"""
    assert na.ipv6_to_octets(v6("2001:db8::1")) == (0x20, 0x01, 0x0D, 0xB8, *[0] * 11, 1)
    assert na.format_ip(na.ipv6_from_bytes_unsafe(bytes(16))) == "::"
    assert na.format_ip(na.ipv4_from_bytes_unsafe(bytes([127, 0, 0, 1]))) == "127.0.0.1"


def test_mac_parses() -> None:
    """parses and canonically formats six octets"""
    address = ok(na.mac_address_from_string("02:0A:0b:0C:0d:0E"))
    assert na.format_mac_address(address) == "02:0a:0b:0c:0d:0e"
    assert na.mac_address_to_octets(address) == (2, 10, 11, 12, 13, 14)
    assert address == ok(na.mac_address_from_octets((2, 10, 11, 12, 13, 14)))
    assert hash(address) == hash(mac("02:0a:0b:0c:0d:0e"))


def test_mac_rejects() -> None:
    """rejects malformed inputs and invalid octets"""
    for text in [
        "",
        "00:11:22:33:44",
        "00:11:22:33:44:55:66",
        "0:11:22:33:44:55",
        "00-11-22-33-44-55",
        "0011.2233.4455",
        "gg:11:22:33:44:55",
    ]:
        err(na.mac_address_from_string(text))
    err(na.mac_address_from_octets((0, 0, 0, 0, 0, 256)))
    err(na.mac_address_from_octets(cast(Any, (0, 0, 0, 0, 0, 1.5))))
    with pytest.raises(NetAddressError):
        mac("invalid")


def test_mac_classifies() -> None:
    """classifies address bits"""
    assert na.is_mac_broadcast(mac("ff:ff:ff:ff:ff:ff"))
    assert na.is_mac_multicast(mac("01:00:5e:00:00:01"))
    assert not na.is_mac_unicast(mac("01:00:5e:00:00:01"))
    assert na.is_mac_unicast(mac("00:00:5e:00:53:01"))
    assert na.is_mac_locally_administered(mac("02:00:00:00:00:01"))
    assert not na.is_mac_universally_administered(mac("02:00:00:00:00:01"))
    assert na.is_mac_universally_administered(mac("00:00:5e:00:53:01"))


def test_classifies_ranges() -> None:
    """classifies documented address ranges at their boundaries"""
    assert na.is_unspecified(ip("0.0.0.0"))
    assert na.is_unspecified(ip("::"))
    assert na.is_loopback(ip("127.255.255.255"))
    assert not na.is_loopback(ip("128.0.0.0"))
    assert na.is_multicast(ip("224.0.0.0"))
    assert not na.is_multicast(ip("223.255.255.255"))
    assert na.is_multicast(ip("ff00::"))
    assert na.is_broadcast(na.ipv4_broadcast)
    assert not na.is_broadcast(v4("255.255.255.254"))
    assert na.is_link_local(ip("169.254.255.255"))
    assert not na.is_link_local(ip("169.255.0.0"))
    assert na.is_link_local(ip("febf::"))
    assert not na.is_link_local(ip("fec0::"))
    assert na.is_private(v4("10.255.255.255"))
    assert na.is_private(v4("172.31.255.255"))
    assert na.is_private(v4("192.168.0.0"))
    assert not na.is_private(v4("172.32.0.0"))
    assert na.is_unique_local(v6("fc00::"))
    assert na.is_unique_local(v6("fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))
    assert not na.is_unique_local(v6("fe00::"))
    assert na.ipv4_unspecified == ip("0.0.0.0")
    assert na.ipv6_unspecified == ip("::")


def test_classifies_ip_boundaries() -> None:
    """classifies IP boundaries without claiming reachability"""
    for text in ["1.2.3.4", "127.0.0.1", "169.254.1.1", "240.0.0.1", "::1", "fe80::1"]:
        assert na.is_unicast(ip(text)), text
    for text in ["0.0.0.0", "224.0.0.0", "255.255.255.255", "::", "ff00::"]:
        assert not na.is_unicast(ip(text)), text
    assert na.is_loopback(ip("127.0.0.0"))
    assert na.is_loopback(ip("127.255.255.255"))
    assert not na.is_loopback(ip("128.0.0.0"))
    assert na.is_loopback(ip("::1"))
    assert not na.is_loopback(ip("::2"))
    assert not na.is_loopback(ip("::ffff:127.0.0.1"))
    assert not na.is_multicast(ip("::ffff:224.0.0.1"))
    assert na.is_link_local(ip("169.254.0.0"))
    assert na.is_link_local(ip("169.254.255.255"))
    assert not na.is_link_local(ip("169.255.0.0"))
    assert na.is_link_local(ip("fe80::"))
    assert na.is_link_local(ip("febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))
    assert not na.is_link_local(ip("fec0::"))
    for text in ["10.0.0.0", "10.255.255.255", "172.16.0.0", "172.31.255.255", "192.168.0.0"]:
        assert na.is_private(v4(text)), text
    for text in ["9.255.255.255", "172.15.255.255", "172.32.0.0", "192.169.0.0", "100.64.0.1"]:
        assert not na.is_private(v4(text)), text
    assert na.is_unique_local(v6("fc00::"))
    assert na.is_unique_local(v6("fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"))
    assert not na.is_unique_local(v6("fe00::"))


def test_classifies_mac_bits() -> None:
    """classifies the independent MAC group and administration bits"""
    for text, multicast, local in [
        ("00:00:5e:00:53:01", False, False),
        ("01:00:5e:00:00:01", True, False),
        ("02:00:00:00:00:01", False, True),
        ("03:00:00:00:00:01", True, True),
        ("ff:ff:ff:ff:ff:ff", True, True),
    ]:
        address = mac(text)
        assert na.is_multicast(address) == multicast
        assert na.is_mac_multicast(address) == multicast
        assert na.is_unicast(address) == (not multicast)
        assert na.is_mac_unicast(address) == (not multicast)
        assert na.is_mac_locally_administered(address) == local
        assert na.is_mac_universally_administered(address) == (not local)
    broadcast = mac("ff:ff:ff:ff:ff:ff")
    assert na.is_broadcast(broadcast)
    assert na.is_mac_broadcast(broadcast)
    assert na.is_multicast(broadcast)
    assert not na.is_broadcast(mac("01:00:5e:00:00:01"))
    assert na.is_broadcast(na.ipv4_broadcast)
    assert not na.is_multicast(na.ipv4_broadcast)


def test_serializes() -> None:
    """serializes and inspects canonical strings without private bytes"""
    for address, expected in [
        (na.ipv4_loopback, "127.0.0.1"),
        (na.ipv6_loopback, "::1"),
        (mac("02:0A:0B:0C:0D:0E"), "02:0a:0b:0c:0d:0e"),
        (inet("127.0.0.1:80"), "127.0.0.1:80"),
        (inet("[fe80::1%2]:80"), "[fe80::1%2]:80"),
        (na.unix_path_address("./run/../server.sock"), "./run/../server.sock"),
    ]:
        assert str(address) == expected


def test_preserves_rejected_input() -> None:
    """preserves the input rejected by the failing operation"""
    cases: list[tuple[Any, str, str]] = [
        (na.ipv4_from_string, "01.2.3.4", "01.2.3.4"),
        (na.ipv6_from_string, "::ffff:192.000.2.1", "192.000.2.1"),
        (na.mac_address_from_string, "00-11-22-33-44-55", "00-11-22-33-44-55"),
        (na.inet_address_from_string, "localhost:80", "localhost"),
        (na.inet_address_from_string, "[::ffff:999.0.0.1]:80", "999.0.0.1"),
        (na.inet_address_from_string, "[fe80::1%bad]:80", "[fe80::1%bad]:80"),
    ]
    for parse, text, rejected in cases:
        assert err(parse(text)).input == rejected
    assert err(na.inet_address_from_string("127.0.0.1:65536")).input == na.ipv4_loopback
    assert err(na.socket_address_from_input({"address": "localhost", "port": 80})).input == (
        "localhost"
    )
    assert err(na.inet_address_from_ip_string("localhost", 80)).input == "localhost"
    octets = (256, 0, 0, 1)
    assert err(na.ipv4_from_octets(octets)).input is octets


def test_checked_constructors_keep_address() -> None:
    """retains the address supplied to checked socket constructors"""
    assert err(na.inet_address_v4(na.ipv4_loopback, -1)).input == na.ipv4_loopback
    assert err(na.inet_address_v6(na.ipv6_loopback, -1)).input == na.ipv6_loopback
    assert err(na.inet_address_v6(na.ipv6_loopback, 80, scope_id=-1)).input == na.ipv6_loopback


def test_to_url() -> None:
    """converts internet addresses to normalized URL values"""
    for text, scheme, expected in [
        ("[::]:3000", "https", "https://[::]:3000/"),
        ("0.0.0.0:3000", "http", "http://0.0.0.0:3000/"),
        ("[::1]:3000", "ws", "ws://[::1]:3000/"),
        ("192.0.2.1:80", "http", "http://192.0.2.1/"),
        ("[::1]:443", "HTTPS", "https://[::1]/"),
        ("[::1]:0", "http", "http://[::1]:0/"),
        ("192.0.2.1:65535", "http", "http://192.0.2.1:65535/"),
    ]:
        assert u.href(ok(na.to_url(inet(text), scheme))) == expected
    parsed = ok(na.to_url(inet("[::]:3000")))
    assert u.href(parsed) == "http://[::]:3000/"
    assert u.origin(u.set_hostname(parsed, "127.0.0.1")) == "http://127.0.0.1:3000"
    assert parsed.hostname == "::"


def test_to_url_bare_ip() -> None:
    """converts bare IP addresses without adding an explicit port"""
    for text, expected in [
        ("127.0.0.1", "http://127.0.0.1/"),
        ("::1", "http://[::1]/"),
        ("0.0.0.0", "http://0.0.0.0/"),
        ("::", "http://[::]/"),
    ]:
        parsed = ok(na.to_url(ip(text)))
        assert u.href(parsed) == expected
        assert parsed.port is None
    assert u.href(ok(na.to_url(na.ipv6_loopback, "https"))) == "https://[::1]/"


def test_format_url() -> None:
    """formats URL strings without trailing slashes or default ports"""
    assert ok(na.format_url(na.ipv4_loopback)) == "http://127.0.0.1"
    assert ok(na.format_url(na.ipv6_loopback, "https")) == "https://[::1]"
    assert na.format_url_unsafe(na.ipv4_loopback) == "http://127.0.0.1"
    assert na.format_url_unsafe(na.ipv6_loopback, "https") == "https://[::1]"
    for text, scheme, expected in [
        ("192.0.2.1:80", "http", "http://192.0.2.1"),
        ("[::1]:443", "HTTPS", "https://[::1]"),
        ("[::]:3000", "http", "http://[::]:3000"),
        ("[::1]:0", "http", "http://[::1]:0"),
        ("127.0.0.1:80", "tcp", "tcp://127.0.0.1:80"),
    ]:
        assert ok(na.format_url(inet(text), scheme)) == expected
    scoped = inet("[fe80::1%2]:3000")
    scoped_error = err(na.format_url(scoped))
    assert scoped_error.input == scoped
    assert "scoped IPv6" in scoped_error.message
    scheme_error = err(na.format_url(na.ipv4_loopback, "1http"))
    assert scheme_error.input == na.ipv4_loopback
    assert isinstance(scheme_error.cause, ValueError)
    with pytest.raises(NetAddressError, match="scoped IPv6"):
        na.format_url_unsafe(scoped)
    with pytest.raises(NetAddressError):
        na.format_url_unsafe(na.ipv4_loopback, "1http")


def test_format_unix_path() -> None:
    """formats Unix socket paths without encoding or normalizing them"""
    for path, expected in [
        ("/tmp/server.sock", "unix:///tmp/server.sock"),
        ("./run/../server.sock", "unix://./run/../server.sock"),
        ("/tmp/socket?#%20", "unix:///tmp/socket?#%20"),
        ("/tmp/socket with spaces.sock", "unix:///tmp/socket with spaces.sock"),
        ("", "unix://"),
    ]:
        address = na.unix_path_address(path)
        assert na.format_unix_path(address) == expected
        assert ok(na.format_url(address)) == expected
        assert na.format_url_unsafe(address, "https") == expected


def test_to_url_errors() -> None:
    """returns URL conversion errors for scopes and rejected URLs"""
    for text in ["[fe80::1%2]:3000", "[::%2]:3000"]:
        scoped = inet(text)
        error = err(na.to_url(scoped, "http"))
        assert error.input == scoped
        assert "scoped IPv6" in error.message
        assert error.cause is None
    address = inet("127.0.0.1:80")
    for scheme in ["", "1http", "file"]:
        error = err(na.to_url(address, scheme))
        assert error.input == address
        assert error.message == "failed to construct URL"
        assert isinstance(error.cause, ValueError)


def test_canonicalizes_mapped_inet() -> None:
    """canonicalizes mapped internet addresses while retaining their port"""
    ipv4 = v4("192.0.2.128")
    expected = ok(na.inet_address_v4(ipv4, 4567))
    for scope_id in [0, 7]:
        mapped = ok(na.inet_address_v6(na.to_ipv4_mapped(ipv4), 4567, scope_id=scope_id))
        canonical = na.to_canonical(mapped)
        assert isinstance(canonical, na.InetAddressV4)
        assert canonical == expected
        assert hash(canonical) == hash(expected)
        assert na.to_canonical(canonical) is canonical


def test_canonical_keeps_identity() -> None:
    """retains identity and scope for internet addresses that need no canonicalization"""
    scoped = ok(na.inet_address_from_input({"address": "fe80::1", "port": 1234, "scope_id": 3}))
    for address in [ok(na.inet_address_v4(na.ipv4_loopback, 1234)), scoped]:
        assert na.to_canonical(address) is address
    assert na.to_canonical(scoped.address) is scoped.address


def test_immutable() -> None:
    """constructs immutable address values"""
    inet6 = ok(na.inet_address_v6(v6("::1"), 80, scope_id=2))
    for address, field in [
        (ok(na.inet_address_v4(v4("127.0.0.1"), 80)), "port"),
        (inet6, "scope_id"),
        (mac("00:00:5e:00:53:01"), "packed"),
        (na.unix_path_address("server.sock"), "path"),
    ]:
        with pytest.raises(AttributeError):
            setattr(address, field, 1)


def test_copies_bytes() -> None:
    """copies byte constructor inputs"""
    ipv4_bytes = bytearray([127, 0, 0, 1])
    ipv6_bytes = bytearray(16)
    ipv6_bytes[15] = 1
    ipv4 = na.ipv4_from_bytes_unsafe(ipv4_bytes)
    ipv6 = na.ipv6_from_bytes_unsafe(ipv6_bytes)
    ipv4_hash, ipv6_hash = hash(ipv4), hash(ipv6)
    ipv4_bytes[0] = 1
    ipv6_bytes[15] = 2
    assert na.format_ip(ipv4) == "127.0.0.1"
    assert na.format_ip(ipv6) == "::1"
    assert hash(ipv4) == ipv4_hash
    assert hash(ipv6) == ipv6_hash


def test_checked_operations_error() -> None:
    """returns NetAddressError from checked operations"""
    error = err(na.ip_from_string("localhost"))
    assert isinstance(error, NetAddressError)
    assert error.message == "expected exactly four decimal octets"
    assert error.input == "localhost"


def test_socket_address_from_input() -> None:
    """constructs socket addresses from input"""
    address = inet("127.0.0.1:8080")
    assert ok(na.socket_address_from_input(address)) is address
    fmt = na.format_socket_address
    assert fmt(ok(na.socket_address_from_input("127.0.0.1:3000"))) == "127.0.0.1:3000"
    assert fmt(ok(na.socket_address_from_input("[::1]:3000"))) == "[::1]:3000"
    assert fmt(ok(na.socket_address_from_input({"address": "::1", "port": 8080}))) == "[::1]:8080"
    assert (
        fmt(ok(na.socket_address_from_input({"address": na.ipv4_loopback, "port": 8080})))
        == "127.0.0.1:8080"
    )
    assert fmt(ok(na.socket_address_from_input({"path": "server.sock"}))) == "server.sock"
    err(na.socket_address_from_input({"address": "localhost", "port": 8080}))
    err(na.socket_address_from_input({"address": "127.0.0.1", "port": 65536}))
    err(na.socket_address_from_input("localhost:8080"))
    with pytest.raises(NetAddressError):
        na.socket_address_from_input_unsafe({"address": "localhost", "port": 8080})


def test_bracketed_numeric() -> None:
    """parses and formats bracketed numeric addresses"""
    assert na.format_inet(ok(na.inet_address_from_string("127.0.0.1:8080"))) == "127.0.0.1:8080"
    assert na.format_inet(ok(na.inet_address_from_string("[0:0:0:0:0:0:0:1]:8080"))) == (
        "[::1]:8080"
    )
    assert na.format_inet(ok(na.inet_address_from_ip_string("::1", 8080))) == "[::1]:8080"
    assert na.format_url_host(v6("::1")) == "[::1]"


def test_native_addresses() -> None:
    """constructs frozen native addresses matching checked parsing"""
    for host in ["127.0.0.1", "2001:db8::1", "::ffff:192.0.2.128"]:
        actual = na.inet_address_from_native_unsafe(host, 4567)
        assert actual == ok(na.inet_address_from_ip_string(host, 4567))
        with pytest.raises(AttributeError):
            actual.port = 1  # pyright: ignore[reportAttributeAccessIssue]


def test_native_zones() -> None:
    """resolves native IPv6 zones and rejects unknown interfaces"""
    scope_ids = {"eth0": 7}
    for host in ["fe80::1%7", "fe80::1%eth0"]:
        assert na.inet_address_from_native_unsafe(host, 4567, scope_ids) == inet("[fe80::1%7]:4567")
    with pytest.raises(ValueError, match="unknown IPv6 interface: missing"):
        na.inet_address_from_native_unsafe("fe80::1%missing", 4567, scope_ids)


def test_format_host() -> None:
    """formats separate socket hosts while preserving IPv6 scope"""
    for text, expected in [
        ("127.0.0.1:8080", "127.0.0.1"),
        ("[0:0:0:0:0:0:0:1]:8080", "::1"),
        ("[fe80::1%7]:4567", "fe80::1%7"),
        ("[fe80::1%0]:4567", "fe80::1"),
    ]:
        address = inet(text)
        host = na.format_host(address)
        assert host == expected
        assert ok(na.inet_address_from_host_string(host, address.port)) == address


EN0_EN1: list[tuple[str, list[na.NetworkInterfaceAddress] | None]] = [
    ("en0", [{"family": "IPv6", "scopeid": 7}]),
    ("en1", [{"family": "IPv6", "scopeid": 7}]),
]


def test_format_native_host() -> None:
    """formats native hosts using the supplied platform and interface names"""
    scope_ids = na.scope_ids_from_interfaces(EN0_EN1)
    for platform in ["win32", "linux", "darwin", None]:
        for text, expected in [
            ("127.0.0.1:8080", "127.0.0.1"),
            ("[0:0:0:0:0:0:0:1]:8080", "::1"),
            ("[fe80::1%0]:4567", "fe80::1"),
            ("[fe80::1%7]:4567", "fe80::1%7" if platform == "win32" else "fe80::1%en0"),
            ("[fe80::1%9]:4567", "fe80::1%9"),
        ]:
            address = inet(text)
            host = na.format_native_host(address, scope_ids, platform)
            assert host == expected
            assert ok(na.inet_address_from_host_string(host, address.port, scope_ids)) == address
    address = inet("[fe80::1%7]:4567")
    assert na.format_native_host(address, scope_ids) == "fe80::1%en0"
    assert na.format_native_host(address, {}, "linux") == "fe80::1%7"
    assert na.format_native_host(address, {"eth0": 7}, "linux") == "fe80::1%eth0"


def test_format_multicast_interface() -> None:
    """formats multicast interfaces using the supplied platform and scope map"""
    scope_ids = na.scope_ids_from_interfaces(EN0_EN1)
    for platform in ["win32", "linux", "darwin", None]:
        fmt = na.format_multicast_interface
        assert fmt(na.ipv4_loopback, scope_ids, platform) == "127.0.0.1"
        assert fmt(0, scope_ids, platform) == "::"
        assert fmt(7, scope_ids, platform) == ("::%7" if platform == "win32" else "::%en0")
        assert fmt(9, scope_ids, platform) == "::%9"
    assert na.format_multicast_interface(7, scope_ids) == "::%en0"
    assert na.format_multicast_interface(7, {}, "linux") == "::%7"
    assert na.format_multicast_interface(7, {"eth0": 7}, "linux") == "::%eth0"


def test_named_zones() -> None:
    """resolves named IPv6 zones only through the supplied scope map"""
    for scope_id in [7, 9]:
        address = ok(na.inet_address_from_host_string("fe80::1%en0", 4567, {"en0": scope_id}))
        assert address == inet(f"[fe80::1%{scope_id}]:4567")
    unknown = err(na.inet_address_from_host_string("fe80::1%en0", 4567, {"en1": 7}))
    assert unknown.input == "fe80::1%en0"
    err(na.inet_address_from_host_string("fe80::1%en0", 4567))


def test_scope_id_snapshot() -> None:
    """snapshots the first positive IPv6 scope ID from each interface"""
    link_local: na.NetworkInterfaceAddress = {"family": "IPv6", "scopeid": 7}
    interfaces: dict[str, list[na.NetworkInterfaceAddress] | None] = {
        "en0": [
            {"family": "IPv4", "scopeid": 99},
            {"family": "IPv6"},
            {"family": "IPv6", "scopeid": 0},
            {"family": "IPv6", "scopeid": -1},
            link_local,
            {"family": "IPv6", "scopeid": 9},
        ],
        "en1": None,
        "en2": [
            {"family": "IPv4"},
            {"family": "IPv6", "scopeid": 0},
            {"family": "IPv6", "scopeid": None},
        ],
        "en3": [{"family": "IPv6", "scopeid": 11}],
    }
    scope_ids = na.scope_ids_from_interfaces(interfaces.items())
    link_local["scopeid"] = 12
    assert scope_ids == {"en0": 7, "en3": 11}
    assert na.scope_ids_from_interfaces([]) == {}
    assert na.scope_id_from_interface(interfaces["en0"]) == 12
    assert na.scope_id_from_interface(interfaces["en2"]) is None


def test_throwing_counterparts() -> None:
    """provides throwing counterparts for trusted construction"""
    address = ip("::1")
    assert na.format_ip(address) == "::1"
    assert na.format_inet(na.inet_address_unsafe(address, 8080)) == "[::1]:8080"
    assert na.format_inet(inet("127.0.0.1:8080")) == "127.0.0.1:8080"
    with pytest.raises(NetAddressError):
        ip("localhost")
    with pytest.raises(NetAddressError):
        na.inet_address_unsafe(address, -1)
    with pytest.raises(NetAddressError):
        inet("localhost:8080")


def test_port_boundaries() -> None:
    """checks port boundaries and rejects ambiguous input"""
    for port in [0, 1, 65535]:
        assert ok(na.inet_address_from_string(f"127.0.0.1:{port}")).port == port
    for text in [
        "127.0.0.1:-1",
        "127.0.0.1:65536",
        "127.0.0.1:1.5",
        "127.0.0.1:00",
        "127.0.0.1:080",
        "localhost:80",
        "::1:80",
        "[::1]80",
        "[127.0.0.1]:80",
        "[fe80::1%]:80",
        "[fe80::1%-1]:80",
        "[fe80::1%1.5]:80",
        "[fe80::1%en0]:80",
        "[fe80::1%1%2]:80",
        "[fe80::1%4294967296]:80",
    ]:
        err(na.inet_address_from_string(text))
    assert (
        err(na.inet_address_from_string("127.0.0.1:65536")).message
        == "port must be an integer from 0 through 65535"
    )
    assert (
        err(na.inet_address_from_string("127.0.0.1")).message == "expected host:port or [IPv6]:port"
    )


def test_scope_equality() -> None:
    """preserves IPv6 scope metadata in equality and hashing"""
    address = v6("fe80::1")
    first = ok(na.inet_address_v6(address, 80, scope_id=3))
    second = ok(na.inet_address_v6(address, 80, scope_id=3))
    other = ok(na.inet_address_v6(address, 80, scope_id=4))
    assert first == second
    assert hash(first) == hash(second)
    assert first != other


def test_numeric_scope_round_trip() -> None:
    """round trips numeric IPv6 scope identifiers"""
    scoped = ok(na.inet_address_from_string("[fe80::1%4294967295]:65535"))
    assert isinstance(scoped, na.InetAddressV6)
    assert scoped.scope_id == 0xFFFFFFFF
    assert na.format_inet(scoped) == "[fe80::1%4294967295]:65535"
    assert na.format_inet(ok(na.inet_address_from_string("[fe80::1%0]:80"))) == "[fe80::1]:80"


def test_unix_paths_opaque() -> None:
    """keeps Unix paths opaque"""
    address = na.unix_path_address("./run/../server.sock")
    assert address.path == "./run/../server.sock"
    assert na.format_socket_address(address) == "./run/../server.sock"
    assert address == na.unix_path_address("./run/../server.sock")


def test_scoped_literals() -> None:
    """normalizes scoped IPv6 literals"""
    assert ok(na.scoped_ipv6_literal_from_string("FE80::1%01")) == "fe80::1%1"
    err(na.scoped_ipv6_literal_from_string("fe80::1%4294967296"))
    assert not na.is_scoped_ipv6_literal("FE80::1%eth0")


def test_from_input_strings() -> None:
    """parses strings and returns values unchanged"""
    ipv4, ipv6 = v4("192.0.2.1"), v6("2001:db8::1")
    address = mac("00:11:22:33:44:55")
    socket_address = inet("[2001:db8::1]:443")
    assert ok(na.ip_from_input("192.0.2.1")) == ipv4
    assert ok(na.ipv4_from_input("192.0.2.1")) == ipv4
    assert ok(na.ipv6_from_input("2001:DB8::1")) == ipv6
    assert ok(na.mac_address_from_input("00:11:22:33:44:55")) == address
    assert ok(na.inet_address_from_input("[2001:db8::1]:443")) == socket_address
    assert ok(na.scoped_ipv6_literal_from_input("FE80::1%eth0")) == "fe80::1%eth0"
    assert ok(na.ip_from_input(ipv6)) is ipv6
    assert ok(na.ipv4_from_input(ipv4)) is ipv4
    assert ok(na.ipv6_from_input(ipv6)) is ipv6
    assert ok(na.mac_address_from_input(address)) is address
    assert ok(na.inet_address_from_input(socket_address)) is socket_address
    err(na.ip_from_input("example.com"))
    err(na.ipv4_from_input("2001:db8::1"))
    err(na.ipv6_from_input("192.0.2.1"))
    err(na.mac_address_from_input("00:11:22:33:44"))
    err(na.inet_address_from_input("192.0.2.1"))
    err(na.scoped_ipv6_literal_from_input("fe80::1"))


def test_from_input_parts() -> None:
    """converts octets, segments, bytes, and parts"""
    ipv4, ipv6 = v4("192.0.2.1"), v6("2001:db8::1")
    ipv6_bytes = bytes([0x20, 0x01, 0x0D, 0xB8, *[0] * 11, 1])
    assert ok(na.ip_from_input((192, 0, 2, 1))) == ipv4
    assert ok(na.ip_from_input(bytes([192, 0, 2, 1]))) == ipv4
    assert ok(na.ip_from_input((0x2001, 0xDB8, 0, 0, 0, 0, 0, 1))) == ipv6
    assert ok(na.ip_from_input(ipv6_bytes)) == ipv6
    assert ok(na.ipv4_from_input(bytearray([192, 0, 2, 1]))) == ipv4
    assert ok(na.ipv6_from_input((0x2001, 0xDB8, 0, 0, 0, 0, 0, 1))) == ipv6
    assert ok(na.ipv6_from_input(ipv6_bytes)) == ipv6
    assert ok(na.mac_address_from_input((0, 0x11, 0x22, 0x33, 0x44, 0x55))) == mac(
        "00:11:22:33:44:55"
    )
    assert ok(na.inet_address_from_input({"address": (192, 0, 2, 1), "port": 53})) == inet(
        "192.0.2.1:53"
    )
    assert ok(na.inet_address_from_input({"address": "fe80::1", "port": 80, "scope_id": 3})) == (
        inet("[fe80::1%3]:80")
    )
    assert ok(na.socket_address_from_input({"address": ipv6_bytes, "port": 443})) == inet(
        "[2001:db8::1]:443"
    )
    assert ok(na.inet_address_from_input({"address": "192.0.2.1", "port": 53, "scope_id": 0})) == (
        inet("192.0.2.1:53")
    )
    err(na.ip_from_input(bytes(5)))
    err(na.ip_from_input(cast(Any, (1, 2, 3))))
    err(na.ipv4_from_input((256, 0, 0, 1)))
    err(na.ipv4_from_input(bytes(16)))
    err(na.ipv6_from_input(bytes(4)))
    err(na.ipv6_from_input((0, 0, 0, 0, 0, 0, 0, 0x10000)))
    err(na.mac_address_from_input((0, 0, 0, 0, 0, 256)))
    err(na.inet_address_from_input({"address": "192.0.2.1", "port": 65536}))
    err(na.inet_address_from_input({"address": "192.0.2.1", "port": 53, "scope_id": 1}))


def test_unsafe_variants() -> None:
    """has unsafe variants that throw on failure"""
    address = ip("192.0.2.1")
    assert na.ip_from_input_unsafe(address) is address
    assert na.ip_from_input_unsafe("192.0.2.1") == address
    assert na.mac_address_from_input_unsafe("00:11:22:33:44:55") == mac("00:11:22:33:44:55")
    assert na.inet_address_from_input_unsafe("192.0.2.1:53") == inet("192.0.2.1:53")
    with pytest.raises(NetAddressError):
        na.ip_from_input_unsafe("example.com")
    with pytest.raises(NetAddressError):
        na.mac_address_from_input_unsafe("00:11")
    with pytest.raises(NetAddressError):
        na.inet_address_from_input_unsafe("192.0.2.1")
