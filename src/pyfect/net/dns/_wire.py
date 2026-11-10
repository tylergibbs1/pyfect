"""PTR queries over the DNS wire format (RFC 1035), for the system resolver.

Python's standard library resolves addresses (``getaddrinfo``) but has no DNS
client, and ``gethostbyaddr`` answers from the hosts file and adds the query
name to its aliases. Effect's ``NodeDns`` reverse-resolves by querying PTR
records, so the system ``Dns`` service does the same here: a query over UDP to
each name server in turn, retried over TCP when the answer is truncated.
"""

from __future__ import annotations

import secrets
import socket
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address

from pyfect._digits import parse_digits
from pyfect.duration import Duration
from pyfect.net.dns._error import DnsErrorReason
from pyfect.net.net_address._inet import InetAddress, InetAddressV4, InetAddressV6
from pyfect.result import Err, Ok, Result

_PTR = 12
_IN = 1
# c-ares's answer to each response code, as NodeDns maps its error codes.
_RCODES: dict[int, DnsErrorReason] = {
    1: "InvalidResponse",  # FORMERR
    2: "ServerFailure",  # SERVFAIL
    3: "NotFound",  # NXDOMAIN
    4: "Unsupported",  # NOTIMP
    5: "Refused",  # REFUSED
}


@dataclass(frozen=True, slots=True)
class ResolverConfig:
    """Name servers and per-attempt timeout, as ``/etc/resolv.conf`` gives them."""

    name_servers: tuple[InetAddress, ...]
    timeout: Duration
    attempts: int


_LOCALHOST = InetAddressV4(IPv4Address("127.0.0.1"), 53)


def parse_resolv_conf(text: str) -> ResolverConfig:
    """The resolver configuration in ``resolv.conf`` text; with no name
    server, ``127.0.0.1`` (as c-ares)."""
    from pyfect.net.dns._service import name_server_from_string

    servers: list[InetAddress] = []
    timeout, attempts = 5.0, 2
    for line in text.splitlines():
        fields = line.split("#", 1)[0].split(";", 1)[0].split()
        match fields:
            case ["nameserver", address, *_]:
                parsed = name_server_from_string(address)
                if isinstance(parsed, Ok):
                    servers.append(parsed.value)
            case ["options", *options]:
                for option in options:
                    key, _, value = option.partition(":")
                    number = parse_digits(value)
                    if number is None:
                        continue
                    if key == "timeout":
                        timeout = float(max(number, 1))
                    elif key == "attempts":
                        attempts = max(number, 1)
            case _:
                pass
    return ResolverConfig(tuple(servers) or (_LOCALHOST,), Duration(timeout), attempts)


def system_config() -> ResolverConfig:
    try:
        with open("/etc/resolv.conf", encoding="utf-8", errors="replace") as file:
            return parse_resolv_conf(file.read())
    except OSError:
        return parse_resolv_conf("")


def _encode_name(name: str) -> bytes:
    labels = [label for label in name.rstrip(".").split(".") if label]
    return (
        b"".join(bytes([len(e)]) + e for e in (label.encode("ascii") for label in labels)) + b"\0"
    )


def ptr_query(query_id: int, name: str) -> bytes:
    """A recursive PTR query for ``name`` (an ``in-addr.arpa`` or ``ip6.arpa``
    name)."""
    return (
        struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
        + _encode_name(name)
        + struct.pack("!HH", _PTR, _IN)
    )


class _Malformed(Exception):
    pass


def _label_text(label: bytes) -> str:
    return label.decode("utf-8", "replace").replace("\\", "\\\\").replace(".", "\\.")


def _read_name(packet: bytes, offset: int) -> tuple[str, int]:
    """The name at ``offset`` as text (labels decoded as UTF-8, with ``.`` and
    ``\\`` inside a label escaped, fully qualified) and the offset after it."""
    labels: list[str] = []
    end: int | None = None
    jumps = 0
    while True:
        if offset >= len(packet):
            raise _Malformed
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet) or jumps > 64:
                raise _Malformed
            end = offset + 2 if end is None else end
            offset = ((length & 0x3F) << 8) | packet[offset + 1]
            jumps += 1
        elif length & 0xC0:
            raise _Malformed
        elif length == 0:
            text = ".".join(labels) + "."
            return text, offset + 1 if end is None else end
        else:
            label = packet[offset + 1 : offset + 1 + length]
            if len(label) != length:
                raise _Malformed
            labels.append(_label_text(label))
            offset += 1 + length


