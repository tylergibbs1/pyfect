"""The live server closes a connection whose TLS handshake does not finish.

Found by the soak test (tests/soak): a client that gave up during the handshake left the
server's side of the connection open for good. An end of input during the handshake did
not fail it (only a lost connection did), and nothing else closed a connection that had
not reached the app yet; with no limit on the handshake, a client that never sent one
held a connection for good too. Now the end of input fails the handshake, and a
handshake that takes longer than ``handshake_timeout`` (Node's ``handshakeTimeout``,
120 seconds) is dropped.
"""

from __future__ import annotations

import datetime
import socket
import threading
from collections.abc import Callable
from functools import partial

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import pyfect as fx
from pyfect import layer
from pyfect.http import live_server, router, server_response
from pyfect.http.server import HttpServer
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped


def _pem() -> tuple[bytes, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


def _closed_by_the_server(client: socket.socket) -> bool:
    client.settimeout(3)
    try:
        return client.recv(1) == b""
    except TimeoutError:
        return False
    except ConnectionResetError:
        return True


def _with_server(check: Callable[[int], None], handshake_timeout: str | None = None) -> None:
    cert, key = _pem()
    done = threading.Event()

    @fx.fn
    def serving():
        running = yield from HttpServer()
        assert isinstance(running.address, InetAddressV4)
        port = running.address.port
        yield from fx.blocking(partial(check, port))
        done.set()

    app = router.serve(
        router.add("GET", "/", server_response.text("ok")),
        disable_logger=True,
        disable_listen_log=True,
    )
    made = (
        live_server.make_tls(host="127.0.0.1", cert=cert, key=key)
        if handshake_timeout is None
        else live_server.make_tls(
            host="127.0.0.1", cert=cert, key=key, handshake_timeout=handshake_timeout
        )
    )
    server = layer.merge(layer.effect(HttpServer, made), live_server.layer_services)
    fx.run_blocking(scoped(serving().pipe(fx.provide(app))).pipe(fx.provide(server)).or_die())
    assert done.is_set()


def test_a_client_that_hangs_up_during_the_handshake_is_closed() -> None:
    results: list[bool] = []

    def check(port: int) -> None:
        with socket.create_connection(("127.0.0.1", port)) as client:
            client.sendall(b"\x16\x03\x01")  # the start of a ClientHello
            client.shutdown(socket.SHUT_WR)
            results.append(_closed_by_the_server(client))

    _with_server(check)
    assert results == [True]


@pytest.mark.parametrize("timeout", ["300 millis"])
def test_a_handshake_that_never_comes_times_out(timeout: str) -> None:
    results: list[bool] = []

    def check(port: int) -> None:
        with socket.create_connection(("127.0.0.1", port)) as client:
            results.append(_closed_by_the_server(client))

    _with_server(check, handshake_timeout=timeout)
    assert results == [True]
