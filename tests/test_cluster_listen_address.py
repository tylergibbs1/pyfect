"""Where ``cluster_socket.layer_socket_server`` and
``cluster_http.layer_http_server`` listen, read from Effect's
``NodeClusterSocket`` / ``NodeClusterHttp``: at ``runner_listen_address``
when it is set, else at ``runner_address``, and a defect when neither is."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cluster import cluster_http, cluster_socket, runner_address, sharding_config
from pyfect.cluster.sharding_config import DEFAULTS
from pyfect.http.server import HttpServer
from pyfect.layer import Layer
from pyfect.net.net_address import InetAddressV4
from pyfect.socket.server import SocketServer

# Port 1 is privileged: binding it fails, so a server that listens there
# instead of at the listen address fails the test.
UNBINDABLE = runner_address.make("127.0.0.1", 1)
FREE = runner_address.make("127.0.0.1", 0)


def _address_of(
    server_layer: Layer[Any, Any, Any], address: fx.Effect[Any, Never, Any]
) -> fx.Effect[Any, Any]:
    return fx.scoped(
        address.pipe(fx.provide(server_layer)).pipe(
            fx.provide(
                sharding_config.layer(
                    replace(DEFAULTS, runner_address=UNBINDABLE, runner_listen_address=FREE)
                )
            )
        )
    )


@testing.live
def test_the_socket_server_listens_at_the_listen_address():
    address = yield from _address_of(
        cluster_socket.layer_socket_server, SocketServer().map(lambda server: server.address)
    )
    assert isinstance(address, InetAddressV4)
    assert address.port not in (0, 1)


@testing.live
def test_the_http_server_listens_at_the_listen_address():
    address = yield from _address_of(
        cluster_http.layer_http_server, HttpServer().map(lambda server: server.address)
    )
    assert isinstance(address, InetAddressV4)
    assert address.port not in (0, 1)


@pytest.mark.parametrize(
    ("server_layer", "message"),
    [
        (
            cluster_socket.layer_socket_server,
            "layerSocketServer: ShardingConfig.runnerListenAddress is None",
        ),
        (
            cluster_http.layer_http_server,
            "NodeClusterHttp.layerHttpServer: ShardingConfig.runnerAddress is None",
        ),
    ],
)
@testing.live
def test_a_server_without_an_address_dies(server_layer: Layer[Any, Any, Any], message: str):
    exit = yield from (
        fx.scoped(server_layer.build())
        .pipe(fx.provide(sharding_config.layer(replace(DEFAULTS, runner_address=None))))
        .exit()
    )
    assert isinstance(exit, fx.exit.Failure)
    defect = exit.cause.squash()
    assert str(defect) == message
