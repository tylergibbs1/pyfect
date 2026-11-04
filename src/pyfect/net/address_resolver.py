"""Socket addresses from endpoints (Effect's ``AddressResolver``).

``resolve`` turns a ``host:port`` (text, parts or ``HostPort``) into the
socket addresses to connect to: an IP literal directly, a scoped IPv6
literal with its zone looked up, a domain name through ``Dns``. Socket
addresses pass through, checked against ``family`` when given::

    resolver = yield from AddressResolver()
    addresses = yield from resolver.resolve("localhost:8080", family="IPv4")
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Literal, Never, cast, overload

from pyfect._core import Effect
from pyfect._digits import is_digits
from pyfect.context import Tag
from pyfect.effect import fail, from_result, succeed, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.net._errors import NetAddressError
from pyfect.net.dns import Dns, DnsError, DnsService
from pyfect.net.host import HostPort, HostPortInput, host_port_from_input
from pyfect.net.net_address._inet import (
    InetAddress,
    InetAddressV4,
    InetAddressV6,
    SocketAddress,
    UnixPathAddress,
    inet_address,
    inet_address_from_host_string,
    inet_address_unsafe,
)
from pyfect.net.net_address._ip import IpFamily, family_of, is_link_local

type ScopeIdLookup = Callable[[str], Effect[int | None, NetAddressError]]
"""The scope ID of the network interface named ``name``, or ``None``."""

type ResolveError = DnsError | NetAddressError


def _in_family(
    address: InetAddress, family: IpFamily | None
) -> Effect[tuple[InetAddress, ...], NetAddressError]:
    if family is None or family_of(address.address) == family:
        return succeed((address,))
    return fail(NetAddressError(f"expected an {family} address", address))


@dataclass(frozen=True, slots=True)
class AddressResolverService:
    """Resolves endpoints to socket addresses (a non-empty tuple)."""

    _dns: DnsService
    _scope_id: ScopeIdLookup | None = None

    @overload
    def resolve(
        self, target: InetAddress | HostPortInput, *, family: Literal["IPv4"]
    ) -> Effect[tuple[InetAddressV4, ...], ResolveError]: ...
    @overload
    def resolve(
        self, target: InetAddress | HostPortInput, *, family: Literal["IPv6"]
    ) -> Effect[tuple[InetAddressV6, ...], ResolveError]: ...
    @overload
    def resolve(
        self, target: InetAddress | HostPortInput, *, family: IpFamily | None = None
    ) -> Effect[tuple[InetAddress, ...], ResolveError]: ...
    @overload
    def resolve(
        self, target: SocketAddress | HostPortInput, *, family: IpFamily | None = None
    ) -> Effect[tuple[SocketAddress, ...], ResolveError]: ...
    def resolve(
        self, target: SocketAddress | HostPortInput, *, family: IpFamily | None = None
    ) -> Effect[tuple[SocketAddress, ...], ResolveError]:
        if isinstance(target, UnixPathAddress):
            return succeed((target,))
        if isinstance(target, InetAddressV4 | InetAddressV6):
            return _widen(_in_family(target, family))
        if not isinstance(target, HostPort):
            return from_result(host_port_from_input(target)).flat_map(
                lambda endpoint: self.resolve(endpoint, family=family)
            )
        host, port = target.host, target.port
        if isinstance(host, IPv4Address | IPv6Address) or "%" in host:
            return _widen(self._from_literal(host, port).flat_map(lambda a: _in_family(a, family)))

        def addresses(
            found: tuple[IPv4Address | IPv6Address, ...],
        ) -> Effect[tuple[SocketAddress, ...], ResolveError]:
            # Lookups do not report the scope that a link-local IPv6 address needs.
            usable = tuple(
                inet_address_unsafe(a, port)
                for a in found
                if not (isinstance(a, IPv6Address) and is_link_local(a))
            )
            if usable:
                return succeed(usable)
            return fail(
                NetAddressError(
                    "only link-local IPv6 addresses were found, "
                    "and lookups do not report their scope",
                    host,
                )
            )

        return self._dns.lookup(host, family=family).flat_map(addresses)

    def _from_literal(
        self, host: IPv4Address | IPv6Address | str, port: int
    ) -> Effect[InetAddress, NetAddressError]:
        if isinstance(host, IPv4Address | IPv6Address):
            return from_result(inet_address(host, port))
        zone = host[host.index("%") + 1 :]
        lookup = self._scope_id
        if lookup is None or is_digits(zone):
            return from_result(inet_address_from_host_string(host, port))

        def with_scope(scope_id: int | None) -> Effect[InetAddress, NetAddressError]:
            scopes: Mapping[str, int] | None = None if scope_id is None else {zone: scope_id}
            return from_result(inet_address_from_host_string(host, port, scopes))

        return lookup(zone).flat_map(with_scope)


def _widen[E](
    eff: Effect[tuple[InetAddress, ...], E],
) -> Effect[tuple[SocketAddress, ...], E]:
    return cast(Effect[tuple[SocketAddress, ...], E], eff)


class AddressResolver(Tag[AddressResolverService], key="effect/net/AddressResolver"):
    """The address resolver service."""


def make(dns: DnsService, *, scope_id: ScopeIdLookup | None = None) -> AddressResolverService:
    """A resolver looking names up with ``dns``; ``scope_id`` resolves named
    IPv6 zones (``fe80::1%eth0``), which fail without it."""
    return AddressResolverService(dns, scope_id)


def layer(*, scope_id: ScopeIdLookup | None = None) -> Layer[AddressResolver, Never, Dns]:
    return layer_effect(AddressResolver, Dns().map(lambda dns: make(dns, scope_id=scope_id)))


def system_scope_id(name: str) -> Effect[int | None, NetAddressError]:
    """The scope ID of a network interface of this machine: its index."""

    def find() -> int | None:
        try:
            return socket.if_nametoindex(name)
        except OSError:
            return None

    return sync(find)


def layer_system() -> Layer[AddressResolver, Never, Dns]:
    """A resolver over ``Dns`` resolving IPv6 zones by this machine's
    network interfaces."""
    return layer(scope_id=system_scope_id)


__all__ = [
    "AddressResolver",
    "AddressResolverService",
    "NetAddressError",
    "ResolveError",
    "ScopeIdLookup",
    "layer",
    "layer_system",
    "make",
    "system_scope_id",
]
