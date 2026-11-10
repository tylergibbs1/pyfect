"""Ports of the schema tests in Effect's ``net/NetAddress.test.ts``,
``net/Host.test.ts``, ``net/IpInterface.test.ts``, ``net/IpNetwork.test.ts``
and ``net/Dns.test.ts`` (the net schemas of ``Schema.ts``).

Each test's docstring is the Effect test title, prefixed with its file.
"""

from ipaddress import IPv4Address
from typing import Never

import pytest

from pyfect import schema as S
from pyfect.duration import millis
from pyfect.net import dns, ip_network
from pyfect.net import host as h
from pyfect.net import net_address as na
from pyfect.schema import SchemaError


def test_validates_ports() -> None:
    """NetAddress: validates ports"""
    assert S.decode_unknown_sync(S.Port)(65535) == 65535
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.Port)(65536)
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.Port)(1.5)


def _round_trip[A](schema: S.Codec[A, str, Never, Never], text: str) -> str:
    return S.encode_sync(schema)(S.decode_unknown_sync(schema)(text))


def test_decodes_and_canonically_encodes_schemas() -> None:
    """NetAddress: decodes and canonically encodes schemas"""
    assert (S.resolve_annotations(S.IpAddress) or {}).get("identifier") == "IpAddress"
    identifier = (S.resolve_annotations(S.IpAddressFromString) or {}).get("identifier")
    assert identifier == "IpAddressFromString"
    assert _round_trip(S.MacAddressFromString, "02:0A:0b:0C:0d:0E") == "02:0a:0b:0c:0d:0e"
    assert _round_trip(S.Ipv6AddressFromString, "2001:0DB8:0:0:0:0:0:1") == "2001:db8::1"
    assert _round_trip(S.InetAddressFromString, "[0:0:0:0:0:0:0:1]:0") == "[::1]:0"
    assert _round_trip(S.InetAddressFromString, "[fe80::1%3]:80") == "[fe80::1%3]:80"
    assert _round_trip(S.UnixPathAddressFromString, "../opaque.sock") == "../opaque.sock"
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.MacAddressFromString)("00-11-22-33-44-55")
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.Ipv4AddressFromString)("999.0.0.1")
    assert _round_trip(S.IpAddressFromString, "2001:DB8::1") == "2001:db8::1"


def test_validates_branded_address_schemas_on_decode_and_encode() -> None:
    """NetAddress: validates branded address schemas on decode and encode"""
    multicast_ip = S.decode_unknown_sync(S.IpMulticastAddressFromString)("239.255.0.1")
    multicast_mac = S.decode_unknown_sync(S.MacMulticastAddressFromString)("01:00:5E:00:00:01")
    broadcast_mac = S.decode_unknown_sync(S.MacBroadcastAddressFromString)("FF:FF:FF:FF:FF:FF")
    assert S.encode_sync(S.IpMulticastAddressFromString)(multicast_ip) == "239.255.0.1"
    assert S.encode_sync(S.MacMulticastAddressFromString)(multicast_mac) == "01:00:5e:00:00:01"
    assert na.is_multicast(multicast_ip)
    assert na.is_multicast(multicast_mac)
    assert na.is_multicast(broadcast_mac)

    assert na.is_unicast(S.decode_unknown_sync(S.IpUnicastAddressFromString)("192.0.2.1"))
    mac = S.decode_unknown_sync(S.MacUnicastAddressFromString)("00:00:5e:00:53:01")
    assert na.is_mac_unicast(mac)
    ipv4 = S.decode_unknown_sync(S.Ipv4BroadcastAddressFromString)("255.255.255.255")
    assert na.is_broadcast(ipv4)
    assert na.is_loopback(S.decode_unknown_sync(S.IpLoopbackAddressFromString)("::1"))
    assert na.is_link_local(S.decode_unknown_sync(S.IpLinkLocalAddressFromString)("fe80::1"))
    assert na.is_unspecified(S.decode_unknown_sync(S.IpUnspecifiedAddressFromString)("::"))
    assert na.is_private(S.decode_unknown_sync(S.Ipv4PrivateAddressFromString)("10.0.0.1"))
    assert na.is_unique_local(S.decode_unknown_sync(S.Ipv6UniqueLocalAddressFromString)("fd00::1"))
    local = S.decode_unknown_sync(S.MacLocallyAdministeredAddressFromString)("02:00:00:00:00:01")
    assert na.is_mac_locally_administered(local)
    universal = S.decode_unknown_sync(S.MacUniversallyAdministeredAddressFromString)(
        "00:00:5e:00:53:01"
    )
    assert na.is_mac_universally_administered(universal)

    loopback = na.ipv4_loopback
    assert S.decode_unknown_sync(S.IpLoopbackAddress)(loopback) is loopback
    assert S.is_(S.IpLoopbackAddress)(loopback)
    assert not S.is_(S.IpMulticastAddress)(loopback)
    with pytest.raises(SchemaError, match="Expected a multicast address"):
        S.decode_unknown_sync(S.IpMulticastAddressFromString)("127.0.0.1")
    with pytest.raises(SchemaError, match="expected exactly four decimal octets"):
        S.decode_unknown_sync(S.IpMulticastAddressFromString)("localhost")
    with pytest.raises(SchemaError, match="Expected a multicast address"):
        S.encode_unknown_sync(S.IpMulticastAddressFromString)(loopback)


