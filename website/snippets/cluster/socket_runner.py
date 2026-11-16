from dataclasses import replace

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import (
    cluster_socket,
    message_storage,
    runner_address,
    runner_health,
    runner_storage,
    sharding_config,
    socket_runner,
)
from pyfect.cluster.entity import Entity
from pyfect.cluster.sharding_config import DEFAULTS
from pyfect.net.net_address import InetAddressV4
from pyfect.rpc import make as make_rpc
from pyfect.rpc import serialization
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer


class Greeter(Entity, type="Greeter"):
    greet = make_rpc("Greet", payload=S.String, success=S.String)


Greeters = Greeter.to_layer(
    Greeter.handlers().handle(Greeter.greet)(lambda request: fx.succeed(f"hi {request.payload}"))
)

# The runner and the client share storage: in memory here, SQL in production.
Storage = fx.layer.merge(runner_storage.layer_memory, message_storage.layer_memory).pipe(
    fx.layer.provide(sharding_config.layer_defaults)
)


def settings(port: int):
    address = runner_address.make("127.0.0.1", port)
    config = replace(DEFAULTS, runner_address=address, entity_termination_timeout=fx.duration.zero)
    return sharding_config.layer(config)


@fx.fn
def greet(name: str):
    make_client = yield from Greeter.client()
    return (yield from make_client("door").greet(name))


@fx.fn
def program():
    # A server you already have, here on a free port the system picks.
    server = yield from socket_server.make(0, "127.0.0.1")
    assert isinstance(server.address, InetAddressV4)
    port = server.address.port

    # socket_runner.layer serves the runner protocol on the SocketServer in the context.
    runner = (
        Greeters.pipe(fx.layer.provide_merge(socket_runner.layer))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(fx.layer.succeed(SocketServer, server)))
        .pipe(fx.layer.provide(cluster_socket.layer_client_protocol))
        .pipe(fx.layer.provide(settings(port)))
        .pipe(fx.layer.provide(serialization.layer_schema_binary()))
    )
    yield from runner.build()

    # A sender only: it owns no shards and dials the runner over TCP.
    sender = (
        socket_runner.layer_client_only.pipe(fx.layer.provide(cluster_socket.layer_client_protocol))
        .pipe(fx.layer.provide(settings(port)))
        .pipe(fx.layer.provide(serialization.layer_schema_binary()))
    )
    reply = yield from greet("ada").pipe(fx.provide(sender))
    print(reply)


quiet = fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ERROR)
fx.run_main(fx.scoped(program()).pipe(fx.provide(Storage)).pipe(quiet))