def ptr_answer(packet: bytes, query_id: int) -> Result[list[str], DnsErrorReason] | None:
    """The PTR targets in a response to query ``query_id``, the reason it
    failed, or ``None`` when it answers another query."""
    try:
        if len(packet) < 12:
            raise _Malformed
        answer_id, flags, questions, answers, _, _ = struct.unpack("!HHHHHH", packet[:12])
        if answer_id != query_id or not flags & 0x8000:
            return None
        if (reason := _RCODES.get(flags & 0x000F)) is not None:
            return Err(reason)
        offset = 12
        for _ in range(questions):
            offset = _read_name(packet, offset)[1] + 4
        targets: list[str] = []
        for _ in range(answers):
            offset = _read_name(packet, offset)[1]
            if offset + 10 > len(packet):
                raise _Malformed
            record_type, record_class, _, length = struct.unpack(
                "!HHIH", packet[offset : offset + 10]
            )
            offset += 10
            if record_type == _PTR and record_class == _IN:
                targets.append(_read_name(packet, offset)[0])
            offset += length
        return Ok(targets) if targets else Err("NotFound")
    except _Malformed:
        return Err("InvalidResponse")


def _is_truncated(packet: bytes) -> bool:
    return len(packet) >= 4 and bool(packet[2] & 0x02)


def _endpoint(server: InetAddress) -> tuple[int, tuple[str, int] | tuple[str, int, int, int]]:
    match server:
        case InetAddressV4(address, port):
            return socket.AF_INET, (str(address), port)
        case InetAddressV6(address, port, scope_id):
            return socket.AF_INET6, (str(address), port, 0, scope_id)


def _over_udp(server: InetAddress, query: bytes, query_id: int, timeout: float) -> bytes:
    family, endpoint = _endpoint(server)
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect(endpoint)
        sock.send(query)
        while True:
            packet = sock.recv(65535)
            if len(packet) >= 2 and struct.unpack("!H", packet[:2])[0] == query_id:
                return packet


def _receive_exactly(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the name server closed the connection")
        data += chunk
    return data


def _over_tcp(server: InetAddress, query: bytes, timeout: float) -> bytes:
    family, endpoint = _endpoint(server)
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(endpoint)
        sock.sendall(struct.pack("!H", len(query)) + query)
        (length,) = struct.unpack("!H", _receive_exactly(sock, 2))
        return _receive_exactly(sock, length)


def query_ptr(name: str, config: ResolverConfig) -> Result[list[str], DnsErrorReason]:
    """Ask each name server in turn, ``config.attempts`` rounds, for the PTR
    records at ``name``. A missing name ends the search; a failure, refusal
    or timeout moves on to the next server."""
    last: DnsErrorReason = "Timeout"
    for _ in range(config.attempts):
        for server in config.name_servers:
            query_id = secrets.randbelow(0x10000)
            query = ptr_query(query_id, name)
            try:
                packet = _over_udp(server, query, query_id, config.timeout)
                if _is_truncated(packet):
                    packet = _over_tcp(server, query, config.timeout)
            except TimeoutError:
                last = "Timeout"
                continue
            except OSError:
                last = "Refused"
                continue
            match ptr_answer(packet, query_id):
                case Ok() as found:
                    return found
                case Err("NotFound" | "InvalidResponse") as failed:
                    return failed
                case Err(reason):
                    last = reason
                case None:
                    last = "InvalidResponse"
    return Err(last)


def query_ptr_from(
    name: str, name_servers: Sequence[InetAddress]
) -> Result[list[str], DnsErrorReason]:
    """``query_ptr`` with the system configuration, or the given name servers."""
    config = system_config()
    if name_servers:
        config = ResolverConfig(tuple(name_servers), config.timeout, config.attempts)
    return query_ptr(name, config)
