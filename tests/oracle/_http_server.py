"""A local HTTP server on a thread, standing in for the Node servers of
Effect's HTTP client tests (no network), and an httpx ``HttpClient`` whose
requests go to it (Effect's ``HttpServer.layerTestClient``)."""

import functools
import json
import threading
from email.message import Message
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect

LARGE_BODY = b"a" * (10 * 1024 * 1024)
RESPONSE_BYTES = bytes([0x89, 0x50, 0x4E, 0x47])


def _multipart(content_type: str, body: bytes) -> list[dict[str, str]]:
    message = BytesParser(policy=HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    parts: list[dict[str, str]] = []
    for part in message.iter_parts():
        assert isinstance(part, Message)
        key = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        assert isinstance(key, str)
        assert isinstance(payload, bytes)
        if filename is None:
            parts.append({"key": key, "value": payload.decode()})
        else:
            parts.append(
                {
                    "key": key,
                    "name": filename,
                    "contentType": part.get_content_type(),
                    "content": payload.decode(),
                }
            )
    return parts


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        """Clients hang up mid-request on purpose (interruption, early
        close); that is not an error of the server."""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _body(self) -> bytes:
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            data = b""
            while True:
                size = int(self.rfile.readline().strip() or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    return data
                data += self.rfile.read(size)
                self.rfile.readline()
        return self.rfile.read(int(self.headers.get("content-length") or 0))

    def _send(
        self, status: int, body: bytes = b"", content_type: str = "text/plain", **headers: str
    ) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value: object) -> None:
        self._send(200, json.dumps(value).encode(), "application/json")

    def _hang(self) -> None:
        """Wait until the client closes the connection."""
        self.connection.recv(1)
        self.close_connection = True

    def do_GET(self) -> None:
        match self.path.split("?")[0]:
            case "/" | "/text":
                self._send(200, b"test")
            case "/redirect":
                self._send(302, location="/redirected")
            case "/redirect-body":
                self._send(302, b"redirecting", location="/redirected")
            case "/redirected":
                self._send(200, b"redirected")
            case "/redirect-fragment":
                self._send(302, location="/?value=a%23b#fragment")
            case "/stream":
                self.send_response(200)
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"4\r\ntest\r\n0\r\n\r\n")
            case "/interrupt":
                self.send_response(200)
                self.send_header("transfer-encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"4\r\ntest\r\n")
                self.wfile.flush()
                self._hang()
            case "/todos/1":
                self._json({"userId": 1, "id": 1, "title": "test", "completed": False})
            case "/bytes":
                self._send(200, RESPONSE_BYTES, "application/octet-stream")
            case "/large":
                self._send(200, LARGE_BODY)
            case "/hang":
                self._hang()
            case _:
                self._send(404)

    def do_HEAD(self) -> None:
        self._send(200 if self.path == "/todos" else 404)

    def do_POST(self) -> None:
        try:
            body = self._body()
        except ValueError:
            self.close_connection = True
            return
        match self.path.split("?")[0]:
            case "/":
                self._send(200, body)
            case "/framing":
                framing = self.headers.get("transfer-encoding", "content-length")
                self._send(200, body, **{"x-framing": framing})
            case "/todos":
                self._json({**json.loads(body), "id": 201})
            case "/bom-json":
                value = json.loads(body.decode("utf-8-sig"))
                self._send(200, ("﻿" + json.dumps(value)).encode(), "application/json")
            case "/multipart":
                self._json(_multipart(self.headers["content-type"], body))
            case "/upgrade":
                self._send(
                    401, json.dumps({"message": "unauthorized"}).encode(), "application/json"
                )
            case _:
                self._send(404)

    def do_QUERY(self) -> None:
        body = self._body()
        self._json(
            {
                "method": self.command,
                "contentType": self.headers.get("content-type"),
                "body": body.decode(),
            }
        )


@functools.cache
def base_url() -> str:
    """The URL of the server, started on first use."""
    server = _Server(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


def layer_test_client() -> Layer[HttpClient]:
    """An httpx ``HttpClient`` sending relative URLs to the server."""
    from pyfect.http import httpx_client

    base = base_url()
    return layer_effect(
        HttpClient,
        httpx_client.make().map(lambda client: client.map_request(lambda r: r.prepend_url(base))),
    )
