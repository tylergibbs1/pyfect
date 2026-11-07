"""Ports of ``platform/node/test/OtlpProxy.test.ts`` ("OtlpProxy on
NodeHttpServer"), on a real uvicorn server.

Each test's docstring is the Effect test title. ``NodeHttpServer.layerTest``
is ``uvicorn_server.layer_test``. The headers-only request is a raw socket
that declares a 100-byte body and never sends it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import pyfect as fx
from pyfect import byte_size, layer, stream
from pyfect.http import body as http_body
from pyfect.http import client, response, router, uvicorn_server
from pyfect.http.client import HttpClient, HttpClientError
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.server import HttpServer
from pyfect.net.net_address import InetAddressV4, InetAddressV6
from pyfect.observability import otlp_proxy


def _upstream() -> tuple[list[HttpClientRequest], client.HttpClientService[HttpClientError]]:
    forwarded: list[HttpClientRequest] = []

    def post(
        made: fx.Effect[HttpClientRequest, Any, Any],
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        def send(request: HttpClientRequest) -> HttpClientResponse:
            forwarded.append(request)
            return response.make(request)

        return made.map(send)

    return forwarded, client.make_with(post, fx.succeed)


def test_applies_an_explicit_max_body_size_above_the_ambient_max_body_size() -> None:
    """OtlpProxy on NodeHttpServer applies an explicit maxBodySize above the ambient MaxBodySize to declared and chunked bodies"""  # noqa: E501
    forwarded, upstream = _upstream()
    proxy = otlp_proxy.layer(base_url="http://upstream.example", max_body_size=8).pipe(
        layer.provide(layer.succeed(HttpClient, upstream))
    )
    served = router.serve(
        proxy,
        disable_logger=True,
        disable_listen_log=True,
        middleware=fx.provide_service(MaxBodySize, byte_size.bytes(4)),
    )
    data = bytes([1, 2, 3, 4, 5, 6])

    @fx.gen
    def program():
        http = yield from HttpClient()
        declared = yield from http.post(
            "/v1/traces", body=http_body.bytes_(data, "application/x-protobuf")
        )
        chunked = yield from http.post(
            "/v1/traces",
            body=http_body.stream(stream.make(data), "application/x-protobuf"),
        )
        return declared.status, chunked.status

    statuses = fx.run_blocking(
        fx.scoped(program)
        .pipe(layer.provide(served.pipe(layer.provide_merge(uvicorn_server.layer_test()))))
        .timeout(10)
        .or_die()
    )
    assert statuses == (200, 200)
    assert len(forwarded) == 2


async def _headers_only_request(port: int, headers: dict[str, str]) -> tuple[int, int]:
    """The status of a request whose 100-byte body never comes, and how
    many ``100 Continue`` answers arrived first."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        lines = [
            "POST /v1/traces HTTP/1.1",
            f"host: 127.0.0.1:{port}",
            "content-type: application/x-protobuf",
            "content-length: 100",
            *(f"{name}: {value}" for name, value in headers.items()),
        ]
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        await writer.drain()
        continues = 0
        while True:
            status_line = await asyncio.wait_for(reader.readline(), 3)
            status = int(status_line.split()[1])
            while (await reader.readline()) not in (b"\r\n", b""):
                pass
            if status != 100:
                return status, continues
            continues += 1
    finally:
        writer.close()


@pytest.mark.parametrize(
    "headers", [{}, {"expect": "100-continue"}], ids=["", " with Expect: 100-continue"]
)
def test_rejects_an_over_limit_content_length_before_the_body_arrives(
    headers: dict[str, str],
) -> None:
    """OtlpProxy on NodeHttpServer rejects an over-limit content-length before the body arrives$name"""  # noqa: E501
    forwarded, upstream = _upstream()
    proxy = otlp_proxy.layer(base_url="http://upstream.example", max_body_size=4).pipe(
        layer.provide(layer.succeed(HttpClient, upstream))
    )
    served = router.serve(proxy, disable_logger=True, disable_listen_log=True)

    @fx.gen
    def program():
        server = yield from HttpServer()
        address = server.address
        assert isinstance(address, InetAddressV4 | InetAddressV6)
        port = address.port
        return (yield from fx.from_async(lambda: _headers_only_request(port, headers)))

    status, continues = asyncio.run(
        fx.run_async(
            fx.scoped(program)
            .pipe(layer.provide(served.pipe(layer.provide_merge(uvicorn_server.layer_test()))))
            .timeout(10)
            .or_die()
        )
    )
    assert (status, continues) == (413, 0)
    assert forwarded == []
