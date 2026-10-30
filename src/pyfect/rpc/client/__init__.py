"""RPC clients (Effect's ``RpcClient``).

``make(Group)`` is a client of the group over the ``ClientProtocol`` in
the context: an instance of the group whose RPC attributes call them.
``layer_protocol_http(url)`` and ``layer_protocol_socket()`` give the
protocol; the serialization (``RpcSerialization``) comes from the context.
``layer_protocol_worker(size=)`` calls a pool of workers instead (their
messages are values, so it needs no serialization).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect.http.client import HttpClient, HttpClientService
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.rpc.client._core import (
    ClientCore,
    ClientOptions,
    CurrentHeaders,
    OnFromClient,
    make_no_serialization,
    with_headers,
)
from pyfect.rpc.client._http import Batch, make_protocol_http
from pyfect.rpc.client._protocol import (
    ClientProtocol,
    ClientProtocolParts,
    ClientProtocolService,
    with_run_client,
)
from pyfect.rpc.client._serialized import make
from pyfect.rpc.client._transports import (
    ConnectionHooks,
    ConnectionHooksService,
    SocketOptions,
    default_retry_policy,
    make_protocol_socket,
)
from pyfect.rpc.client._worker import layer_protocol_worker, make_protocol_worker
from pyfect.rpc.serialization import RpcSerialization
from pyfect.socket import Socket

type TransformClient = Callable[[HttpClientService[Any, Any]], HttpClientService[Any, Any]]


def layer_protocol_http(
    url: str, *, transform_client: TransformClient | None = None, batch: Batch | None = None
) -> Layer[ClientProtocol, Never, RpcSerialization | HttpClient]:
    """A client protocol POSTing to ``url`` with the ``HttpClient``; with
    ``batch``, the requests a client makes together go in one POST."""
    from pyfect.effect import gen

    @gen
    def make_():
        client = yield from HttpClient()
        bound: HttpClientService[Any, Any] = client.map_request(
            lambda request: request.prepend_url(url)
        )
        if transform_client is not None:
            bound = transform_client(bound)
        return (yield from make_protocol_http(bound, batch=batch))

    return layer_effect(ClientProtocol, make_)


def layer_protocol_socket(
    options: SocketOptions | None = None,
) -> Layer[ClientProtocol, Never, RpcSerialization | Socket]:
    """A client protocol over the ``Socket`` in the context."""
    return layer_effect(ClientProtocol, make_protocol_socket(options))


__all__ = [
    "Batch",
    "ClientCore",
    "ClientOptions",
    "ClientProtocol",
    "ClientProtocolParts",
    "ClientProtocolService",
    "ConnectionHooks",
    "ConnectionHooksService",
    "CurrentHeaders",
    "OnFromClient",
    "SocketOptions",
    "TransformClient",
    "default_retry_policy",
    "layer_protocol_http",
    "layer_protocol_socket",
    "layer_protocol_worker",
    "make",
    "make_no_serialization",
    "make_protocol_http",
    "make_protocol_socket",
    "make_protocol_worker",
    "with_headers",
    "with_run_client",
]
