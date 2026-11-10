"""DNS records: one frozen dataclass per record type, validated when built,
and their presentation format (RFC 1035)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from ipaddress import IPv4Address, IPv6Address
from typing import Any, ClassVar, Literal, cast

from pyfect.duration import Duration
from pyfect.net._errors import NetAddressError
from pyfect.net.host import DomainName, is_domain_name
from pyfect.net.net_address._ip import IpAddress, format_ip, ipv4_to_octets, ipv6_to_octets
from pyfect.result import Err, Ok, Result

type RecordType = Literal[
    "A", "AAAA", "CAA", "CNAME", "MX", "NAPTR", "NS", "PTR", "SOA", "SRV", "TLSA", "TXT"
]

type _Check = Callable[[object], bool]


def _uint(top: int) -> _Check:
    return lambda u: isinstance(u, int) and not isinstance(u, bool) and 0 <= u <= top


_uint8, _uint16, _uint32 = _uint(0xFF), _uint(0xFFFF), _uint(0xFFFFFFFF)


def _string(u: object) -> bool:
    return isinstance(u, str)


def _non_empty_string(u: object) -> bool:
    return isinstance(u, str) and len(u) > 0


def _non_empty_strings(values: tuple[object, ...]) -> bool:
    return len(values) > 0 and all(isinstance(v, str) for v in values)


def _timer(u: object) -> bool:
    """SOA timers are unsigned 32-bit counts of seconds on the wire."""
    return (
        isinstance(u, int | float)
        and not isinstance(u, bool)
        and math.isfinite(u)
        and float(u).is_integer()
        and 0 <= u <= 0xFFFFFFFF
    )


@dataclass(frozen=True, slots=True)
class _Record:
    tag: ClassVar[RecordType]
    _checks: ClassVar[dict[str, _Check]]

    def __post_init__(self) -> None:
        for name, check in self._checks.items():
            if not check(getattr(self, name)):
                values = {f.name: getattr(self, f.name) for f in fields(self)}
                raise NetAddressError(f"invalid {self.tag} record {name}", values)

    def __str__(self) -> str:
        return format_record(cast("DnsRecord", self))


@dataclass(frozen=True, slots=True)
class A(_Record):
    address: IPv4Address
    tag: ClassVar[RecordType] = "A"
    _checks: ClassVar[dict[str, _Check]] = {"address": lambda u: isinstance(u, IPv4Address)}


@dataclass(frozen=True, slots=True)
class Aaaa(_Record):
    address: IPv6Address
    tag: ClassVar[RecordType] = "AAAA"
    _checks: ClassVar[dict[str, _Check]] = {"address": lambda u: isinstance(u, IPv6Address)}


@dataclass(frozen=True, slots=True)
class Caa(_Record):
    critical: bool
    tag_name: str
    value: str
    tag: ClassVar[RecordType] = "CAA"
    _checks: ClassVar[dict[str, _Check]] = {
        "critical": lambda u: isinstance(u, bool),
        "tag_name": lambda u: (
            isinstance(u, str) and re.fullmatch(r"[a-z0-9]+", u, re.I) is not None
        ),
        "value": _string,
    }


@dataclass(frozen=True, slots=True)
class Cname(_Record):
    target: DomainName
    tag: ClassVar[RecordType] = "CNAME"
    _checks: ClassVar[dict[str, _Check]] = {"target": is_domain_name}


@dataclass(frozen=True, slots=True)
class Mx(_Record):
    exchange: DomainName
    priority: int
    tag: ClassVar[RecordType] = "MX"
    _checks: ClassVar[dict[str, _Check]] = {"exchange": is_domain_name, "priority": _uint16}


@dataclass(frozen=True, slots=True)
class Naptr(_Record):
    order: int
    preference: int
    flags: str
    service: str
    regexp: str
    replacement: DomainName
    tag: ClassVar[RecordType] = "NAPTR"
    _checks: ClassVar[dict[str, _Check]] = {
        "order": _uint16,
        "preference": _uint16,
        "flags": _string,
        "service": _string,
        "regexp": _string,
        "replacement": is_domain_name,
    }


@dataclass(frozen=True, slots=True)
class Ns(_Record):
    host: DomainName
    tag: ClassVar[RecordType] = "NS"
    _checks: ClassVar[dict[str, _Check]] = {"host": is_domain_name}


@dataclass(frozen=True, slots=True)
class Ptr(_Record):
    """A pointer; ``host`` is name text, which may hold ``\\.`` escapes."""

    host: str
    tag: ClassVar[RecordType] = "PTR"
    _checks: ClassVar[dict[str, _Check]] = {"host": _non_empty_string}


@dataclass(frozen=True, slots=True)
class Soa(_Record):
    primary: DomainName
    admin: str
    serial: int
    refresh: Duration
    retry: Duration
    expire: Duration
    minimum: Duration
    tag: ClassVar[RecordType] = "SOA"
    _checks: ClassVar[dict[str, _Check]] = {
        "primary": is_domain_name,
        "admin": _non_empty_string,
        "serial": _uint32,
        "refresh": _timer,
        "retry": _timer,
        "expire": _timer,
        "minimum": _timer,
    }


@dataclass(frozen=True, slots=True)
class Srv(_Record):
    target: DomainName
    port: int
    priority: int
    weight: int
    tag: ClassVar[RecordType] = "SRV"
    _checks: ClassVar[dict[str, _Check]] = {
        "target": is_domain_name,
        "port": _uint16,
        "priority": _uint16,
        "weight": _uint16,
    }


@dataclass(frozen=True, slots=True)
class Tlsa(_Record):
    cert_usage: int
    selector: int
    matching_type: int
    data: bytes
    tag: ClassVar[RecordType] = "TLSA"
    _checks: ClassVar[dict[str, _Check]] = {
        "cert_usage": _uint8,
        "selector": _uint8,
        "matching_type": _uint8,
        "data": lambda u: isinstance(u, bytes) and len(u) > 0,
    }


@dataclass(frozen=True, slots=True)
class Txt(_Record):
    chunks: tuple[str, ...]
    tag: ClassVar[RecordType] = "TXT"
    _checks: ClassVar[dict[str, _Check]] = {
        "chunks": lambda u: isinstance(u, tuple) and _non_empty_strings(cast(tuple[object, ...], u))
    }


type DnsRecord = A | Aaaa | Caa | Cname | Mx | Naptr | Ns | Ptr | Soa | Srv | Tlsa | Txt

record_classes: tuple[type[DnsRecord], ...] = (
    A,
    Aaaa,
    Caa,
    Cname,
    Mx,
    Naptr,
    Ns,
    Ptr,
    Soa,
    Srv,
    Tlsa,
    Txt,
)
record_types: tuple[RecordType, ...] = tuple(cls.tag for cls in record_classes)


def is_record_type(value: object) -> bool:
    return value in record_types


def make_record[R: DnsRecord](record_type: type[R], /, **fields: Any) -> Result[R, NetAddressError]:
    """Build a record, as its constructor does, giving the rejection as an
    ``Err`` instead of raising it."""
    try:
        return Ok(record_type(**fields))
    except NetAddressError as error:
        return Err(error)
    except TypeError as cause:
        return Err(NetAddressError(f"invalid {record_type.tag} record", fields, cause))


def _decimal_escape(byte: int) -> str:
    return f"\\{byte:03d}"


def _quote(value: str) -> str:
    """A character string in presentation format: ``"`` and ``\\``
    escaped, bytes outside printable ASCII as ``\\DDD``."""
    out = ['"']
    for byte in value.encode("utf-8", "surrogatepass"):
        if byte in (0x22, 0x5C):
            out.append("\\" + chr(byte))
        elif byte < 0x20 or byte > 0x7E:
            out.append(_decimal_escape(byte))
        else:
            out.append(chr(byte))
    return "".join(out) + '"'


_NAME_SPECIALS = frozenset(b'"$();@')


def _format_name(text: str) -> str:
    """Name text in presentation format: ``\\.`` and ``\\\\`` kept, other
    specials escaped, spaces and non-printable bytes as ``\\DDD``."""
    data = text.encode("utf-8", "surrogatepass")
    out: list[str] = []
    i = 0
    while i < len(data):
        byte = data[i]
        if byte == 0x5C:
            following = data[i + 1] if i + 1 < len(data) else None
            if following in (0x2E, 0x5C):
                out.append("\\" + chr(following))
                i += 1
            else:
                out.append("\\\\")
        elif byte <= 0x20 or byte > 0x7E:
            out.append(_decimal_escape(byte))
        else:
            out.append(("\\" if byte in _NAME_SPECIALS else "") + chr(byte))
        i += 1
    return "".join(out)


def _seconds(value: Duration) -> str:
    return str(int(value))


def format_record(record: DnsRecord) -> str:  # noqa: PLR0911
    """The record in DNS presentation format (``MX 10 mail.example.com``)."""
    match record:
        case A() | Aaaa():
            return f"{record.tag} {format_ip(record.address)}"
        case Caa():
            return f"CAA {128 if record.critical else 0} {record.tag_name} {_quote(record.value)}"
        case Cname():
            return f"CNAME {record.target}"
        case Mx():
            return f"MX {record.priority} {record.exchange}"
        case Naptr():
            return (
                f"NAPTR {record.order} {record.preference} {_quote(record.flags)} "
                f"{_quote(record.service)} {_quote(record.regexp)} {record.replacement}"
            )
        case Ns():
            return f"NS {record.host}"
        case Ptr():
            return f"PTR {_format_name(record.host)}"
        case Soa():
            timers = " ".join(
                _seconds(t) for t in (record.refresh, record.retry, record.expire, record.minimum)
            )
            return f"SOA {record.primary} {_format_name(record.admin)} {record.serial} {timers}"
        case Srv():
            return f"SRV {record.priority} {record.weight} {record.port} {record.target}"
        case Tlsa():
            return (
                f"TLSA {record.cert_usage} {record.selector} {record.matching_type} "
                f"{record.data.hex().upper()}"
            )
        case Txt():
            return "TXT " + " ".join(_quote(chunk) for chunk in record.chunks)


def reverse_name(address: IpAddress) -> DomainName:
    """The ``in-addr.arpa`` / ``ip6.arpa`` name a PTR lookup queries."""
    if isinstance(address, IPv4Address):
        return DomainName(
            ".".join(str(o) for o in reversed(ipv4_to_octets(address))) + ".in-addr.arpa"
        )
    nibbles = [f"{n:x}" for octet in ipv6_to_octets(address) for n in (octet >> 4, octet & 0xF)]
    return DomainName(".".join(reversed(nibbles)) + ".ip6.arpa")
