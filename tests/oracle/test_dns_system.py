"""Ports of Effect's platform DNS suite (``Dns.test-utils.ts``) for the PTR
queries and reverse lookups of ``dns.make_system``.

Effect runs the suite against a CoreDNS container; here a name server on a
local UDP and TCP socket answers from the suite's reverse and edge zones.
The system resolver queries only PTR records, so the titles that query other
record types stay omitted (``tests/_effect_title_omissions.py``).
"""

import socket
import struct
import threading
from collections.abc import Iterator

import pytest

from pyfect import testing
from pyfect.net import dns
from pyfect.net import host as h
from pyfect.net import net_address as na
from pyfect.net.dns import _wire
from pyfect.result import Err

name = h.domain_name_from_string_unsafe
ip = na.ip_from_string_unsafe

# PTR targets by query name, each target as raw labels.
_ZONE: dict[str, list[list[bytes]]] = {
    "1.2.0.192.in-addr.arpa": [[b"example", b"test"]],
    "2.2.0.192.in-addr.arpa": [[b"good", b"example", b"test"], [b"bad host", b"example", b"test"]],
    "_svc._tcp.edge.test": [
        [b"v2.0 Caf\xc3\xa9\\x", b"_svc", b"_tcp", b"edge", b"test"],
    ],
    "_dot._tcp.edge.test": [[b"printer."]],
    "1.0.0.10.in-addr.arpa": [[b"long-" + bytes([97 + i]) * 50, b"test"] for i in range(20)],
}


def _wire_name(labels: list[bytes]) -> bytes:
    return b"".join(bytes([len(label)]) + label for label in labels) + b"\0"


def _answer(query: bytes, *, truncate: bool) -> bytes:
    query_id = struct.unpack("!H", query[:2])[0]
    offset, labels = 12, list[str]()
    while query[offset]:
        labels.append(query[offset + 1 : offset + 1 + query[offset]].decode())
        offset += 1 + query[offset]
    question = query[12 : offset + 5]
    targets = _ZONE.get(".".join(labels))
    if targets is None:
        return struct.pack("!HHHHHH", query_id, 0x8183, 1, 0, 0, 0) + question
    records = b"".join(
        b"\xc0\x0c" + struct.pack("!HHIH", 12, 1, 300, len(data)) + data
        for data in (_wire_name(target) for target in targets)
    )
    packet = struct.pack("!HHHHHH", query_id, 0x8180, 1, len(targets), 0, 0) + question + records
    if truncate and len(packet) > 512:
        return struct.pack("!HHHHHH", query_id, 0x8382, 1, 0, 0, 0) + question
    return packet


def _serve_udp(sock: socket.socket) -> None:
    while True:
        try:
            query, client = sock.recvfrom(512)
        except OSError:
            return
        sock.sendto(_answer(query, truncate=True), client)


def _serve_tcp(sock: socket.socket) -> None:
    while True:
        try:
            connection, _ = sock.accept()
        except OSError:
            return
        with connection:
            (length,) = struct.unpack("!H", connection.recv(2))
            reply = _answer(connection.recv(length), truncate=False)
            connection.sendall(struct.pack("!H", len(reply)) + reply)


@pytest.fixture(scope="module")
def name_server() -> Iterator[na.InetAddress]:
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    port = udp.getsockname()[1]
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.bind(("127.0.0.1", port))
    tcp.listen()
    for target, sock in ((_serve_udp, udp), (_serve_tcp, tcp)):
        threading.Thread(target=target, args=(sock,), daemon=True).start()
    yield dns.name_server_from_string(f"127.0.0.1:{port}").get_or_raise()
    udp.close()
    tcp.close()


@testing.live(timeout="10 seconds")
def test_reverse_names(name_server: na.InetAddress):
    """looks up the host names of an address, skipping invalid names"""
    resolver = dns.make_system([name_server])
    assert (yield from resolver.reverse(ip("192.0.2.1"))) == ("example.test.",)
    assert (yield from resolver.reverse(ip("192.0.2.2"))) == ("good.example.test.",)


@testing.live(timeout="10 seconds")
def test_reverse_missing(name_server: na.InetAddress):
    """reports missing names and records"""
    missing = yield from dns.make_system([name_server]).reverse(ip("192.0.2.9")).flip()
    assert (missing.reason, missing.method, missing.hostname) == (
        "NotFound",
        "reverse",
        "192.0.2.9",
    )


@testing.live(timeout="10 seconds")
def test_unusual_ptr_names(name_server: na.InetAddress):
    """converts unusual record data"""
    records = yield from dns.make_system([name_server]).resolve(
        name("_svc._tcp.edge.test"), dns.Ptr
    )
    assert records == (dns.Ptr("v2\\.0 Café\\\\x._svc._tcp.edge.test."),)


@testing.live(timeout="10 seconds")
def test_escaped_dot_before_root(name_server: na.InetAddress):
    """keeps the root after a label ending with an escaped dot"""
    records = yield from dns.make_system([name_server]).resolve(
        name("_dot._tcp.edge.test"), dns.Ptr
    )
    assert [dns.format_record(r) for r in records] == ["PTR printer\\.."]


@testing.live(timeout="10 seconds")
def test_truncated_answer_retried_over_tcp(name_server: na.InetAddress):
    names = yield from dns.make_system([name_server]).reverse(ip("10.0.0.1"))
    assert len(names) == 20


@testing.live(timeout="10 seconds")
def test_other_record_types_are_unsupported(name_server: na.InetAddress):
    error = yield from dns.make_system([name_server]).resolve(name("example.test"), dns.Mx).flip()
    assert (error.reason, error.record_type) == ("Unsupported", "MX")


def test_resolv_conf_name_servers_and_options():
    config = _wire.parse_resolv_conf(
        "# comment\nsearch lan\nnameserver 192.0.2.53\nnameserver 2001:db8::53 ; x\n"
        "nameserver not-an-address\noptions timeout:3 attempts:4 rotate\n"
    )
    assert [na.format_inet(s) for s in config.name_servers] == [
        "192.0.2.53:53",
        "[2001:db8::53]:53",
    ]
    assert (config.timeout, config.attempts) == (3, 4)
    assert [na.format_inet(s) for s in _wire.parse_resolv_conf("").name_servers] == ["127.0.0.1:53"]


def test_malformed_and_unrelated_answers():
    query = _wire.ptr_query(7, "1.2.0.192.in-addr.arpa")
    assert _wire.ptr_answer(query, 7) is None  # a query, not a response
    assert _wire.ptr_answer(struct.pack("!HHHHHH", 8, 0x8180, 0, 0, 0, 0), 7) is None
    looping = struct.pack("!HHHHHH", 7, 0x8180, 0, 1, 0, 0) + b"\xc0\x0c"
    assert _wire.ptr_answer(looping, 7) == Err("InvalidResponse")
    refused = struct.pack("!HHHHHH", 7, 0x8185, 0, 0, 0, 0)
    assert _wire.ptr_answer(refused, 7) == Err("Refused")
