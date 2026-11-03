"""Ports of Effect's ``net/Dns.test.ts``.

Each test's docstring is the Effect test title. Records are validated
dataclasses (``dns.Srv(...)``); ``make_record`` builds one as a ``Result``;
``resolve`` takes the record class.

Omitted, with the reason:

- ``encodes and decodes JSON``: ported in ``test_schema_net.py``.
- In ``rejects invalid fields``, ``priority: 1.5``: priorities are typed
  ``int``.

From the platform suite (``Dns.test-utils.ts``), "looks up localhost from
the hosts file" runs against ``layer_system``; its other cases query
records from a CoreDNS container, and the system resolver has no record
queries (``resolve`` fails with ``Unsupported``).
"""

from collections.abc import Sequence
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.effect import fail, succeed
from pyfect.net import dns
from pyfect.net import host as h
from pyfect.net import net_address as na
from pyfect.net.dns import DnsError
from pyfect.result import Err, Ok, Result

ip = na.ip_from_string_unsafe
name = h.domain_name_from_string_unsafe


def srv(target: str, priority: int, weight: int) -> dns.Srv:
    return dns.Srv(name(target), 5432, priority, weight)


def tlsa(data: bytes) -> dns.Tlsa:
    return dns.Tlsa(3, 1, 1, data)


def test_rejects_invalid_fields() -> None:
    """rejects invalid fields"""
    assert isinstance(
        dns.make_record(dns.Srv, target=name("a.b"), port=70000, priority=0, weight=0), Err
    )
    assert isinstance(dns.make_record(dns.Cname, target="not a name"), Err)
    assert isinstance(dns.make_record(dns.A, address=ip("2001:db8::1")), Err)
    assert isinstance(
        dns.make_record(dns.Tlsa, cert_usage=256, selector=1, matching_type=1, data=b"\x01"), Err
    )
    assert isinstance(
        dns.make_record(dns.Tlsa, cert_usage=3, selector=1, matching_type=1, data=b""), Err
    )


def test_copies_tlsa_data() -> None:
    """copies TLSA data"""
    data = bytearray([0xAB, 0xCD])
    record = tlsa(bytes(data))
    data[0] = 0
    assert record.data == bytes([0xAB, 0xCD])


def test_presentation_format() -> None:
    """formats records in presentation format"""
    assert dns.format_record(srv("db.internal", 10, 5)) == "SRV 10 5 5432 db.internal"
    assert dns.format_record(dns.Txt(('a "b"', "ü"))) == 'TXT "a \\"b\\"" "\\195\\188"'
    assert (
        dns.format_record(dns.Ptr("Office Printer._ipp._tcp.local."))
        == "PTR Office\\032Printer._ipp._tcp.local."
    )
    assert dns.format_record(tlsa(bytes([0x0A, 0xBC, 0xDE]))) == "TLSA 3 1 1 0ABCDE"


def test_equality() -> None:
    """implements equality and hashing"""
    a = srv("db.internal", 10, 5)
    assert a == srv("db.internal", 10, 5)
    assert hash(a) == hash(srv("db.internal", 10, 5))
    assert a != srv("db.internal", 10, 6)
    b = tlsa(bytes([1, 2]))
    assert b == tlsa(bytes([1, 2]))
    assert hash(b) == hash(tlsa(bytes([1, 2])))
    assert b != tlsa(bytes([1, 3]))


def test_reverse_names() -> None:
    """builds reverse lookup names"""
    assert dns.reverse_name(ip("192.0.2.1")) == "1.2.0.192.in-addr.arpa"
    assert (
        dns.reverse_name(ip("2001:db8::567:89ab"))
        == "b.a.9.8.7.6.5.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa"
    )


def _normalizing() -> dns.DnsService:
    def lookup(
        host: h.DomainName, _family: na.IpFamily | None
    ) -> fx.Effect[Sequence[na.IpAddress], DnsError]:
        return succeed([ip("10.0.0.1")] if host == "xn--bcher-kva.example." else [])

    def resolve(
        host: h.DomainName, _type: dns.RecordType
    ) -> fx.Effect[Sequence[dns.DnsRecord], DnsError]:
        return succeed([dns.Txt(("normalized",))] if host == "xn--bcher-kva.example." else [])

    return dns.make(lookup, resolve)


