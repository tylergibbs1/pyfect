"""Socket addresses: an IP address and port (``InetAddressV4`` /
``InetAddressV6``, the latter with a scope), or a Unix socket path."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import NotRequired, TypedDict, overload

from pyfect._digits import is_digits, parse_digits
from pyfect._url import Url
from pyfect.net._errors import NetAddressError, address_error
from pyfect.net.net_address._ip import (
    IpAddress,
    IpAddressInput,
    canonical_ip,
    format_ip,
    format_url_host,
    ip_from_input,
    ip_from_string,
)
from pyfect.result import Err, Ok, Result


def _check_port(port: object) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 0 <= port <= 0xFFFF


def _check_scope(scope_id: object) -> bool:
    return (
        isinstance(scope_id, int) and not isinstance(scope_id, bool) and 0 <= scope_id <= 0xFFFFFFFF
    )


@dataclass(frozen=True, slots=True)
class InetAddressV4:
    """An IPv4 address and port; ``str`` gives ``1.2.3.4:80``."""

    address: IPv4Address
    port: int

    def __post_init__(self) -> None:
        if not _check_port(self.port):
            raise NetAddressError("port must be an integer from 0 through 65535", self.address)

    def __str__(self) -> str:
        return format_inet(self)


@dataclass(frozen=True, slots=True)
class InetAddressV6:
    """An IPv6 address, port and scope (``0`` when unscoped); ``str`` gives
    ``[fe80::1%2]:80``."""

    address: IPv6Address
    port: int
    scope_id: int = 0

    def __post_init__(self) -> None:
        if not _check_port(self.port):
            raise NetAddressError("port must be an integer from 0 through 65535", self.address)
        if not _check_scope(self.scope_id):
            raise NetAddressError("scopeId must be an unsigned 32-bit integer", self.address)

    def __str__(self) -> str:
        return format_inet(self)


type InetAddress = InetAddressV4 | InetAddressV6


@dataclass(frozen=True, slots=True)
class UnixPathAddress:
    """A Unix socket path, kept as given."""

    path: str

    def __str__(self) -> str:
        return self.path


type SocketAddress = InetAddress | UnixPathAddress


class InetAddressParts(TypedDict):
    address: IpAddressInput
    port: int
    scope_id: NotRequired[int]


class UnixPathAddressParts(TypedDict):
    path: str


type InetAddressInput = InetAddress | str | InetAddressParts
type SocketAddressInput = SocketAddress | InetAddressInput | UnixPathAddressParts


class NetworkInterfaceAddress(TypedDict):
    """An entry of a network interface listing, as Node's
    ``os.networkInterfaces()`` gives it."""

    family: str
    scopeid: NotRequired[int | None]


def inet_address_v4(address: IPv4Address, port: int) -> Result[InetAddressV4, NetAddressError]:
    if not _check_port(port):
        return address_error(address, "port must be an integer from 0 through 65535")
    return Ok(InetAddressV4(address, port))


def inet_address_v6(
    address: IPv6Address, port: int, *, scope_id: int = 0
) -> Result[InetAddressV6, NetAddressError]:
    if not _check_port(port):
        return address_error(address, "port must be an integer from 0 through 65535")
    if not _check_scope(scope_id):
        return address_error(address, "scopeId must be an unsigned 32-bit integer")
    return Ok(InetAddressV6(address, port, scope_id))


@overload
def inet_address(address: IPv4Address, port: int) -> Result[InetAddressV4, NetAddressError]: ...
@overload
def inet_address(address: IPv6Address, port: int) -> Result[InetAddressV6, NetAddressError]: ...
@overload
def inet_address(address: IpAddress, port: int) -> Result[InetAddress, NetAddressError]: ...
def inet_address(address: IpAddress, port: int) -> Result[InetAddress, NetAddressError]:
    if isinstance(address, IPv4Address):
        return inet_address_v4(address, port)
    return inet_address_v6(address, port)


def inet_address_unsafe(address: IpAddress, port: int) -> InetAddress:
    return inet_address(address, port).get_or_raise()


def inet_address_from_ip_string(address: str, port: int) -> Result[InetAddress, NetAddressError]:
    return ip_from_string(address).flat_map(lambda ip: inet_address(ip, port))


def inet_address_from_ip_string_unsafe(address: str, port: int) -> InetAddress:
    return inet_address_from_ip_string(address, port).get_or_raise()


def inet_address_from_native_unsafe(
    host: str, port: int, scope_ids: Mapping[str, int] | None = None
) -> InetAddress:
    """The address a socket API reported (``'::ffff:1.2.3.4'``,
    ``'fe80::1%en0'``), trusted; a named zone is looked up in
    ``scope_ids`` and raises ``ValueError`` when unknown."""
    text, _, zone = host.partition("%")
    address = ip_address(text)
    if isinstance(address, IPv4Address):
        return InetAddressV4(address, port)
    scope_id = 0
    if zone:
        found = parse_digits(zone) if is_digits(zone) else (scope_ids or {}).get(zone)
        if found is None:
            raise ValueError(f"unknown IPv6 interface: {zone}")
        scope_id = found
    return InetAddressV6(address, port, scope_id)


def inet_address_from_host_string(
    host: str, port: int, scope_ids: Mapping[str, int] | None = None
) -> Result[InetAddress, NetAddressError]:
    """A host as ``format_host`` or ``format_native_host`` writes it, and a
    port; a named zone is resolved only through ``scope_ids``."""
    head, separator, zone = host.partition("%")
    if separator:
        if not zone or "%" in zone:
            return address_error(host, "invalid IPv6 scope identifier")
        if not is_digits(zone):
            scope_id = (scope_ids or {}).get(zone)
            if scope_id is None:
                return address_error(host, f"unknown IPv6 interface: {zone}")
            host = f"{head}%{scope_id}"
    return inet_address_from_string(f"[{host}]:{port}" if ":" in host else f"{host}:{port}")


def scope_id_from_interface(
    addresses: Iterable[NetworkInterfaceAddress] | None,
) -> int | None:
    """The first positive IPv6 scope ID among an interface's addresses."""
    for address in addresses or ():
        scope = address.get("scopeid")
        if address["family"] == "IPv6" and isinstance(scope, int) and scope > 0:
            return scope
    return None


