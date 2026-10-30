"""Host names and endpoints (Effect's ``Host``).

A host is an IP address, a scoped IPv6 literal (``fe80::1%eth0``) or a
``DomainName``: lowercase ASCII, internationalized labels converted to
their ``xn--`` form, an optional trailing dot. ``HostPort`` pairs a host
with a port::

    host.host_port_from_string("DB.internal:5432")   # Ok(HostPort("db.internal", 5432))
    host.format_host_port(endpoint)                   # "db.internal:5432"
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import NewType, TypedDict

from pyfect._digits import parse_digits
from pyfect.net._errors import NetAddressError, address_error
from pyfect.net.net_address._ip import (
    IpAddress,
    IpAddressInput,
    ScopedIpv6Literal,
    format_ip,
    ip_from_input,
    ip_from_string,
    is_scoped_ipv6_literal,
    scoped_ipv6_literal_from_string,
)
from pyfect.result import Ok, Result

DomainName = NewType("DomainName", str)
"""A validated, lowercase ASCII domain name; a trailing dot makes it fully
qualified, ``"."`` is the root."""

type DomainNameInput = DomainName | str
type Host = IpAddress | ScopedIpv6Literal | DomainName
type HostInput = Host | IpAddressInput


class HostPortParts(TypedDict):
    host: HostInput
    port: int


_ASCII_NAME_CHARACTER = re.compile(r"[a-z0-9_.-]", re.IGNORECASE)
_LABEL = re.compile(r"[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?")
_NUMERIC_LABEL = re.compile(r"[0-9]+|0x[0-9a-f]*")
_DOMAIN_TEXT = re.compile(r"[a-z0-9_.-]+")
_NUMERIC_HOST = re.compile(r"[0-9.]+")


def _validate(name: str) -> str | None:  # noqa: PLR0911
    """Why ``name`` (lowercase ASCII) is not a domain name, or ``None``."""
    if name == ".":
        return None
    relative = name.removesuffix(".")
    if not relative:
        return "domain name must not be empty"
    if len(relative) > 253:
        return "domain name must be at most 253 characters"
    labels = relative.split(".")
    for label in labels:
        if not label:
            return "domain name labels must not be empty"
        if len(label) > 63:
            return "domain name labels must be at most 63 characters"
        if not _LABEL.fullmatch(label):
            return (
                "domain name labels must contain only letters, digits, hyphens, or "
                "underscores and must not start or end with a hyphen"
            )
    if _NUMERIC_LABEL.fullmatch(labels[-1]):
        return "the last domain name label must not be numeric"
    return None


def _to_ascii(text: str) -> str | None:
    """The name lowercased, or its WHATWG URL host form when it holds
    non-ASCII characters; ``None`` for characters a name cannot hold."""
    if all(_ASCII_NAME_CHARACTER.fullmatch(ch) for ch in text if ch.isascii()):
        if text.isascii():
            return text.lower()
        from pyfect.http import url

        try:
            return url.parse(f"http://{text}").hostname
        except ValueError:
            return None
    return None


def is_domain_name(value: object) -> bool:
    """Whether ``value`` is already a normalized domain name."""
    return (
        isinstance(value, str) and bool(_DOMAIN_TEXT.fullmatch(value)) and _validate(value) is None
    )


def is_host(value: object) -> bool:
    return (
        isinstance(value, IPv4Address | IPv6Address)
        or is_scoped_ipv6_literal(value)
        or is_domain_name(value)
    )


def domain_name_from_string(text: str) -> Result[DomainName, NetAddressError]:
    name = _to_ascii(text)
    if name is None:
        return address_error(text, "invalid domain name")
    error = _validate(name)
    return Ok(DomainName(name)) if error is None else address_error(text, error)


def domain_name_from_string_unsafe(text: str) -> DomainName:
    return domain_name_from_string(text).get_or_raise()


def domain_name_from_input(value: DomainNameInput) -> Result[DomainName, NetAddressError]:
    return domain_name_from_string(value)


def domain_name_from_input_unsafe(value: DomainNameInput) -> DomainName:
    return domain_name_from_input(value).get_or_raise()


def host_from_string(text: str) -> Result[Host, NetAddressError]:
    """A scoped IPv6 literal, an IP address or a domain name, by its text."""
    if "%" in text:
        scoped: Result[Host, NetAddressError] = scoped_ipv6_literal_from_string(text)
        return scoped
    if ":" in text:
        return ip_from_string(text)
    if _NUMERIC_HOST.fullmatch(text):
        address = ip_from_string(text)
        if isinstance(address, Ok):
            return address
    return domain_name_from_string(text)


def host_from_string_unsafe(text: str) -> Host:
    return host_from_string(text).get_or_raise()


def host_from_input(value: HostInput) -> Result[Host, NetAddressError]:
    if isinstance(value, str):
        return host_from_string(value)
    return ip_from_input(value)


def host_from_input_unsafe(value: HostInput) -> Host:
    return host_from_input(value).get_or_raise()


def format_host(host: Host) -> str:
    return host if isinstance(host, str) else format_ip(host)


def is_fully_qualified(name: DomainName) -> bool:
    return name.endswith(".")


def to_fully_qualified(name: DomainName) -> DomainName:
    return name if is_fully_qualified(name) else DomainName(f"{name}.")


def to_relative(name: DomainName) -> DomainName:
    return DomainName(name[:-1]) if len(name) > 1 and is_fully_qualified(name) else name


@dataclass(frozen=True, slots=True)
class HostPort:
    """A host and port; ``str`` gives ``host:port`` (``[ipv6]:port``)."""

    host: Host
    port: int

    def __post_init__(self) -> None:
        if not is_host(self.host):
            raise NetAddressError("expected a host", self.host)
        if not _is_port(self.port):
            raise NetAddressError("port must be an integer from 0 through 65535", self.port)

    def __str__(self) -> str:
        return format_host_port(self)


type HostPortInput = HostPort | str | HostPortParts


def _is_port(port: object) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 0 <= port <= 0xFFFF


def host_port(host: Host, port: int) -> Result[HostPort, NetAddressError]:
    if not is_host(host):
        return address_error(host, "expected a host")
    if not _is_port(port):
        return address_error(port, "port must be an integer from 0 through 65535")
    return Ok(HostPort(host, port))


def host_port_unsafe(host: Host, port: int) -> HostPort:
    return host_port(host, port).get_or_raise()


def host_port_from_string(text: str) -> Result[HostPort, NetAddressError]:  # noqa: PLR0911
    if text.startswith("["):
        end = text.find("]")
        if end == -1 or text[end + 1 : end + 2] != ":":
            return address_error(text, "expected [IPv6]:port")
        host_text, port_text = text[1:end], text[end + 2 :]
        if ":" not in host_text:
            return address_error(text, "only IPv6 addresses use brackets")
    else:
        separator = text.rfind(":")
        if separator == -1:
            return address_error(text, "expected host:port")
        if text.find(":") != separator:
            return address_error(text, "IPv6 addresses must be bracketed")
        host_text, port_text = text[:separator], text[separator + 1 :]
    port = parse_digits(port_text, unpadded=True)
    if port is None:
        return address_error(text, "port must be an unpadded decimal integer")
    if not _is_port(port):
        return address_error(text, "port must be an integer from 0 through 65535")
    return host_from_string(host_text).map(lambda host: HostPort(host, port))


def host_port_from_string_unsafe(text: str) -> HostPort:
    return host_port_from_string(text).get_or_raise()


def host_port_from_input(value: HostPortInput) -> Result[HostPort, NetAddressError]:
    """An endpoint, its text, or ``{"host": ..., "port": ...}``."""
    if isinstance(value, HostPort):
        return Ok(value)
    if isinstance(value, str):
        return host_port_from_string(value)
    port = value["port"]
    return host_from_input(value["host"]).flat_map(lambda host: host_port(host, port))


def host_port_from_input_unsafe(value: HostPortInput) -> HostPort:
    return host_port_from_input(value).get_or_raise()


def format_host_port(endpoint: HostPort) -> str:
    host = format_host(endpoint.host)
    return f"[{host}]:{endpoint.port}" if ":" in host else f"{host}:{endpoint.port}"


type HostsTable = Mapping[DomainName, tuple[IpAddress, ...]]


def parse_hosts_file(text: str) -> HostsTable:
    """A hosts file's addresses by relative name, in file order; lines and
    names that do not parse are skipped."""
    hosts: dict[DomainName, list[IpAddress]] = {}
    for line in re.split(r"\r?\n", text):
        fields = line.partition("#")[0].split()
        if not fields:
            continue
        address = ip_from_string(fields[0])
        if not isinstance(address, Ok):
            continue
        for name in fields[1:]:
            domain = domain_name_from_string(name)
            if not isinstance(domain, Ok):
                continue
            addresses = hosts.setdefault(to_relative(domain.value), [])
            if address.value not in addresses:
                addresses.append(address.value)
    return {name: tuple(addresses) for name, addresses in hosts.items()}


__all__ = [
    "DomainName",
    "DomainNameInput",
    "Host",
    "HostInput",
    "HostPort",
    "HostPortInput",
    "HostPortParts",
    "HostsTable",
    "domain_name_from_input",
    "domain_name_from_input_unsafe",
    "domain_name_from_string",
    "domain_name_from_string_unsafe",
    "format_host",
    "format_host_port",
    "host_from_input",
    "host_from_input_unsafe",
    "host_from_string",
    "host_from_string_unsafe",
    "host_port",
    "host_port_from_input",
    "host_port_from_input_unsafe",
    "host_port_from_string",
    "host_port_from_string_unsafe",
    "host_port_unsafe",
    "is_domain_name",
    "is_fully_qualified",
    "is_host",
    "parse_hosts_file",
    "to_fully_qualified",
    "to_relative",
]
