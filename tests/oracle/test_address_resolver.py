"""Ports of Effect's ``net/AddressResolver.test.ts`` and of the platform
resolver tests (``AddressResolver.test-utils.ts``, run by
``NodeAddressResolver.test.ts``) against ``layer_system`` over the system
``Dns``.

Each test's docstring is the Effect test title.
"""

import socket
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.effect import succeed
from pyfect.net import address_resolver as ar
from pyfect.net import dns
from pyfect.net import host as h
from pyfect.net import net_address as na
from pyfect.net.address_resolver import AddressResolverService
from pyfect.net.net_address import NetAddressError

ZONE = dns.make_static(
    hosts={"db.internal": ["10.0.0.5", "fd00::5"], "printer.local": ["fe80::1", "169.254.0.7"]}
).get_or_raise()


def resolver(scope_id: ar.ScopeIdLookup | None = None) -> AddressResolverService:
    return ar.make(ZONE, scope_id=scope_id)


def formatted(addresses: tuple[na.SocketAddress, ...]) -> list[str]:
    return [na.format_socket_address(a) for a in addresses]


@testing.effect
def test_string_endpoints():
    """parses string endpoints and normalizes domain names"""
    addresses = yield from resolver().resolve("DB.internal.:5432", family="IPv4")
    assert formatted(addresses) == ["10.0.0.5:5432"]
    scoped = yield from resolver().resolve("[fe80::1%2]:80")
    assert formatted(scoped) == ["[fe80::1%2]:80"]


@testing.effect
def test_host_port_objects():
    """converts host and port objects"""
    addresses = yield from resolver().resolve({"host": "DB.internal", "port": 5432}, family="IPv4")
    assert formatted(addresses) == ["10.0.0.5:5432"]
    numeric = yield from resolver().resolve({"host": (10, 0, 0, 1), "port": 80})
    assert formatted(numeric) == ["10.0.0.1:80"]
    error = yield from resolver().resolve({"host": "db.internal", "port": 70000}).flip()
    assert isinstance(error, NetAddressError)


@testing.effect
def test_invalid_string_endpoints():
    """reports invalid string endpoints as NetAddressError"""
    error = yield from resolver().resolve("db.internal:70000").flip()
    assert isinstance(error, NetAddressError)


@testing.effect
def test_concrete_addresses():
    """returns concrete addresses without a lookup"""
    inet = na.inet_address_from_string_unsafe("10.0.0.1:80")
    assert (yield from resolver().resolve(inet)) == (inet,)
    unix = na.unix_path_address("/run/app.sock")
    assert (yield from resolver().resolve(unix)) == (unix,)
    error = yield from resolver().resolve(inet, family="IPv6").flip()
    assert isinstance(error, NetAddressError)


@testing.effect
def test_looks_up_names():
    """looks up domain names and attaches the port"""
    every = yield from resolver().resolve("db.internal:5432")
    assert formatted(every) == ["10.0.0.5:5432", "[fd00::5]:5432"]
    v4 = yield from resolver().resolve("db.internal:5432", family="IPv4")
    assert formatted(v4) == ["10.0.0.5:5432"]


@testing.effect
def test_skips_link_local():
    """skips looked-up IPv6 link-local addresses, which have no scope"""
    addresses = yield from resolver().resolve("printer.local:631")
    assert formatted(addresses) == ["169.254.0.7:631"]


@testing.effect
def test_named_zones():
    """resolves named IPv6 zones with the scope ID lookup"""
    with_lookup = resolver(lambda name: succeed(2 if name == "eth0" else None))
    named = yield from with_lookup.resolve("[fe80::1%eth0]:80")
    assert formatted(named) == ["[fe80::1%2]:80"]
    unknown = yield from with_lookup.resolve("[fe80::1%wlan0]:80").flip()
    assert isinstance(unknown, NetAddressError)
    error = yield from resolver().resolve("[fe80::1%eth0]:80").flip()
    assert isinstance(error, NetAddressError)


SYSTEM = ar.layer_system().pipe(fx.provide(dns.layer_system()))


@testing.live(timeout=10)
def test_system_hosts_file():
    """looks up domain names from the hosts file"""

    def body() -> Any:
        service = yield from ar.AddressResolver()
        addresses = yield from service.resolve(
            h.host_port_from_string_unsafe("localhost:8080"), family="IPv4"
        )
        assert "127.0.0.1:8080" in formatted(addresses)

    yield from fx.gen(body).pipe(fx.provide(SYSTEM))


@testing.live(timeout=10)
def test_system_zones():
    """resolves IPv6 zones from the network interfaces"""

    def body() -> Any:
        service = yield from ar.AddressResolver()
        interfaces = socket.if_nameindex()
        if interfaces:
            index, zone = interfaces[0]
            addresses = yield from service.resolve(
                h.host_port_from_string_unsafe(f"[fe80::1%{zone}]:80")
            )
            assert formatted(addresses) == [f"[fe80::1%{index}]:80"]
        unknown = yield from service.resolve(
            h.host_port_from_string_unsafe("[fe80::1%nonexistent0]:80")
        ).flip()
        assert isinstance(unknown, NetAddressError)

    yield from fx.gen(body).pipe(fx.provide(SYSTEM))
