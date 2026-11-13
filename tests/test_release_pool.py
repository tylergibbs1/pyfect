"""Pools, servers and connections let go of what they handled once the run
ends, without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

import gc
from typing import Any

from _closure_release import Handled, assert_freed_after_run
from _gc_census import tracked_of
from oracle._ai_http import MockHttp
from oracle._graphql import FakeWebSocket
from oracle._mcp_rpc import custom_transport, request

import pyfect as fx
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.dispatch import Connection
from pyfect.ai.openai import client as openai_client
from pyfect.deferred import Deferred
from pyfect.persistence import redis as R
from pyfect.persistence.redis import RedisError
from pyfect.queue import Queue
from pyfect.redacted import make as redact
from pyfect.rpc import server as rpc_server
from pyfect.socket import WebSocketConstructor


def test_pool_use_frees_its_function_after_waiting_for_an_item() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any, Any]:
        def program():
            pool = yield from fx.Pool.make(fx.yield_now().as_(1), size=1)
            yield from pool.use(lambda _: fx.succeed(v))

        return fx.scoped(fx.gen(program))

    assert_freed_after_run(build)


def _never_subscribe(
    _channel: str, _on_message: Any
) -> fx.Effect[fx.Effect[None, RedisError], RedisError, fx.Scope]:
    return fx.succeed(fx.never)


def _unused_send(_command: str, *_args: str) -> fx.Effect[R.RedisReply, RedisError]:
    return fx.die(RuntimeError("unused"))


def test_redis_frees_a_reserved_connection_once_closed() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any, Any]:
        def opened() -> R.OpenConnection:
            return R.OpenConnection(
                send=lambda command, *_args: fx.succeed(v.label or command), close=fx.void
            )

        def program():
            redis = yield from R.make(
                send=_unused_send, subscribe=_never_subscribe, connect=fx.sync(opened)
            )
            yield from fx.scoped(redis.reserve.flat_map(lambda c: c.send("PING")))

        return fx.scoped(fx.gen(program))

    assert_freed_after_run(build)


def test_mcp_over_an_rpc_protocol_frees_a_session_that_ended() -> None:
    def program():
        transport = yield from custom_transport()
        served = M.layer_rpc_protocol(
            name="Release", version="1.0.0", protocols=[P.v2025_11_25]
        ).pipe(fx.provide(fx.layer.succeed(rpc_server.ServerProtocol, transport.protocol)))
        yield from served.build()
        write = yield from transport.ready.wait()
        initialize = {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "client", "version": "1"},
        }
        yield from write(1, request(1, "initialize", initialize))
        assert (yield from transport.outbound.take())[1]["_tag"] == "Exit"
        yield from write(1, {"_tag": "Eof"})
        # The session ends on a daemon fiber once its requests are answered.
        yield from fx.sleep("50 millis")

    gc.collect()
    before = len(tracked_of(Connection))
    gc.disable()
    try:
        fx.run_blocking(fx.scoped(fx.gen(program)).or_die())
        assert len(tracked_of(Connection)) == before, "an ended session is still held"
    finally:
        gc.enable()


class _DroppingWebSocket(FakeWebSocket):
    """An in-memory WebSocket that drops its listeners once closed."""

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        super().close(code, reason)
        self.listeners = []


def test_openai_web_socket_mode_frees_its_http_client() -> None:
    def build(v: Handled) -> fx.Effect[Any, Any, Any]:
        def construct(_url: str, _options: Any) -> FakeWebSocket:
            return _DroppingWebSocket(Queue(), Deferred())

        mock = MockHttp(lambda _request: fx.die(RuntimeError(v.label)))
        return (
            fx.scoped(openai_client.layer_web_socket_mode().build().as_void())
            .pipe(fx.provide(openai_client.layer(api_key=redact("sk-test"))))
            .pipe(fx.provide(mock.layer))
            .pipe(fx.provide_service(WebSocketConstructor, construct))
        )

    assert_freed_after_run(build)
