"""Cluster runners over TCP (Effect's ``NodeClusterSocket``).

``layer()`` is a whole runner: a ``SocketServer`` at the configured
``runner_listen_address`` (or ``runner_address``), other runners dialed
over TCP, runner health by ping (or Kubernetes), messages and shard locks
in SQL (``storage="sql"``, the default, needing a ``SqlClient``), in
memory (``"local"``) or brought by the caller (``"byo"``), and settings
read from the environment and passed through ``sharding_config``.
``client_only=True`` serves nothing and owns no shards.

Messages are ``SchemaBinary`` frames, as in Effect; ``serialization="ndjson"``
writes ndjson instead. ``serialization_max_buffer_size`` limits a frame of
either.
"""

from __future__ import annotations

from typing import Any, Literal, Never, overload

from pyfect import layer as layer_
from pyfect.cluster import socket_runner
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
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import RpcClientProtocol, RpcClientProtocolService, Runners
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.config import ConfigError
from pyfect.effect import Effect, die, gen, provide_service
from pyfect.layer import Layer
from pyfect.rpc.client import ClientProtocolService, make_protocol_socket
from pyfect.rpc.serialization import MaxBufferSize, RpcSerialization
from pyfect.scope import Scope
from pyfect.socket import Socket, make_net
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer, SocketServerError
from pyfect.sql.client import SqlClient

_OPEN_TIMEOUT = "1 second"


@gen
def _client_protocol():
    serialization = yield from RpcSerialization()

    def make_protocol(address: RunnerAddress) -> Effect[ClientProtocolService, Never, Scope]:
        socket = make_net(address.port, address.host, open_timeout=_OPEN_TIMEOUT)
        return (
            make_protocol_socket()
            .pipe(provide_service(Socket, socket))
            .pipe(provide_service(RpcSerialization, serialization))
        )

    return RpcClientProtocolService(make=make_protocol, codec_for=serialization.codec_for)


layer_client_protocol: Layer[RpcClientProtocol, Never, RpcSerialization] = layer_.effect(
    RpcClientProtocol, _client_protocol
)
"""Dial other runners over TCP (one second to connect)."""


@gen
def _socket_server():
    config = yield from ShardingConfig()
    listen = config.runner_listen_address or config.runner_address
    if listen is None:
        return (
            yield from die(
                RuntimeError("layerSocketServer: ShardingConfig.runnerListenAddress is None")
            )
        )
    return socket_server.layer(listen.port, listen.host)


layer_socket_server: Layer[SocketServer, SocketServerError, ShardingConfig] = layer_.unwrap(
    _socket_server
)
"""A ``SocketServer`` at the runner's listen address."""


type _Out = Sharding | Runners | MessageStorage
type _Core = Sharding | Runners


@overload
def layer(
    *,
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
    client_only: Literal[True],
    storage: Literal["sql"] = "sql",
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, ConfigError, SqlClient]: ...
@overload
def layer(
    *,
    client_only: Literal[True],
    storage: Literal["local"],
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Out, ConfigError]: ...
@overload
def layer(
    *,
    client_only: Literal[True],
    storage: Literal["byo"],
    serialization: SerializationKind = ...,
    serialization_max_buffer_size: MaxBufferSize = ...,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[_Core, ConfigError, MessageStorage | RunnerStorage]: ...
def layer(
    *,
    client_only: bool = False,
    storage: Storage = "sql",
    runner_health: Health = "ping",
    runner_health_k8s_namespace: str | None = None,
    runner_health_k8s_label_selector: str | None = None,
    serialization: SerializationKind = "binary",
    serialization_max_buffer_size: MaxBufferSize = 16 * 1024 * 1024,
    sharding_config: ShardingConfigUpdate | None = None,
) -> Layer[Any, Any, Any]:
    """A cluster runner (or, with ``client_only``, a sender) over TCP."""
    transport: Layer[Any, Any, Any] = (
        socket_runner.layer_client_only.pipe(layer_.provide(layer_client_protocol))
        if client_only
        else socket_runner.layer.pipe(
            layer_.provide(layer_.merge(layer_socket_server, layer_client_protocol))
        )
    )
    health = (
        None
        if client_only
        else runner_health_layer(
            client_protocol=layer_client_protocol,
            health=runner_health,
            namespace=runner_health_k8s_namespace,
            label_selector=runner_health_k8s_label_selector,
        )
    )
    return assemble(
        transport,
        health=health,
        storage=storage,
        sharding_config=sharding_config,
        serialization_kind=serialization,
        serialization_max_buffer_size=serialization_max_buffer_size,
    )


__all__ = ["layer", "layer_client_protocol", "layer_k8s_http_client", "layer_socket_server"]