@testing.effect
def test_normalizes_lookup():
    """normalizes string inputs before lookup"""
    addresses = yield from _normalizing().lookup("Bücher.Example.")
    assert [na.format_ip(a) for a in addresses] == ["10.0.0.1"]


@testing.effect
def test_normalizes_resolve():
    """normalizes string inputs before resolve"""
    records = yield from _normalizing().resolve("Bücher.Example.", dns.Txt)
    assert [dns.format_record(r) for r in records] == ['TXT "normalized"']


def _valid() -> dns.DnsService:
    return dns.make(
        lambda _h, _f: succeed([ip("10.0.0.1")]),
        lambda _h, _t: succeed([dns.Txt(("valid",))]),
    )


@testing.effect
def test_bad_name_lookup():
    """reports invalid lookup string inputs as BadName"""
    error = yield from _valid().lookup("not a name").flip()
    assert (error.reason, error.method, error.hostname, error.record_type) == (
        "BadName",
        "lookup",
        "not a name",
        None,
    )


@testing.effect
def test_bad_name_resolve():
    """reports invalid resolve string inputs as BadName"""
    error = yield from _valid().resolve("not a name", dns.Txt).flip()
    assert (error.reason, error.method, error.hostname, error.record_type) == (
        "BadName",
        "resolve",
        "not a name",
        "TXT",
    )


@testing.effect
def test_reverse_strings():
    """parses reverse lookup addresses given as strings"""
    seen: list[str] = []

    def reverse(address: na.IpAddress) -> fx.Effect[Sequence[str], DnsError]:
        seen.append(na.format_ip(address))
        return succeed(["host.example."])

    service = dns.make(lambda _h, _f: succeed([]), reverse=reverse)
    assert (yield from service.reverse("2001:DB8::1")) == ("host.example.",)
    assert seen == ["2001:db8::1"]
    error = yield from service.reverse("not an address").flip()
    assert (error.reason, error.method, error.hostname) == ("BadName", "reverse", "not an address")
    assert seen == ["2001:db8::1"]


@testing.effect
def test_filters_and_dedupes():
    """filters and deduplicates results, and fails on empty results"""
    service = dns.make(
        lambda _h, _f: succeed([ip("10.0.0.1"), ip("::1"), ip("10.0.0.1")]),
        lambda _h, _t: succeed([]),
    )
    every = yield from service.lookup("a.b")
    assert [na.format_ip(a) for a in every] == ["10.0.0.1", "::1"]
    v6 = yield from service.lookup("a.b", family="IPv6")
    assert [na.format_ip(a) for a in v6] == ["::1"]
    error = yield from service.resolve("a.b", dns.Mx).flip()
    assert error.reason == "NotFound"


@testing.effect
def test_unsupported_without_resolve():
    """reports record queries as unsupported without a resolve operation"""
    service = dns.make(lambda _h, _f: succeed([ip("10.0.0.1")]))
    addresses = yield from service.lookup("a.b")
    assert [na.format_ip(a) for a in addresses] == ["10.0.0.1"]
    resolve = yield from service.resolve("a.b", dns.Txt).flip()
    assert (resolve.reason, resolve.method, resolve.hostname, resolve.record_type) == (
        "Unsupported",
        "resolve",
        "a.b",
        "TXT",
    )
    reverse = yield from service.reverse(ip("192.0.2.1")).flip()
    assert (reverse.reason, reverse.method, reverse.hostname) == (
        "Unsupported",
        "reverse",
        "192.0.2.1",
    )


@testing.effect
def test_reverse_from_ptr():
    """derives reverse lookups from PTR queries"""

    def resolve(
        hostname: h.DomainName, record_type: dns.RecordType
    ) -> fx.Effect[Sequence[dns.DnsRecord], DnsError]:
        if hostname == "1.2.0.192.in-addr.arpa":
            return succeed([dns.Ptr("web.example.com."), dns.Ptr("not a host.example.com.")])
        return fail(DnsError("ServerFailure", "resolve", hostname, record_type))

    service = dns.make(lambda _h, _f: succeed([]), resolve)
    assert (yield from service.reverse(ip("192.0.2.1"))) == ("web.example.com.",)
    error = yield from service.reverse(ip("192.0.2.2")).flip()
    assert (error.reason, error.method, error.hostname) == ("ServerFailure", "reverse", "192.0.2.2")


