"""Cluster runners over HTTP or WebSockets (Effect's ``NodeClusterHttp``).

``layer(transport="http" | "websocket")`` is a whole runner: the live HTTP
server at the configured ``runner_listen_address`` (or ``runner_address``)
serving the runner protocol at ``/``, other runners dialed with httpx
(extra ``pyfect-dev[httpx]``) or ``websockets`` (extra
``pyfect-dev[websockets]``), and the health, storage, settings and
serialization options of ``cluster_socket.layer``.
"""

from __future__ import annotations

from typing import Any, Literal, Never, overload

from pyfect import layer as layer_
from pyfect.cluster import http_runner
from pyfect.cluster._cluster_layer import (
    Health,
    SerializationKind,
    ShardingConfigUpdate,
    Storage,
    assemble,
    layer_k8s_http_client,
    runner_health_layer,
)
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import RpcClientProtocol, Runners
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.config import ConfigError
from pyfect.effect import die, gen
from pyfect.file_system import FileSystem
from pyfect.http import httpx_client, live_server
from pyfect.http.etag import Generator
from pyfect.http.platform import HttpPlatform
from pyfect.http.server import HttpServer
from pyfect.layer import Layer
from pyfect.path import Path
from pyfect.rpc.serialization import MaxBufferSize, RpcSerialization
from pyfect.socket.server import SocketServerError
from pyfect.sql.client import SqlClient

type Transport = Literal["http", "websocket"]


@gen
def _http_server():
    config = yield from ShardingConfig()
    listen = config.runner_listen_address or config.runner_address
    if listen is None:
        return (
            yield from die(
                RuntimeError(
                    "NodeClusterHttp.layerHttpServer: ShardingConfig.runnerAddress is None"
                )
            )
        )
    return live_server.layer(port=listen.port, host=listen.host)


layer_http_server: Layer[
    HttpServer | Path | HttpPlatform | FileSystem | Generator, SocketServerError, ShardingConfig
] = layer_.unwrap(_http_server)
"""The live HTTP server (and its platform services) at the runner's
listen address."""


def _client_layer(transport: Transport) -> Layer[Any]:
    """httpx for HTTP, the ``websockets`` constructor for WebSockets."""
    if transport == "http":
        return httpx_client.layer
    # ``websockets`` is an optional extra: load it only for this transport.
    from pyfect.socket import ws

    return ws.layer_web_socket_constructor


def _client_protocol(transport: Transport) -> Layer[RpcClientProtocol, Never, RpcSerialization]:
    protocol: Layer[RpcClientProtocol, Never, Any] = (
        http_runner.layer_client_protocol_http_default
        if transport == "http"
        else http_runner.layer_client_protocol_websocket_default
    )
    return protocol.pipe(layer_.provide(_client_layer(transport)))


def _transport(transport: Transport, client_only: bool) -> Layer[Any, Any, Any]:
    client = _client_layer(transport)
    if client_only:
        sender: Layer[Any, Any, Any] = (
            http_runner.layer_http_client_only
            if transport == "http"
            else http_runner.layer_websocket_client_only
        )
        return sender.pipe(layer_.provide(client))
    served: Layer[Any, Any, Any] = (
        http_runner.layer_http if transport == "http" else http_runner.layer_websocket
    )
    return served.pipe(layer_.provide(layer_.merge(layer_http_server, client)))


type _Out = Sharding | Runners | MessageStorage
type _Core = Sharding | Runners


@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[False] = False,
    storage: Literal["sql"] = "sql",
    runner_health: Health = "ping",
    runner_health_k8s_namespace: str | None = None,
    runner_health_k8s_label_selector: str | None = None,
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, SocketServerError | ConfigError, SqlClient]: ...
@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[False] = False,
    storage: Literal["local"],
    runner_health: Health = "ping",
    runner_health_k8s_namespace: str | None = None,
    runner_health_k8s_label_selector: str | None = None,
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, SocketServerError | ConfigError]: ...
@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[False] = False,
    storage: Literal["byo"],
    runner_health: Health = "ping",
    runner_health_k8s_namespace: str | None = None,
    runner_health_k8s_label_selector: str | None = None,
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Core, SocketServerError | ConfigError, MessageStorage | RunnerStorage]: ...
@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[True],
    storage: Literal["sql"] = "sql",
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, ConfigError, SqlClient]: ...
@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[True],
    storage: Literal["local"],
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, ConfigError]: ...
@overload
def layer(
    *,
    transport: Transport,
    client_only: Literal[True],
    storage: Literal["byo"],
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Core, ConfigError, MessageStorage | RunnerStorage]: ...
def layer(
    *,
    transport: Transport,
    client_only: bool = False,
    storage: Storage = "sql",
    runner_health: Health = "ping",
    runner_health_k8s_namespace: str | None = None,
    runner_health_k8s_label_selector: str | None = None,
    serialization: SerializationKind = "binary",
    serialization_max_buffer_size: MaxBufferSize = 16 * 1024 * 1024,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[Any, Any, Any]:
    """A cluster runner (or, with ``client_only``, a sender) over HTTP or
    WebSockets."""
    health = (
        None
        if client_only
        else runner_health_layer(
            client_protocol=_client_protocol(transport),
            health=runner_health,
            namespace=runner_health_k8s_namespace,
            label_selector=runner_health_k8s_label_selector,
        )
    )
    return assemble(
        _transport(transport, client_only),
        health=health,
        storage=storage,
        sharding_config=sharding_config,
        serialization_kind=serialization,
        serialization_max_buffer_size=serialization_max_buffer_size,
    )


__all__ = ["Transport", "layer", "layer_http_server", "layer_k8s_http_client"]