def scope_ids_from_interfaces(
    interfaces: Iterable[tuple[str, Iterable[NetworkInterfaceAddress] | None]],
) -> dict[str, int]:
    """Each interface's first positive IPv6 scope ID, by name, as a
    snapshot."""
    scope_ids: dict[str, int] = {}
    for name, addresses in interfaces:
        scope_id = scope_id_from_interface(addresses)
        if scope_id is not None:
            scope_ids[name] = scope_id
    return scope_ids


def _split_inet(text: str) -> Result[tuple[str, str, int, bool], NetAddressError]:  # noqa: PLR0911
    if text.startswith("["):
        end = text.find("]")
        if end < 0 or text[end + 1 : end + 2] != ":" or "]" in text[end + 1 :]:
            return address_error(text, "expected [IPv6]:port")
        host, port_text = text[1:end], text[end + 2 :]
        head, separator, scope_text = host.partition("%")
        scope_id = 0
        if separator:
            if "%" in scope_text or not is_digits(scope_text):
                return address_error(text, "scope identifier must be decimal")
            number = parse_digits(scope_text)
            if number is None or number > 0xFFFFFFFF:
                return address_error(text, "scope identifier must be an unsigned 32-bit integer")
            scope_id = number
        return Ok((head, port_text, scope_id, True))
    separator = text.rfind(":")
    if separator < 0:
        return address_error(text, "expected host:port or [IPv6]:port")
    if text.find(":") != separator:
        return address_error(text, "IPv6 addresses must be bracketed")
    return Ok((text[:separator], text[separator + 1 :], 0, False))


def inet_address_from_string(text: str) -> Result[InetAddress, NetAddressError]:
    """``1.2.3.4:80`` or ``[::1]:80`` / ``[fe80::1%2]:80``: numeric hosts
    only, an unpadded decimal port."""
    match _split_inet(text):
        case Err() as error:
            return error
        case Ok((host, port_text, scope_id, bracketed)):
            pass
    port = parse_digits(port_text, unpadded=True)
    if port is None:
        return address_error(text, "port must be an unpadded decimal integer")

    def build(address: IpAddress) -> Result[InetAddress, NetAddressError]:
        if bracketed != isinstance(address, IPv6Address):
            return address_error(text, "only IPv6 addresses use brackets")
        if isinstance(address, IPv6Address):
            return inet_address_v6(address, port, scope_id=scope_id)
        return inet_address_v4(address, port)

    return ip_from_string(host).flat_map(build)


def inet_address_from_string_unsafe(text: str) -> InetAddress:
    return inet_address_from_string(text).get_or_raise()


def inet_address_from_input(value: InetAddressInput) -> Result[InetAddress, NetAddressError]:
    """An address, its text, or ``{"address": ..., "port": ..., "scope_id":
    ...}``."""
    match value:
        case InetAddressV4() | InetAddressV6():
            return Ok(value)
        case str():
            return inet_address_from_string(value)
        case _:
            pass
    port, scope_id = value["port"], value.get("scope_id", 0)

    def build(address: IpAddress) -> Result[InetAddress, NetAddressError]:
        if isinstance(address, IPv6Address):
            return inet_address_v6(address, port, scope_id=scope_id)
        if scope_id != 0:
            return address_error(value, "scopeId requires an IPv6 address")
        return inet_address_v4(address, port)

    return ip_from_input(value["address"]).flat_map(build)


