"""The DNS service (Effect's ``Dns``): built from a lookup, and optionally a
record resolver and reverse lookup, by ``make``; or from a fixed zone by
``make_static``."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Literal, overload

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import fail, from_result, succeed, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.net._errors import NetAddressError
from pyfect.net.dns._error import DnsError, DnsMethod
from pyfect.net.dns._records import (
    A,
    Aaaa,
    DnsRecord,
    Ptr,
    RecordType,
    record_classes,
    reverse_name,
)
from pyfect.net.host import DomainName, DomainNameInput, domain_name_from_input, to_relative
from pyfect.net.net_address._inet import (
    InetAddress,
    InetAddressInput,
    InetAddressV4,
    InetAddressV6,
    inet_address_from_input,
    inet_address_unsafe,
)
from pyfect.net.net_address._inet import inet_address_from_string as parse_inet
from pyfect.net.net_address._ip import (
    IpAddress,
    IpAddressInput,
    IpFamily,
    family_of,
    format_ip,
    ip_from_input,
)
from pyfect.result import Err, Ok, Result

type Lookup = Callable[[DomainName, IpFamily | None], Effect[Sequence[IpAddress], DnsError]]
type Resolve = Callable[[DomainName, RecordType], Effect[Sequence[DnsRecord], DnsError]]
type Reverse = Callable[[IpAddress], Effect[Sequence[str], DnsError]]

_ASCII_NAME = re.compile(r"[\w.-]+", re.ASCII)
_HOST_PORT = re.compile(r"[^:]*:[0-9]+")


def _dedupe[A](values: Iterable[A]) -> tuple[A, ...]:
    return tuple(dict.fromkeys(values))


def _not_found(method: DnsMethod, hostname: str, record_type: RecordType | None = None) -> DnsError:
    return DnsError("NotFound", method, hostname, record_type)


@dataclass(frozen=True, slots=True)
class DnsService:
    """Host lookups, record queries and reverse lookups. Every result is
    non-empty and without duplicates; an empty answer fails with
    ``NotFound``, a name that does not parse with ``BadName``."""

    _lookup: Lookup
    _resolve: Resolve
    _reverse: Reverse

    @overload
    def lookup(
        self, host: DomainNameInput, *, family: Literal["IPv4"]
    ) -> Effect[tuple[IPv4Address, ...], DnsError]: ...
    @overload
    def lookup(
        self, host: DomainNameInput, *, family: Literal["IPv6"]
    ) -> Effect[tuple[IPv6Address, ...], DnsError]: ...
    @overload
    def lookup(
        self, host: DomainNameInput, *, family: IpFamily | None = None
    ) -> Effect[tuple[IpAddress, ...], DnsError]: ...
    def lookup(
        self, host: DomainNameInput, *, family: IpFamily | None = None
    ) -> Effect[tuple[IpAddress, ...], DnsError]:
        """The addresses of ``host``, of ``family`` when given."""
        match domain_name_from_input(host):
            case Err(error):
                return fail(DnsError("BadName", "lookup", host, cause=error))
            case Ok(name):
                pass

        def found(addresses: Sequence[IpAddress]) -> Effect[tuple[IpAddress, ...], DnsError]:
            kept = _dedupe(a for a in addresses if family is None or family_of(a) == family)
            return succeed(kept) if kept else fail(_not_found("lookup", name))

        return self._lookup(name, family).flat_map(found)

    def resolve[R: DnsRecord](
        self, name: DomainNameInput, record_type: type[R]
    ) -> Effect[tuple[R, ...], DnsError]:
        """The records of ``record_type`` (a record class: ``dns.Mx``) at
        ``name``."""
        tag = record_type.tag
        match domain_name_from_input(name):
            case Err(error):
                return fail(DnsError("BadName", "resolve", name, tag, error))
            case Ok(domain):
                pass

        def found(records: Sequence[DnsRecord]) -> Effect[tuple[R, ...], DnsError]:
            kept = _dedupe(r for r in records if isinstance(r, record_type))
            return succeed(kept) if kept else fail(_not_found("resolve", domain, tag))

        return self._resolve(domain, tag).flat_map(found)

    def reverse(self, address: IpAddressInput) -> Effect[tuple[DomainName, ...], DnsError]:
        """The names of ``address``; only ASCII names are kept (a UTF-8 name
        would become a different ``xn--`` name)."""
        match ip_from_input(address):
            case Err(error):
                return fail(DnsError("BadName", "reverse", str(address), cause=error))
            case Ok(ip):
                pass
        hostname = format_ip(ip)

        def found(names: Sequence[str]) -> Effect[tuple[DomainName, ...], DnsError]:
            hosts = _dedupe(
                parsed.value
                for name in names
                if _ASCII_NAME.fullmatch(name)
                for parsed in (domain_name_from_input(name),)
                if isinstance(parsed, Ok)
            )
            if hosts:
                return succeed(hosts)
            if names:
                return fail(DnsError("InvalidResponse", "reverse", hostname))
            return fail(_not_found("reverse", hostname))

        return self._reverse(ip).flat_map(found)


class Dns(Tag[DnsService], key="effect/net/Dns"):
    """The DNS service."""


def make(
    lookup: Lookup, resolve: Resolve | None = None, reverse: Reverse | None = None
) -> DnsService:
    """A DNS service from its primitives. Without ``resolve``, record
    queries fail with ``Unsupported``; without ``reverse``, reverse lookups
    query PTR records."""

    def unsupported(
        name: DomainName, record_type: RecordType
    ) -> Effect[Sequence[DnsRecord], DnsError]:
        return fail(DnsError("Unsupported", "resolve", name, record_type))

    resolve_records = resolve or unsupported

    def reverse_by_ptr(address: IpAddress) -> Effect[Sequence[str], DnsError]:
        def rename(error: DnsError) -> DnsError:
            return DnsError(error.reason, "reverse", format_ip(address), cause=error.cause)

        return (
            resolve_records(reverse_name(address), "PTR")
            .map(lambda records: [r.host for r in records if isinstance(r, Ptr)])
            .map_error(rename)
        )

    return DnsService(lookup, resolve_records, reverse or reverse_by_ptr)


def _zone_key(name: str) -> str:
    return to_relative(DomainName(name))


@dataclass(slots=True)
class _Entry:
    addresses: list[IpAddress]
    records: list[DnsRecord]


def make_static(
    hosts: Mapping[str, Sequence[IpAddressInput]] | None = None,
    records: Mapping[str, Sequence[DnsRecord]] | None = None,
) -> Result[DnsService, NetAddressError]:
    """A DNS service answering from a fixed zone: addresses by host name,
    records by name."""
    entries: dict[str, _Entry] = {}

    def entry(name: str) -> Result[_Entry, NetAddressError]:
        return domain_name_from_input(name).map(
            lambda domain: entries.setdefault(_zone_key(domain), _Entry([], []))
        )

    for name, inputs in (hosts or {}).items():
        match entry(name):
            case Err() as error:
                return error
            case Ok(current):
                for value in inputs:
                    match ip_from_input(value):
                        case Err() as error:
                            return error
                        case Ok(address):
                            current.addresses.append(address)
    for name, values in (records or {}).items():
        match entry(name):
            case Err() as error:
                return error
            case Ok(current):
                for record in values:
                    if not isinstance(record, record_classes):
                        return Err(NetAddressError("expected a DNS record", record))
                    current.records.append(record)

    def records_at(name: str) -> list[DnsRecord]:
        found = entries.get(_zone_key(name))
        return [] if found is None else found.records

    def lookup(host: DomainName, _family: IpFamily | None) -> Effect[Sequence[IpAddress], DnsError]:
        def answer() -> Sequence[IpAddress]:
            found = entries.get(_zone_key(host))
            direct = [] if found is None else found.addresses
            return [*direct, *(r.address for r in records_at(host) if isinstance(r, (A, Aaaa)))]

        return sync(answer)

    def resolve(name: DomainName, _type: RecordType) -> Effect[Sequence[DnsRecord], DnsError]:
        return sync(lambda: records_at(name))

    def reverse(address: IpAddress) -> Effect[Sequence[str], DnsError]:
        def answer() -> Sequence[str]:
            named = [name for name, current in entries.items() if address in current.addresses]
            pointed = [r.host for r in records_at(reverse_name(address)) if isinstance(r, Ptr)]
            return [*named, *pointed]

        return sync(answer)

    return Ok(make(lookup, resolve, reverse))


def layer_static(
    hosts: Mapping[str, Sequence[IpAddressInput]] | None = None,
    records: Mapping[str, Sequence[DnsRecord]] | None = None,
) -> Layer[Dns, NetAddressError]:
    """A ``Dns`` layer answering from a fixed zone."""
    return layer_effect(Dns, from_result(make_static(hosts, records)))


def name_server_from_string(text: str) -> Result[InetAddress, NetAddressError]:
    """A name server address; port 53 unless given."""
    if text.startswith("[") or _HOST_PORT.fullmatch(text):
        return parse_inet(text)
    return parse_inet(f"[{text}]:53" if ":" in text else f"{text}:53")


def name_server_from_input(
    value: IpAddressInput | InetAddressInput,
) -> Result[InetAddress, NetAddressError]:
    """A name server address from text, parts with a port, or an IP address
    (port 53)."""
    if isinstance(value, str):
        return name_server_from_string(value)
    if isinstance(value, (Mapping, InetAddressV4, InetAddressV6)):
        return inet_address_from_input(value)
    return ip_from_input(value).map(lambda address: inet_address_unsafe(address, 53))


__all__ = [
    "Dns",
    "DnsService",
    "Lookup",
    "Resolve",
    "Reverse",
    "layer_static",
    "make",
    "make_static",
    "name_server_from_input",
    "name_server_from_string",
]
