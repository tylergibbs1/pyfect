"""Clients for tests of the live HTTP server: raw sockets (run off the
fiber's thread with ``effect.blocking``) and a parser for what they
receive."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import effect
from pyfect.http import live_server
from pyfect.http.server import HttpServer
from pyfect.net.net_address import InetAddressV4, InetAddressV6
from pyfect.scope import scoped

TIMEOUT = 5.0


def run_live(program: fx.Effect[Any, Any, Any], **options: Any) -> Any:
    """Run ``program`` with a live test server (and its client)."""
    provided = scoped(program).pipe(fx.provide(live_server.layer_test(**options)))
    return fx.run_blocking(provided.or_die())


def _port(address: object) -> int:
    assert isinstance(address, InetAddressV4 | InetAddressV6)
    return address.port


port: fx.Effect[int, Any, HttpServer] = HttpServer().map(lambda server: _port(server.address))


def _connect(at: int) -> socket.socket:
    conn = socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT)
    conn.settimeout(TIMEOUT)
    return conn


def _read_until_close(conn: socket.socket) -> bytes:
    received = bytearray()
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        try:
            chunk = conn.recv(65536)
        except ConnectionResetError:
            break
        if not chunk:
            break
        received += chunk
    return bytes(received)


def exchange(at: int, parts: Sequence[bytes], *, pause: float = 0.05) -> fx.Effect[bytes]:
    """Send ``parts`` on one connection (pausing between them), ending the
    write side after the last; everything received until it closes."""

    def run() -> bytes:
        with _connect(at) as conn:
            for index, part in enumerate(parts):
                if index:
                    time.sleep(pause)
                conn.sendall(part)
            conn.shutdown(socket.SHUT_WR)
            return _read_until_close(conn)

    return effect.blocking(run)


def until_close(at: int, data: bytes) -> fx.Effect[bytes]:
    """Send ``data``, keeping the write side open; everything received
    until the server closes."""

    def run() -> bytes:
        with _connect(at) as conn:
            conn.sendall(data)
            return _read_until_close(conn)

    return effect.blocking(run)


def with_socket[A](at: int, use: Callable[[socket.socket], A]) -> fx.Effect[A]:
    def run() -> A:
        with _connect(at) as conn:
            return use(conn)

    return effect.blocking(run)


@dataclass(frozen=True)
class Response:
    status: int
    reason: str
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name: str) -> str | None:
        for key, value in self.headers:
            if key == name:
                return value
        return None


def _dechunk(data: bytes) -> tuple[bytes, bytes]:
    body = bytearray()
    while True:
        line, _, data = data.partition(b"\r\n")
        size = int(line.split(b";")[0], 16)
        if size == 0:
            _, _, rest = data.partition(b"\r\n")
            return bytes(body), rest
        body += data[:size]
        data = data[size + 2 :]


def parse_responses(data: bytes, *, head: bool = False) -> list[Response]:
    """Every response in ``data`` (``head``: their bodies were omitted)."""
    responses: list[Response] = []
    while data:
        head_bytes, separator, data = data.partition(b"\r\n\r\n")
        if not separator:
            break
        lines = head_bytes.decode("latin-1").split("\r\n")
        _version, status, *reason = lines[0].split(" ", 2)
        headers = [
            (name.lower(), value.strip())
            for name, _, value in (line.partition(":") for line in lines[1:])
        ]
        response = Response(int(status), reason[0] if reason else "", headers, b"")
        if int(status) < 200 or head or int(status) in (204, 304):
            body = b""
        elif response.header("transfer-encoding") == "chunked":
            body, data = _dechunk(data)
        elif (length := response.header("content-length")) is not None:
            body, data = data[: int(length)], data[int(length) :]
        else:
            body, data = data, b""
        responses.append(Response(response.status, response.reason, headers, body))
    return responses


@dataclass(frozen=True)
class ContinueResult:
    status: int
    body: bytes
    continues: int
    uploaded: bool


def expect_continue(
    at: int, payload: bytes, headers: dict[str, str] | None = None
) -> fx.Effect[ContinueResult]:
    """POST ``payload`` with ``Expect: 100-continue``, uploading it only
    once the server asks for it (as curl does)."""

    def use(conn: socket.socket) -> ContinueResult:
        lines = [
            "POST / HTTP/1.1",
            "host: 127.0.0.1",
            "expect: 100-continue",
            f"content-length: {len(payload)}",
            "connection: close",
            *(f"{name}: {value}" for name, value in (headers or {}).items()),
        ]
        conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        received = bytearray()
        continues = 0
        uploaded = False
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            received += chunk
            while received.startswith(b"HTTP/1.1 100 Continue\r\n\r\n"):
                del received[: len(b"HTTP/1.1 100 Continue\r\n\r\n")]
                continues += 1
                if not uploaded:
                    uploaded = True
                    conn.sendall(payload)
        [response] = parse_responses(bytes(received))
        return ContinueResult(response.status, response.body, continues, uploaded)

    return with_socket(at, use)
