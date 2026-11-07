"""Every API whose result can outlive a layer provided only to its
construction fails the first use after release with its typed error
(DOGFOOD trawl 1 and 2): RPC clients over a released protocol, the in-memory
RPC client over released handlers, and the thread-backed services those
handlers hold (SQLite, the httpx client, redis-py).

Each case goes through ``assert_fails_after_release``; a new API of this kind
gets a case here.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any

import pytest
from _use_after_release import assert_fails_after_release
from oracle import _redis

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect.http import client as http_client
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError
from pyfect.http_api import HttpApi, HttpApiGroup, endpoint, get_group
from pyfect.http_api import client as api_client
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, RpcRequest, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import test as rpc_test
from pyfect.rpc.client_error import RpcClientError
from pyfect.socket import Reader, Socket, Writer
from pyfect.socket import make as socket_make
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform, WorkerPlatformService


class Calls(RpcGroup):
    ping = make("Ping", success=S.String)


class Rows(RpcGroup):
    count = make("Count", success=S.Int, error=SqlError)


def _no_server(request: Any, *_: object) -> Any:
    return effect.die(AssertionError(f"nothing should be sent: {request}"))


def test_an_rpc_client_over_a_released_http_protocol() -> None:
    protocol = (
        rpc_client.layer_protocol_http("http://localhost/rpc")
        .pipe(layer.provide(rs.layer_json))
        .pipe(layer.provide(layer.succeed(HttpClient, http_client.make(_no_server))))
    )
    assert_fails_after_release(
        protocol, lambda: rpc_client.make(Calls), lambda client: client.ping(), RpcClientError
    )


def test_an_rpc_client_over_a_released_batched_http_protocol() -> None:
    protocol = (
        rpc_client.layer_protocol_http(
            "http://localhost/rpc", batch=rpc_client.Batch(window="10 millis")
        )
        .pipe(layer.provide(rs.layer_json))
        .pipe(layer.provide(layer.succeed(HttpClient, http_client.make(_no_server))))
    )
    assert_fails_after_release(
        protocol, lambda: rpc_client.make(Calls), lambda client: client.ping(), RpcClientError
    )


def test_an_rpc_client_over_a_released_worker_protocol() -> None:
    def send(message: Any, _transfers: Any) -> fx.Effect[None]:
        return effect.die(AssertionError(f"nothing should be sent: {message}"))

    backing = Worker[Any, Any](send=send, run=lambda _handler, _on_spawn: fx.never)
    protocol = (
        rpc_client.layer_protocol_worker(size=1)
        .pipe(
            layer.provide(
                layer.succeed(
                    WorkerPlatform, WorkerPlatformService(lambda _: effect.succeed(backing))
                )
            )
        )
        .pipe(layer.provide(layer.succeed(Spawner, lambda _: None)))
    )
    assert_fails_after_release(
        protocol, lambda: rpc_client.make(Calls), lambda client: client.ping(), RpcClientError
    )


def _memory_socket() -> fx.Effect[Any]:
    def body():
        frames = yield from Queue[str].unbounded()
        return socket_make(
            effect.succeed(Reader(frames.take().map(lambda frame: (frame,)))),
            effect.succeed(Writer(lambda _data: effect.void, lambda _chunks: effect.void)),
        )

    return effect.gen(body)


def test_an_rpc_client_over_a_released_socket_protocol() -> None:
    protocol = (
        rpc_client.layer_protocol_socket()
        .pipe(layer.provide(rs.layer_json))
        .pipe(layer.provide(layer.effect(Socket, _memory_socket())))
    )
    assert_fails_after_release(
        protocol, lambda: rpc_client.make(Calls), lambda client: client.ping(), RpcClientError
    )


def _sqlite(tmp_path: Path) -> fx.Layer[Any, Any, Any]:
    return sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "rows.db")))


def _select_one():
    sql = yield from SqlClient()
    return (yield from sql("SELECT 1 AS one"))


def test_a_released_sqlite_client(tmp_path: Path) -> None:
    error = assert_fails_after_release(
        _sqlite(tmp_path), SqlClient, lambda sql: sql("SELECT 1"), SqlError
    )
    assert isinstance(error, SqlError)
    assert "SQLite connection is closed" in error.message


def _count(_request: RpcRequest[None]) -> fx.Effect[int, SqlError, SqlClient]:
    return effect.gen(_select_one).map(len)


def test_the_in_memory_rpc_client_over_handlers_on_a_released_database(tmp_path: Path) -> None:
    """DOGFOOD trawl 2: the handlers' SQLite client is released with their
    layer; the call fails with the handler's typed ``SqlError``, not a
    ``RuntimeError`` from the connection's stopped worker thread."""
    handlers = Rows.to_layer(Rows.handlers().handle(Rows.count)(_count)).pipe(
        layer.provide(_sqlite(tmp_path))
    )
    assert_fails_after_release(
        handlers, lambda: rpc_test.make_client(Rows), lambda client: client.count(), SqlError
    )


def test_a_released_httpx_client() -> None:
    assert_fails_after_release(
        httpx_client.layer,
        HttpClient,
        lambda http: http.get("http://127.0.0.1:9/never"),
        HttpClientError,
    )


class Health(HttpApiGroup, identifier="health"):
    check = endpoint.get("check", "/health", success=S.String)


def test_an_http_api_client_over_a_released_httpx_client() -> None:
    api = HttpApi.make("health").add(Health)
    assert_fails_after_release(
        httpx_client.layer,
        lambda: api_client.make(api, base_url="http://127.0.0.1:9"),
        lambda client: get_group(client, Health).check(),
        HttpClientError,
    )


def test_a_released_redis_py_client() -> None:
    pytest.importorskip("redis")
    from pyfect.persistence import redis_py

    server = _redis.server()
    error = assert_fails_after_release(
        redis_py.layer(server.url),
        redis_py.RedisPy,
        lambda client: client.use(lambda redis: redis.ping()),
        redis_py.RedisError,
    )
    assert "Redis client is closed" in repr(error)
