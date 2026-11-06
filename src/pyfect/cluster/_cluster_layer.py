"""What ``cluster_socket.layer`` and ``cluster_http.layer`` share (the
second half of Effect's ``NodeClusterSocket.layer`` /
``NodeClusterHttp.layer``): runner health, storage, settings from the
environment and the serialization around a transport layer."""

from __future__ import annotations

import ssl
from collections.abc import Callable
from typing import Any, Literal

from pyfect import file_system
from pyfect import layer as layer_
from pyfect.cluster import (
    k8s_http_client,
    runner_health,
    runner_storage,
    runners,
    sql_message_storage,
    sql_runner_storage,
)
from pyfect.cluster import message_storage as message_storage_
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.k8s_http_client import K8sHttpClient
from pyfect.cluster.runners import RpcClientProtocol
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.effect import gen, succeed
from pyfect.file_system import FileSystem
from pyfect.http import httpx_client
from pyfect.layer import Layer
from pyfect.rpc import serialization
from pyfect.rpc.serialization import MaxBufferSize, RpcSerialization

type Storage = Literal["local", "sql", "byo"]
type Health = Literal["ping", "k8s"]
type SerializationKind = Literal["binary", "ndjson"]
type ShardingConfigUpdate = Callable[[ShardingConfigService], ShardingConfigService]

_K8S_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


@gen
def _k8s_http_client():
    fs = yield from FileSystem()
    no_ca: str | None = None
    ca = yield from fs.read_file_string(_K8S_CA).catch_all(lambda _: succeed(no_ca))
    if ca is None:
        return httpx_client.layer
    return httpx_client.layer_with(verify=ssl.create_default_context(cadata=ca))


layer_k8s_http_client: Layer[K8sHttpClient] = k8s_http_client.layer.pipe(
    layer_.provide(layer_.unwrap(_k8s_http_client))
).pipe(layer_.provide(file_system.layer))
"""The ``K8sHttpClient`` of a pod: httpx trusting the service account's CA
when it is mounted (Effect's ``layerK8sHttpClient``)."""


def runner_health_layer(
    *,
    client_protocol: Layer[RpcClientProtocol, Any, Any],
    health: Health,
    namespace: str | None,
    label_selector: str | None,
) -> Layer[Any, Any, Any]:
    if health == "k8s":
        return runner_health.layer_k8s(namespace=namespace, label_selector=label_selector).pipe(
            layer_.provide(layer_k8s_http_client)
        )
    return runner_health.layer_ping.pipe(layer_.provide(runners.layer_rpc)).pipe(
        layer_.provide(client_protocol)
    )


def assemble(
    transport: Layer[Any, Any, Any],
    *,
    health: Layer[Any, Any, Any] | None,
    storage: Storage,
    sharding_config: ShardingConfigUpdate | None,
    serialization_kind: SerializationKind,
    serialization_max_buffer_size: MaxBufferSize,
) -> Layer[Any, Any, Any]:
    """``transport`` (a ``Sharding | Runners`` layer) with its runner
    health (``None`` for a client), storage, settings and serialization."""
    with_health = transport if health is None else transport.pipe(layer_.provide(health))
    messages: Layer[Any, Any, Any] = (
        message_storage_.layer_noop
        if storage == "local"
        else layer_.empty
        if storage == "byo"
        else sql_message_storage.layer
    )
    locks: Layer[Any, Any, Any] = (
        runner_storage.layer_memory
        if storage == "local"
        else layer_.empty
        if storage == "byo"
        else sql_runner_storage.layer.or_die()
    )
    wire: Layer[RpcSerialization] = (
        serialization.layer_ndjson_with(max_buffer_size=serialization_max_buffer_size)
        if serialization_kind == "ndjson"
        else serialization.layer_schema_binary(max_frame_size=serialization_max_buffer_size)
    )
    return (
        with_health.pipe(layer_.provide_merge(messages))
        .pipe(layer_.provide(locks))
        .pipe(layer_.provide(sharding_config_.layer_from_env(sharding_config)))
        .pipe(layer_.provide(wire))
    )


__all__ = [
    "Health",
    "SerializationKind",
    "ShardingConfigUpdate",
    "Storage",
    "assemble",
    "layer_k8s_http_client",
    "runner_health_layer",
]