def test_host_decodes_and_encodes_schemas() -> None:
    """Host: decodes and encodes schemas"""
    assert _round_trip(S.HostFromString, "2001:DB8::1") == "2001:db8::1"
    assert _round_trip(S.HostPortFromString, "DB.internal:5432") == "db.internal:5432"
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.Host)("DB.internal")


def test_ip_interface_decodes_and_canonically_encodes_schemas() -> None:
    """IpInterface: decodes and canonically encodes schemas"""
    assert _round_trip(S.IpInterfaceFromString, "192.0.2.1/24") == "192.0.2.1/24"


def test_decodes_declarations_and_canonically_encodes_schema_strings() -> None:
    """IpNetwork: decodes declarations and canonically encodes Schema strings"""
    text = "2001:0DB8:0000:0000:0000:0000:0000:0000/32"
    assert _round_trip(S.Ipv6NetworkFromString, text) == "2001:db8::/32"
    network = S.decode_unknown_sync(S.IpNetworkFromString)("192.0.2.0/24")
    assert ip_network.format(network) == "192.0.2.0/24"
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.IpNetworkFromString)("192.0.2.1/24")
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(S.IpNetwork)(
            {"_tag": "IpNetwork", "address": IPv4Address("192.0.2.0"), "prefixLength": 24}
        )


def test_encodes_and_decodes_json() -> None:
    """Dns: encodes and decodes JSON"""
    codec = S.to_codec_json(S.DnsRecord)
    soa = dns.Soa(
        primary=h.domain_name_from_string_unsafe("ns.example.com"),
        admin="hostmaster.example.com",
        serial=1,
        refresh=millis(3_600_000),
        retry=millis(600_000),
        expire=millis(604_800_000),
        minimum=millis(300_000),
    )
    json = {
        "_tag": "SOA",
        "primary": "ns.example.com",
        "admin": "hostmaster.example.com",
        "serial": 1,
        "refresh": 3600,
        "retry": 600,
        "expire": 604800,
        "minimum": 300,
    }
    assert S.encode_sync(codec)(soa) == json
    assert S.decode_unknown_sync(codec)(json) == soa
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(codec)({"_tag": "CNAME", "target": "Example.com"})
    record = dns.Tlsa(cert_usage=3, selector=1, matching_type=1, data=bytes([0x0A, 0xBC]))
    tlsa_json = {"_tag": "TLSA", "certUsage": 3, "selector": 1, "matchingType": 1, "data": "0abc"}
    assert S.encode_sync(codec)(record) == tlsa_json
    assert S.decode_unknown_sync(codec)(tlsa_json) == record
    with pytest.raises(SchemaError):
        S.decode_unknown_sync(codec)({**tlsa_json, "data": ""})


def test_a_caa_tag_is_checked_by_its_json_pattern() -> None:
    """Review: Effect's ``DnsCaaRecord`` JSON checks ``tag`` with
    ``isPattern(/^[a-z0-9]+$/i)``, so a bad tag fails at the key, before the
    record is made (message printed by Effect under Node)."""
    codec = S.to_codec_json(S.DnsRecord)
    with pytest.raises(SchemaError) as error:
        S.decode_unknown_sync(codec)(
            {"_tag": "CAA", "critical": False, "tag": "is-sue", "value": "x"}
        )
    assert str(error.value) == 'Expected a string matching the RegExp ^[a-z0-9]+$\n  at ["tag"]'