def inet_address_from_input_unsafe(value: InetAddressInput) -> InetAddress:
    return inet_address_from_input(value).get_or_raise()


@overload
def to_canonical(address: IPv4Address) -> IPv4Address: ...
@overload
def to_canonical(address: IPv6Address) -> IpAddress: ...
@overload
def to_canonical(address: InetAddressV4) -> InetAddressV4: ...
@overload
def to_canonical(address: InetAddressV6) -> InetAddress: ...
def to_canonical(
    address: IpAddress | InetAddress,
) -> IpAddress | InetAddress:
    """An IPv4-mapped IPv6 address as the IPv4 address it holds (its port
    kept, its scope dropped); any other address unchanged (the same
    object)."""
    if isinstance(address, InetAddressV4 | InetAddressV6):
        ip = canonical_ip(address.address)
        return address if ip is address.address else inet_address_unsafe(ip, address.port)
    return canonical_ip(address)


def format_host(address: InetAddress) -> str:
    """The address's host: IPv6 with its numeric scope when it has one."""
    scope = (
        f"%{address.scope_id}"
        if isinstance(address, InetAddressV6) and address.scope_id != 0
        else ""
    )
    return format_ip(address.address) + scope


def format_native_host(
    address: InetAddress, scope_ids: Mapping[str, int], platform: str | None = None
) -> str:
    """The host for a socket API: outside Windows, a scope named after the
    first interface in ``scope_ids`` that has it."""
    if platform != "win32" and isinstance(address, InetAddressV6) and address.scope_id != 0:
        for name, scope_id in scope_ids.items():
            if scope_id == address.scope_id:
                return f"{format_ip(address.address)}%{name}"
    return format_host(address)


def format_multicast_interface(
    interface: IPv4Address | int, scope_ids: Mapping[str, int], platform: str | None = None
) -> str:
    """A multicast interface for a socket API: an IPv4 address, or an IPv6
    interface index as ``::%name`` (``::%index`` on Windows or when no
    interface has it, ``::`` for ``0``)."""
    if isinstance(interface, IPv4Address):
        return format_ip(interface)
    if interface == 0:
        return "::"
    if platform != "win32":
        for name, scope_id in scope_ids.items():
            if scope_id == interface:
                return f"::%{name}"
    return f"::%{interface}"


def format_inet(address: InetAddress) -> str:
    host = format_host(address)
    return (
        f"{host}:{address.port}"
        if isinstance(address, InetAddressV4)
        else f"[{host}]:{address.port}"
    )


def to_url(address: IpAddress | InetAddress, scheme: str = "http") -> Result[Url, NetAddressError]:
    """The address as a WHATWG-normalized URL (``pyfect.http.url``); scoped
    IPv6 addresses have no URL form."""
    from pyfect.http import url

    if isinstance(address, InetAddressV6) and address.scope_id != 0:
        return address_error(address, "scoped IPv6 addresses are not supported by WHATWG URLs")
    authority = (
        format_inet(address)
        if isinstance(address, InetAddressV4 | InetAddressV6)
        else format_url_host(address)
    )
    try:
        return Ok(url.parse(f"{scheme}://{authority}"))
    except ValueError as cause:
        return Err(NetAddressError("failed to construct URL", address, cause))


def format_url(
    address: IpAddress | SocketAddress, scheme: str = "http"
) -> Result[str, NetAddressError]:
    """``scheme://host[:port]`` without a trailing slash or default port; a
    Unix path as ``unix://path``."""
    if isinstance(address, UnixPathAddress):
        return Ok(format_unix_path(address))
    return to_url(address, scheme).map(lambda u: f"{u.scheme}://{u.netloc}")


def format_url_unsafe(address: IpAddress | SocketAddress, scheme: str = "http") -> str:
    return format_url(address, scheme).get_or_raise()


def format_url_host_string(host: str) -> str:
    """A host string as a URL host: IPv6 text in brackets."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def unix_path_address(path: str) -> UnixPathAddress:
    return UnixPathAddress(path)


def format_unix_path(address: UnixPathAddress) -> str:
    return f"unix://{address.path}"


def socket_address_from_input(value: SocketAddressInput) -> Result[SocketAddress, NetAddressError]:
    """A socket address, its text, or its parts (``{"path": ...}`` for a
    Unix socket)."""
    if isinstance(value, UnixPathAddress):
        return Ok(value)
    if isinstance(value, Mapping) and "path" in value:
        return Ok(UnixPathAddress(value["path"]))
    return inet_address_from_input(value)


def socket_address_from_input_unsafe(value: SocketAddressInput) -> SocketAddress:
    return socket_address_from_input(value).get_or_raise()


def format_socket_address(address: SocketAddress) -> str:
    return address.path if isinstance(address, UnixPathAddress) else format_inet(address)