@testing.effect
def test_static_zone():
    """answers from a static zone"""

    def body() -> Any:
        service = yield from dns.Dns()
        addresses = yield from service.lookup("DB.internal.")
        assert [na.format_ip(a) for a in addresses] == ["10.0.0.5"]
        records = yield from service.resolve("example.com", dns.Mx)
        assert [dns.format_record(r) for r in records] == ["MX 10 mail.example.com"]
        assert (yield from service.reverse(ip("10.0.0.5"))) == ("db.internal",)
        missing = yield from service.lookup("missing.internal").flip()
        assert missing.reason == "NotFound"

    zone = dns.layer_static(
        hosts={"db.internal": ["10.0.0.5"]},
        records={"example.com": [dns.Mx(name("mail.example.com"), 10)]},
    )
    yield from fx.gen(body).pipe(fx.provide(zone))


@testing.effect
def test_static_inputs():
    """converts static host address inputs"""
    hosts: dict[str, list[na.IpAddressInput]] = {
        "db.internal": ["10.0.0.5", (10, 0, 0, 6), ip("fd00::5")]
    }
    service = dns.make_static(hosts=hosts).get_or_raise()
    addresses = yield from service.lookup("db.internal")
    assert [na.format_ip(a) for a in addresses] == ["10.0.0.5", "10.0.0.6", "fd00::5"]
    invalid = dns.make_static(hosts={"db.internal": ["not-an-ip"]})
    assert isinstance(invalid, Err)
    assert invalid.error.input == "not-an-ip"


def _format(result: Result[na.InetAddress, Any]) -> Result[str, Any]:
    return result.map(na.format_inet)


def test_name_server_from_string() -> None:
    """parses IP addresses with and without a port"""
    assert [
        _format(dns.name_server_from_string(t))
        for t in [
            "192.0.2.53",
            "192.0.2.53:5353",
            "2001:db8::53",
            "[2001:db8::53]:5353",
            "fe80::1%2",
        ]
    ] == [
        Ok("192.0.2.53:53"),
        Ok("192.0.2.53:5353"),
        Ok("[2001:db8::53]:53"),
        Ok("[2001:db8::53]:5353"),
        Ok("[fe80::1%2]:53"),
    ]
    for text in ["ns.example", "ns.example:53", "192.0.2.53:", "[2001:db8::53]", "192.0.2.256", ""]:
        assert isinstance(dns.name_server_from_string(text), Err), text


def test_name_server_from_input() -> None:
    """parses strings, converts address inputs, and uses port 53 for IP addresses"""
    inet = na.inet_address_from_string_unsafe("192.0.2.53:5353")
    inputs: list[Any] = [
        "2001:db8::53",
        ip("192.0.2.53"),
        (192, 0, 2, 53),
        inet,
        {"address": "2001:db8::53", "port": 5353},
    ]
    assert [_format(dns.name_server_from_input(i)) for i in inputs] == [
        Ok("[2001:db8::53]:53"),
        Ok("192.0.2.53:53"),
        Ok("192.0.2.53:53"),
        Ok("192.0.2.53:5353"),
        Ok("[2001:db8::53]:5353"),
    ]
    assert dns.name_server_from_input(inet).get_or_raise() is inet
    for value in ["ns.example", (192, 0, 2), {"address": "ns", "port": 53}]:
        assert isinstance(dns.name_server_from_input(cast(Any, value)), Err), value


@testing.live(timeout=10)
def test_system_looks_up_localhost():
    """looks up localhost from the hosts file"""
    service = dns.make_system()
    addresses = yield from service.lookup(name("localhost"), family="IPv4")
    assert any(na.format_ip(address) == "127.0.0.1" for address in addresses)
