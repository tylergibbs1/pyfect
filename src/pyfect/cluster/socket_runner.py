"""A cluster runner whose RPCs travel over a ``SocketServer`` (Effect's
``SocketRunner``).

``layer`` serves the runner protocol on the ``SocketServer`` in the
context, logs where it listens, and provides ``Sharding`` and ``Runners``;
calls to other runners go through the ``RpcClientProtocol`` in the context
(``cluster_socket.layer_client_protocol`` dials them over TCP).
``layer_client_only`` joins the cluster as a sender only."""

from __future__ import annotations

from typing import Never

from pyfect import layer as layer_
from pyfect.cluster import runner_server
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import RpcClientProtocol, Runners
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.effect import gen
from pyfect.layer import Layer
from pyfect.logger import log_info
from pyfect.net.net_address import UnixPathAddress, format_inet
from pyfect.rpc.serialization import RpcSerialization
from pyfect.rpc.server import layer_protocol_socket_server
from pyfect.socket.server import SocketServer


@gen
def _log_address():
    server = yield from SocketServer()
    address = server.address
    formatted = address.path if isinstance(address, UnixPathAddress) else format_inet(address)
    yield from log_info(f"Listening on: {formatted}").annotate_logs(
        {"package": "@effect/cluster", "service": "Runner"}
    )


layer: Layer[
    Sharding | Runners,
    Never,
    RpcClientProtocol
    | ShardingConfig
    | RpcSerialization
    | SocketServer
    | MessageStorage
    | RunnerStorage
    | RunnerHealth,
] = (
    layer_.effect_discard(_log_address)
    .pipe(layer_.provide_merge(runner_server.layer_with_clients))
    .pipe(layer_.provide(layer_protocol_socket_server))
)
"""A runner serving the runner protocol on the ``SocketServer``, with its
``Sharding`` and ``Runners`` (Effect's ``SocketRunner.layer``)."""

layer_client_only: Layer[
    Sharding | Runners,
    Never,
    RpcClientProtocol | ShardingConfig | MessageStorage | RunnerStorage,
] = runner_server.layer_client_only
"""``Sharding`` and ``Runners`` of a process that only sends to the
cluster (Effect's ``SocketRunner.layerClientOnly``)."""

__all__ = ["layer", "layer_client_only"]
