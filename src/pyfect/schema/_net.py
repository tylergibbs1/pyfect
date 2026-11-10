"""Schemas of network values (Effect's ``NetAddress``, ``IpInterface``,
``IpNetwork``, ``Host`` and ``Dns`` schemas), over ``pyfect.net``.

Each value has a declaration (``S.Ipv4Address`` takes an ``IPv4Address``)
and a ``...FromString`` codec reading it from text and writing its
canonical text (``"2001:0DB8::1"`` decodes, ``"2001:db8::1"`` is written).
A text the parser rejects is an issue with the parser's message. The
refinements (``S.IpMulticastAddress``, ...) narrow a declaration or codec
by one of ``net_address``'s classifications. The DNS record schemas are
declarations written in JSON as Effect writes them: a ``_tag`` and the
record's fields under Effect's (camelCase) keys.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import fields
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from types import ModuleType as _strategies_module
from typing import Any, TypeIs, cast

from pyfect.duration import Duration
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.net import dns, host, ip_interface, ip_network
from pyfect.net import net_address as na
from pyfect.net._errors import NetAddressError
from pyfect.result import Ok, Result
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._arrays import NonEmptyArray
from pyfect.schema._checks_number import int_value, is_between
from pyfect.schema._checks_string import is_pattern
from pyfect.schema._codec_links import link
from pyfect.schema._codecs import BytesFromHex
from pyfect.schema._declare import declare
from pyfect.schema._literals import Literals, LiteralsSchema, Union
from pyfect.schema._options import ParseOptions
from pyfect.schema._parsed_text import parsed_text
from pyfect.schema._primitives import Boolean, Int, NonEmptyString, String
from pyfect.schema._refine import refine
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema.ast import make_filter
from pyfect.schema.issue import InvalidValue, Issue, reported


def _is[A](cls: type[A] | tuple[type[A], ...]) -> Callable[[object], TypeIs[A]]:
    def guard(value: object) -> TypeIs[A]:
        return isinstance(value, cls)

    return guard


type _Draw = Callable[[_strategies_module], Callable[[tuple[Any, ...]], Any]]


def _declaration[A](cls: type[A] | tuple[type[A], ...], identifier: str, draw: _Draw) -> Bottom[A]:
    """The declaration of ``cls`` values, drawn by ``draw`` of
    ``schema/_strategy/_net.py`` (imported when a strategy is first made)."""

    def to_arbitrary(parameters: tuple[Any, ...]) -> Any:
        from pyfect.schema._strategy import _net as strategies

        return draw(strategies)(parameters)

    return declare(_is(cls), identifier=identifier, to_arbitrary=to_arbitrary)


def from_string[A](
    declaration: Codec[A, Any, Any, Any],
    parse: Callable[[str], Result[A, NetAddressError]],
    format: Callable[[A], str],
    identifier: str,
) -> DecodeToSchema[A, str]:
    """``declaration``'s values read with ``parse`` and written with
    ``format`` (Effect's ``netAddressFromString``)."""
    transformation = parsed_text(parse, format)
    return String.pipe(decode_to(declaration, transformation)).annotate(identifier=identifier)


def _refinement[A, E](
    schema: Codec[A, E, Any, Any], guard: Callable[[A], bool], expected: str, identifier: str
) -> Bottom[A, E]:
    def narrow(value: A) -> TypeIs[A]:
        return guard(value)

    def to_arbitrary(_parameters: tuple[Any, ...]) -> Any:
        # Half the draws are the special addresses ``guard`` accepts, so a refinement
        # that holds for few values (a broadcast address holds for one) still finds them.
        from pyfect.schema._strategy import _net as strategies
        from pyfect.schema._to_strategy import to_strategy

        accepted = [a for a in strategies.SPECIAL if _accepts(guard, a)]
        drawn = to_strategy(schema)
        return (
            strategies.st.one_of(strategies.st.sampled_from(accepted), drawn) if accepted else drawn
        )

    refined = schema.__codec__().pipe(refine(narrow, expected=expected))
    return refined.annotate(identifier=identifier, to_arbitrary=to_arbitrary)


def _accepts[A](guard: Callable[[A], bool], value: object) -> bool:
    try:
        return guard(cast("A", value))
    except (TypeError, AttributeError, ValueError):
        return False


# ------------------------------------------------------------------ addresses

MacAddress: Bottom[na.MacAddress] = _declaration(
    na.MacAddress, "MacAddress", lambda m: m.mac_addresses
)
"""A ``net_address.MacAddress``."""
MacAddressFromString = from_string(
    MacAddress, na.mac_address_from_string, na.format_mac_address, "MacAddressFromString"
)
Ipv4Address: Bottom[IPv4Address] = _declaration(
    IPv4Address, "Ipv4Address", lambda m: m.ipv4_addresses
)
"""An ``ipaddress.IPv4Address``."""
Ipv4AddressFromString = from_string(
    Ipv4Address, na.ipv4_from_string, na.format_ip, "Ipv4AddressFromString"
)
Ipv6Address: Bottom[IPv6Address] = _declaration(
    IPv6Address, "Ipv6Address", lambda m: m.ipv6_addresses
)
"""An ``ipaddress.IPv6Address``."""
Ipv6AddressFromString = from_string(
    Ipv6Address, na.ipv6_from_string, na.format_ip, "Ipv6AddressFromString"
)
IpAddress: Bottom[na.IpAddress] = _declaration(
    (IPv4Address, IPv6Address), "IpAddress", lambda m: m.ip_addresses
)
"""An IPv4 or IPv6 address."""
IpAddressFromString = from_string(IpAddress, na.ip_from_string, na.format_ip, "IpAddressFromString")

_MULTICAST = "a multicast address"
_UNICAST = "a unicast address"
_BROADCAST = "a broadcast address"

IpMulticastAddress = _refinement(IpAddress, na.is_multicast, _MULTICAST, "IpMulticastAddress")
IpMulticastAddressFromString = _refinement(
    IpAddressFromString, na.is_multicast, _MULTICAST, "IpMulticastAddressFromString"
)
MacMulticastAddress = _refinement(MacAddress, na.is_multicast, _MULTICAST, "MacMulticastAddress")
MacMulticastAddressFromString = _refinement(
    MacAddressFromString, na.is_multicast, _MULTICAST, "MacMulticastAddressFromString"
)
IpUnicastAddress = _refinement(IpAddress, na.is_unicast, _UNICAST, "IpUnicastAddress")
IpUnicastAddressFromString = _refinement(
    IpAddressFromString, na.is_unicast, _UNICAST, "IpUnicastAddressFromString"
)
MacUnicastAddress = _refinement(MacAddress, na.is_mac_unicast, _UNICAST, "MacUnicastAddress")
MacUnicastAddressFromString = _refinement(
    MacAddressFromString, na.is_mac_unicast, _UNICAST, "MacUnicastAddressFromString"
)
Ipv4BroadcastAddress = _refinement(Ipv4Address, na.is_broadcast, _BROADCAST, "Ipv4BroadcastAddress")
Ipv4BroadcastAddressFromString = _refinement(
    Ipv4AddressFromString, na.is_broadcast, _BROADCAST, "Ipv4BroadcastAddressFromString"
)
MacBroadcastAddress = _refinement(
    MacAddress, na.is_mac_broadcast, _BROADCAST, "MacBroadcastAddress"
)
MacBroadcastAddressFromString = _refinement(
    MacAddressFromString, na.is_mac_broadcast, _BROADCAST, "MacBroadcastAddressFromString"
)
IpLoopbackAddress = _refinement(
    IpAddress, na.is_loopback, "a loopback address", "IpLoopbackAddress"
)
IpLoopbackAddressFromString = _refinement(
    IpAddressFromString, na.is_loopback, "a loopback address", "IpLoopbackAddressFromString"
)
IpLinkLocalAddress = _refinement(
    IpAddress, na.is_link_local, "a link-local address", "IpLinkLocalAddress"
)
IpLinkLocalAddressFromString = _refinement(
    IpAddressFromString, na.is_link_local, "a link-local address", "IpLinkLocalAddressFromString"
)
IpUnspecifiedAddress = _refinement(
    IpAddress, na.is_unspecified, "an unspecified address", "IpUnspecifiedAddress"
)
IpUnspecifiedAddressFromString = _refinement(
    IpAddressFromString,
    na.is_unspecified,
    "an unspecified address",
    "IpUnspecifiedAddressFromString",
)
Ipv4PrivateAddress = _refinement(
    Ipv4Address, na.is_private, "a private address", "Ipv4PrivateAddress"
)
Ipv4PrivateAddressFromString = _refinement(
    Ipv4AddressFromString, na.is_private, "a private address", "Ipv4PrivateAddressFromString"
)
Ipv6UniqueLocalAddress = _refinement(
    Ipv6Address, na.is_unique_local, "a unique-local address", "Ipv6UniqueLocalAddress"
)
Ipv6UniqueLocalAddressFromString = _refinement(
    Ipv6AddressFromString,
    na.is_unique_local,
    "a unique-local address",
    "Ipv6UniqueLocalAddressFromString",
)
_LOCAL = "a locally administered address"
_UNIVERSAL = "a universally administered address"
MacLocallyAdministeredAddress = _refinement(
    MacAddress, na.is_mac_locally_administered, _LOCAL, "MacLocallyAdministeredAddress"
)
MacLocallyAdministeredAddressFromString = _refinement(
    MacAddressFromString,
    na.is_mac_locally_administered,
    _LOCAL,
    "MacLocallyAdministeredAddressFromString",
)
MacUniversallyAdministeredAddress = _refinement(
    MacAddress, na.is_mac_universally_administered, _UNIVERSAL, "MacUniversallyAdministeredAddress"
)
MacUniversallyAdministeredAddressFromString = _refinement(
    MacAddressFromString,
    na.is_mac_universally_administered,
    _UNIVERSAL,
    "MacUniversallyAdministeredAddressFromString",
)

# --------------------------------------------------------- interfaces, networks

Ipv4Interface: Bottom[IPv4Interface] = _declaration(
    IPv4Interface, "Ipv4Interface", lambda m: m.ipv4_interfaces
)
Ipv4InterfaceFromString = from_string(
    Ipv4Interface, ip_interface.ipv4_from_string, ip_interface.format, "Ipv4InterfaceFromString"
)
Ipv6Interface: Bottom[IPv6Interface] = _declaration(
    IPv6Interface, "Ipv6Interface", lambda m: m.ipv6_interfaces
)
Ipv6InterfaceFromString = from_string(
    Ipv6Interface, ip_interface.ipv6_from_string, ip_interface.format, "Ipv6InterfaceFromString"
)
IpInterface: Bottom[ip_interface.IpInterface] = _declaration(
    (IPv4Interface, IPv6Interface), "IpInterface", lambda m: m.ip_interfaces
)
IpInterfaceFromString = from_string(
    IpInterface, ip_interface.from_string, ip_interface.format, "IpInterfaceFromString"
)
Ipv4Network: Bottom[IPv4Network] = _declaration(
    IPv4Network, "Ipv4Network", lambda m: m.ipv4_networks
)
Ipv4NetworkFromString = from_string(
    Ipv4Network, ip_network.ipv4_from_string, ip_network.format, "Ipv4NetworkFromString"
)
Ipv6Network: Bottom[IPv6Network] = _declaration(
    IPv6Network, "Ipv6Network", lambda m: m.ipv6_networks
)
Ipv6NetworkFromString = from_string(
    Ipv6Network, ip_network.ipv6_from_string, ip_network.format, "Ipv6NetworkFromString"
)
IpNetwork: Bottom[ip_network.IpNetwork] = _declaration(
    (IPv4Network, IPv6Network), "IpNetwork", lambda m: m.ip_networks
)
IpNetworkFromString = from_string(
    IpNetwork, ip_network.from_string, ip_network.format, "IpNetworkFromString"
)

# ----------------------------------------------------------- socket addresses

InetAddressV4: Bottom[na.InetAddressV4] = _declaration(
    na.InetAddressV4, "InetAddressV4", lambda m: m.inet_v4
)
InetAddressV6: Bottom[na.InetAddressV6] = _declaration(
    na.InetAddressV6, "InetAddressV6", lambda m: m.inet_v6
)
InetAddress: Bottom[na.InetAddress] = _declaration(
    (na.InetAddressV4, na.InetAddressV6), "InetAddress", lambda m: m.inet
)
InetAddressFromString = from_string(
    InetAddress, na.inet_address_from_string, na.format_inet, "InetAddressFromString"
)
UnixPathAddress: Bottom[na.UnixPathAddress] = _declaration(
    na.UnixPathAddress, "UnixPathAddress", lambda m: m.unix_paths
)


def _unix_path(address: na.UnixPathAddress) -> str:
    return address.path


UnixPathAddressFromString: DecodeToSchema[na.UnixPathAddress, str] = String.pipe(
    decode_to(UnixPathAddress, T.transform(decode=na.unix_path_address, encode=_unix_path))
).annotate(identifier="UnixPathAddressFromString")
SocketAddress: Bottom[na.SocketAddress] = _declaration(
    (na.InetAddressV4, na.InetAddressV6, na.UnixPathAddress),
    "SocketAddress",
    lambda m: m.socket_addresses,
)

# ---------------------------------------------------------------------- hosts


def _is_domain_name(value: str) -> bool:
    return host.is_domain_name(value)


def _is_scoped(value: str) -> bool:
    return na.is_scoped_ipv6_literal(value)


_LABEL = r"[a-z](?:-?[a-z0-9]){0,9}"
_DOMAIN_PATTERN = re.compile(rf"\A{_LABEL}(?:\.{_LABEL}){{0,3}}\Z")
"""Normalized names to generate (random text is rarely one)."""
_SCOPED_PATTERN = re.compile(r"\Afe80::[1-9a-f][0-9a-f]{0,3}%[a-z0-9]{1,8}\Z")


def _same[A](value: A) -> A:
    return value


DomainName = cast(
    "Bottom[host.DomainName, str]",
    String.check(
        make_filter(
            _is_domain_name,
            expected="a normalized domain name",
            arbitrary_constraint=ArbitraryConstraint(patterns=(_DOMAIN_PATTERN,)),
        )
    ).annotate(identifier="DomainName"),
)
"""A normalized ``host.DomainName``."""
DomainNameFromString = from_string(
    DomainName, host.domain_name_from_string, _same, "DomainNameFromString"
)
ScopedIpv6Literal = cast(
    "Bottom[na.ScopedIpv6Literal, str]",
    String.check(
        make_filter(
            _is_scoped,
            expected="a canonical scoped IPv6 literal",
            # Random text is almost never one: generate link-local literals.
            arbitrary_constraint=ArbitraryConstraint(patterns=(_SCOPED_PATTERN,)),
        )
    ).annotate(identifier="ScopedIpv6Literal"),
)
"""A canonical ``net_address.ScopedIpv6Literal`` (``address%zone``)."""
ScopedIpv6LiteralFromString = from_string(
    ScopedIpv6Literal, na.scoped_ipv6_literal_from_string, _same, "ScopedIpv6LiteralFromString"
)
Host: Bottom[host.Host, Any] = Union(IpAddress, ScopedIpv6Literal, DomainName).annotate(
    identifier="Host"
)
"""An IP address, a scoped IPv6 literal or a domain name."""
HostFromString: Bottom[host.Host, str] = Union(
    IpAddressFromString, ScopedIpv6LiteralFromString, DomainNameFromString
).annotate(identifier="HostFromString")
HostPort: Bottom[host.HostPort] = _declaration(host.HostPort, "HostPort", lambda m: m.host_ports)
HostPortFromString = from_string(
    HostPort, host.host_port_from_string, host.format_host_port, "HostPortFromString"
)

# ------------------------------------------------------------------------ DNS

DnsRecordType: LiteralsSchema[dns.RecordType] = Literals(*dns.record_types)
"""A DNS record type (``"A"``, ``"MX"``, ...)."""


def _canonical_address[A: na.IpAddress](
    schema: Codec[A, Any, Any, Any], parse: Callable[[str], Result[A, NetAddressError]]
) -> DecodeToSchema[A, str]:
    # Addresses in JSON records are canonical already (Effect's).
    def decode(text: str, options: ParseOptions) -> Exit[A, Issue]:
        result = parse(text)
        shown = reported(text, options)
        if not isinstance(result, Ok):
            return fail_exit(InvalidValue({"message": result.error.message}, shown))
        if na.format_ip(result.value) != text:
            return fail_exit(InvalidValue({"message": "expected a canonical address"}, shown))
        return Success(result.value)

    return String.pipe(
        decode_to(
            schema,
            T.transform_effect(decode=decode, encode=lambda a, _: Success(na.format_ip(a))),
        )
    )


_UINT8 = Int.check(is_between(minimum=0, maximum=0xFF))
_UINT16 = Int.check(is_between(minimum=0, maximum=0xFFFF))
_UINT32 = Int.check(is_between(minimum=0, maximum=0xFFFFFFFF))


def _seconds(count: int) -> Duration:
    return Duration(float(count))


def _count(seconds: Duration) -> int:
    return int(seconds)


_TIMER = ast.decode_to(_UINT32.ast, ast.number, T.transform(decode=_seconds, encode=_count))
"""An SOA timer: whole seconds, as in zone files."""
_TIMER_DRAWN = ast.append_checks(
    ast.number, (int_value(), is_between(minimum=0, maximum=0xFFFFFFFF))
)
_JSON_KEYS = {"tag_name": "tag", "cert_usage": "certUsage", "matching_type": "matchingType"}


def _record[R: dns.DnsRecord](cls: type[R], identifier: str, **schemas: ast.AST) -> Bottom[R]:
    """The declaration of ``cls`` records, written in JSON as
    ``{"_tag": type, <field>: <encoded field>, ...}``."""
    names = [f.name for f in fields(cls)]
    json = ast.Objects(
        (
            ast.PropertySignature("_tag", ast.Literal(cls.tag)),
            *(ast.PropertySignature(_JSON_KEYS.get(n, n), schemas[n]) for n in names),
        )
    )

    def decode(input: Mapping[str, object], options: ParseOptions) -> Exit[R, Issue]:
        values = {name: input[_JSON_KEYS.get(name, name)] for name in names}
        result = dns.make_record(cls, **values)
        if isinstance(result, Ok):
            return Success(result.value)
        message = {"message": result.error.message}
        return fail_exit(InvalidValue(message, reported(input, options)))

    def encode(record: R, _: ParseOptions) -> Exit[Mapping[str, object], Issue]:
        out: dict[str, object] = {"_tag": cls.tag}
        out.update({_JSON_KEYS.get(n, n): getattr(record, n) for n in names})
        return Success(out)

    def codec(_: tuple[ast.AST, ...]) -> ast.Link:
        return ast.Link(json, T.transform_effect(decode=decode, encode=encode))

    # Generation: the decoded fields, SOA timers as whole seconds.
    drawn = ast.Objects(
        tuple(
            ast.PropertySignature(n, _TIMER_DRAWN if schemas[n] is _TIMER else schemas[n].to_type())
            for n in names
        )
    )

    def made(values: Mapping[str, Any]) -> R:
        return dns.make_record(cls, **values).get_or_raise()

    def arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
        return link(drawn, decode=made, encode=_fields_of)

    return declare(
        _is(cls), identifier=identifier, to_codec_json=codec, to_codec_arbitrary=arbitrary
    )


def _fields_of(record: dns.DnsRecord) -> Mapping[str, object]:
    return {f.name: getattr(record, f.name) for f in fields(record)}


_DOMAIN = DomainName.ast
_NON_EMPTY = NonEmptyString.ast
_STRING = String.ast

DnsARecord = _record(
    dns.A, "DnsARecord", address=_canonical_address(Ipv4Address, na.ipv4_from_string).ast
)
DnsAaaaRecord = _record(
    dns.Aaaa, "DnsAaaaRecord", address=_canonical_address(Ipv6Address, na.ipv6_from_string).ast
)
DnsCaaRecord = _record(
    dns.Caa,
    "DnsCaaRecord",
    critical=Boolean.ast,
    tag_name=String.check(is_pattern(re.compile(r"^[a-z0-9]+$", re.IGNORECASE))).ast,
    value=_STRING,
)
DnsCnameRecord = _record(dns.Cname, "DnsCnameRecord", target=_DOMAIN)
DnsMxRecord = _record(dns.Mx, "DnsMxRecord", exchange=_DOMAIN, priority=_UINT16.ast)
DnsNaptrRecord = _record(
    dns.Naptr,
    "DnsNaptrRecord",
    order=_UINT16.ast,
    preference=_UINT16.ast,
    flags=_STRING,
    service=_STRING,
    regexp=_STRING,
    replacement=_DOMAIN,
)
DnsNsRecord = _record(dns.Ns, "DnsNsRecord", host=_DOMAIN)
DnsPtrRecord = _record(dns.Ptr, "DnsPtrRecord", host=_NON_EMPTY)
DnsSoaRecord = _record(
    dns.Soa,
    "DnsSoaRecord",
    primary=_DOMAIN,
    admin=_NON_EMPTY,
    serial=_UINT32.ast,
    refresh=_TIMER,
    retry=_TIMER,
    expire=_TIMER,
    minimum=_TIMER,
)
DnsSrvRecord = _record(
    dns.Srv,
    "DnsSrvRecord",
    target=_DOMAIN,
    port=_UINT16.ast,
    priority=_UINT16.ast,
    weight=_UINT16.ast,
)
DnsTlsaRecord = _record(
    dns.Tlsa,
    "DnsTlsaRecord",
    cert_usage=_UINT8.ast,
    selector=_UINT8.ast,
    matching_type=_UINT8.ast,
    data=BytesFromHex.ast,
)
DnsTxtRecord = _record(dns.Txt, "DnsTxtRecord", chunks=NonEmptyArray(String).ast)
DnsRecord: Bottom[dns.DnsRecord] = Union(
    DnsARecord,
    DnsAaaaRecord,
    DnsCaaRecord,
    DnsCnameRecord,
    DnsMxRecord,
    DnsNaptrRecord,
    DnsNsRecord,
    DnsPtrRecord,
    DnsSoaRecord,
    DnsSrvRecord,
    DnsTlsaRecord,
    DnsTxtRecord,
).annotate(identifier="DnsRecord")
"""Any DNS record (``pyfect.net.dns``)."""
