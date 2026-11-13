"""The name a client TLS upgrade checks the server certificate against, as
Node's ``tls.connect({socket})`` (Effect's ``NodeSocket`` upgrade) picks it:
``servername``, else the host name the socket connected to, else
``localhost`` (also for an IP literal, which Node does not record as the
socket's host). Loopback only: ``mail.example.test`` resolves to 127.0.0.1 in
this process."""

from __future__ import annotations

import datetime
import socket
from collections.abc import Callable
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import pyfect as fx
from pyfect.net.net_address import InetAddressV4
from pyfect.redacted import Redacted
from pyfect.result import Ok
from pyfect.socket import (
    SocketError,
    SocketService,
    SocketUpgradeError,
    TlsUpgradeOptions,
    make_net,
    server,
)

HOST = "mail.example.test"


def _certificates(name: str) -> tuple[str, str, str]:
    """A CA's PEM, and a leaf it signed for ``DNS:name`` only, with its key."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    key = leaf_key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return ca.public_bytes(pem).decode(), leaf.public_bytes(pem).decode(), key.decode()


@pytest.fixture(autouse=True)
def resolve_host_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve = socket.getaddrinfo

    def local(host: Any, *args: Any, **kwargs: Any) -> Any:
        return resolve("127.0.0.1" if host == HOST else host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local)


def _echo(sock: SocketService) -> fx.Effect[None]:
    @fx.fn
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        while True:
            yield from writer.write_all((yield from reader.pull))

    return fx.scoped(body()).catch_all(lambda _: fx.void)


def _upgrade(
    certified: str, connect: Callable[[int], SocketService], servername: str | None = None
) -> fx.Exit[None, Any]:
    """The exit of a client upgrade on ``connect(port)``, against a server
    whose certificate names only ``certified``."""
    ca, leaf, key = _certificates(certified)

    @fx.fn
    def program():
        srv = yield from server.make_tls(cert=leaf, key=Redacted(key), host="127.0.0.1")
        yield from srv.run(_echo).fork_scoped()
        address = srv.address
        assert isinstance(address, InetAddressV4)
        sock = connect(address.port)
        reader = yield from sock.reader
        return (yield from reader.upgrade(TlsUpgradeOptions(ca=[ca], servername=servername)))

    return fx.run_blocking(fx.scoped(program()).timeout("10 seconds").exit())


def _rejected(exit_: fx.Exit[None, Any]) -> bool:
    if not isinstance(exit_, fx.exit.Failure):
        return False
    match exit_.cause.find_error():
        case Ok(SocketError(reason=SocketUpgradeError())):
            return True
        case _:
            return False


def test_an_upgrade_checks_the_connected_host_name() -> None:
    assert _rejected(_upgrade("localhost", lambda port: make_net(port, HOST)))
    assert not _rejected(_upgrade(HOST, lambda port: make_net(port, HOST)))


def test_a_servername_wins_over_the_connected_host() -> None:
    assert not _rejected(_upgrade("localhost", lambda port: make_net(port, HOST), "localhost"))


def test_an_upgrade_on_an_ip_literal_checks_localhost_as_node_does() -> None:
    assert not _rejected(_upgrade("localhost", lambda port: make_net(port, "127.0.0.1")))
    assert _rejected(_upgrade(HOST, lambda port: make_net(port, "127.0.0.1")))
