"""Ports of Effect's ``net/Host.test.ts``.

Each test's docstring is the Effect test title.

Omitted, with the reason:

- ``decodes and encodes schemas``: ported in ``test_schema_net.py``.
"""

from typing import Any

import pytest

from pyfect.net import host as h
from pyfect.net import net_address as na
from pyfect.net.net_address import NetAddressError
from pyfect.result import Err, Ok, Result


def ok[A](result: Result[A, Any]) -> A:
    assert isinstance(result, Ok), result
    return result.value


def err[E](result: Result[Any, E]) -> E:
    assert isinstance(result, Err), result
    return result.error


def test_normalizes_domain_names() -> None:
    """normalizes domain names"""
    assert ok(h.domain_name_from_string("Example.COM.")) == "example.com."
    assert ok(h.domain_name_from_string("_pg._tcp.DB.internal")) == "_pg._tcp.db.internal"
    assert ok(h.domain_name_from_string("Bücher.Example")) == "xn--bcher-kva.example"


def test_fully_qualified() -> None:
    """makes domain names fully qualified"""
    for text in ["example.com", "example.com.", "."]:
        name = h.to_fully_qualified(h.domain_name_from_string_unsafe(text))
        assert name == (text if text.endswith(".") else f"{text}.")
        assert h.is_fully_qualified(name)


def test_relative() -> None:
    """makes domain names relative"""
    for text, expected in [
        ("example.com.", "example.com"),
        ("example.com", "example.com"),
        (".", "."),
    ]:
        assert h.to_relative(h.domain_name_from_string_unsafe(text)) == expected


def test_rejects_malformed_names() -> None:
    """rejects malformed domain names"""
    for text in ["", "a..b", "-bad.com", "a b.com", "1.2.3.4", f"{'a' * 64}.com"]:
        err(h.domain_name_from_string(text))


def test_parses_hosts() -> None:
    """parses hosts"""
    assert isinstance(ok(h.host_from_string("10.0.0.5")), na.IPv4Address)
    assert ok(h.host_from_string("FE80:0::1%eth0")) == "fe80::1%eth0"
    assert ok(h.host_from_string("DB.internal")) == "db.internal"
    err(h.host_from_string("10.0.0.1%eth0"))


def test_endpoints() -> None:
    """parses and formats endpoints"""
    for text, expected in [
        ("DB.internal:5432", "db.internal:5432"),
        ("[2001:DB8::1]:443", "[2001:db8::1]:443"),
        ("[fe80::1%eth0]:80", "[fe80::1%eth0]:80"),
    ]:
        assert h.format_host_port(ok(h.host_port_from_string(text))) == expected
    for text in ["example.com", "example.com:65536", "::1:80", "[example.com]:80"]:
        err(h.host_port_from_string(text))


def test_endpoint_equality() -> None:
    """implements equality and hashing for endpoints"""
    a = ok(h.host_port_from_string("example.com:80"))
    b = ok(h.host_port_from_string("EXAMPLE.com:80"))
    assert a == b
    assert hash(a) == hash(b)
    assert a != ok(h.host_port_from_string("example.com:81"))


def test_from_input_strings() -> None:
    """parses strings and returns values unchanged"""
    address = ok(na.ip_from_string("192.0.2.1"))
    endpoint = ok(h.host_port_from_string("Example.COM:443"))
    assert ok(h.domain_name_from_input("Example.COM.")) == "example.com."
    assert h.format_host(ok(h.host_from_input("DB.internal"))) == "db.internal"
    assert ok(h.host_from_input("192.0.2.1")) == address
    assert ok(h.host_port_from_input("example.com:443")) == endpoint
    assert ok(h.host_from_input(address)) is address
    assert ok(h.host_port_from_input(endpoint)) is endpoint
    err(h.domain_name_from_input("bad name"))
    err(h.host_from_input("bad name"))
    err(h.host_port_from_input("example.com"))


def test_from_input_parts() -> None:
    """converts IP address inputs and parts"""
    address = ok(na.ip_from_string("192.0.2.1"))
    assert ok(h.host_from_input((192, 0, 2, 1))) == address
    assert ok(h.host_port_from_input({"host": "Example.COM", "port": 443})) == ok(
        h.host_port_from_string("example.com:443")
    )
    assert ok(h.host_port_from_input({"host": bytes([192, 0, 2, 1]), "port": 53})) == ok(
        h.host_port_from_string("192.0.2.1:53")
    )
    err(h.host_from_input(bytes(5)))
    err(h.host_port_from_input({"host": "bad name", "port": 443}))
    err(h.host_port_from_input({"host": "example.com", "port": 65536}))


def test_unsafe_variants() -> None:
    """has unsafe variants that throw on failure"""
    endpoint = h.host_port_from_string_unsafe("example.com:443")
    assert h.domain_name_from_input_unsafe("Example.COM") == "example.com"
    assert h.format_host(h.host_from_input_unsafe("DB.internal")) == "db.internal"
    assert h.host_port_from_input_unsafe(endpoint) is endpoint
    with pytest.raises(NetAddressError):
        h.domain_name_from_input_unsafe("bad name")
    with pytest.raises(NetAddressError):
        h.host_from_input_unsafe("bad name")
    with pytest.raises(NetAddressError):
        h.host_port_from_input_unsafe("example.com")


def test_hosts_file() -> None:
    """reads addresses and aliases"""
    hosts = h.parse_hosts_file(
        "\n".join(
            [
                "127.0.0.1   localhost",
                "::1         localhost ip6-localhost # loopback",
                "# 192.0.2.9 commented.example",
                "192.0.2.1   DB.Example.  db",
                "192.0.2.1   db",
                "fe80::1%eth0 router",
                "not-an-ip   ignored.example",
                "192.0.2.2   bad..name good.example",
                "192.0.2.3",
            ]
        )
    )
    assert {name: [na.format_ip(a) for a in addresses] for name, addresses in hosts.items()} == {
        "localhost": ["127.0.0.1", "::1"],
        "ip6-localhost": ["::1"],
        "db.example": ["192.0.2.1"],
        "db": ["192.0.2.1"],
        "good.example": ["192.0.2.2"],
    }
