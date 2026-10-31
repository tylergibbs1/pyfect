"""A unary call tells the server it was interrupted whenever its result is an
interruption, as Effect's client (``Effect.onInterrupt`` around the call):
when the caller is interrupted, when the client closes under it, and when
the server's own exit is an interruption. The ``Interrupt`` carries the
interruptors. Expected values are from Effect's ``RpcClient`` under Node."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect._fiber import Fiber
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc.message import Interrupt, Request, ResponseExit
from pyfect.scope import CloseableScope, Scope


class Group(RpcGroup):
    ping = make("Ping", success=S.String)
    count = make("Count", success=S.Int, stream=True)


def _recorder(log: list[Any]) -> Callable[[rpc_client.OnFromClient], fx.Effect[None]]:
    def on_from_client(options: rpc_client.OnFromClient) -> fx.Effect[None]:
        return fx.sync(lambda: log.append(options.message))

    return on_from_client


def _interrupts(log: list[Any]) -> list[tuple[int, ...]]:
    return [m.interruptors for m in log if isinstance(m, Interrupt)]


@testing.effect
def test_closing_the_client_sends_an_interrupt_for_a_waiting_call():
    log: list[Any] = []
    scope = CloseableScope()
    client, _ = yield from rpc_client.make_no_serialization(Group, _recorder(log)).pipe(
        fx.provide_service(Scope, scope)
    )
    fiber = yield from client.ping().fork(start_immediately=True)
    me = Fiber.get_current()
    assert me is not None
    yield from scope.close(Exit.succeed(None))
    exit = yield from fiber.await_exit()
    assert isinstance(exit, Exit.Failure) and exit.cause.has_interrupts_only
    assert _interrupts(log) == [(me.id,)]


@testing.effect
def test_an_interrupted_exit_from_the_server_sends_an_interrupt():
    log: list[Any] = []

    @fx.gen
    def body():
        client, core = yield from rpc_client.make_no_serialization(Group, _recorder(log))
        fiber = yield from client.ping().fork(start_immediately=True)
        request = next(m for m in log if isinstance(m, Request))
        yield from core.write(ResponseExit(0, request.id, Exit.interrupt(7)))
        exit = yield from fiber.await_exit()
        assert isinstance(exit, Exit.Failure) and exit.cause.has_interrupts_only
        assert _interrupts(log) == [(7,)]

    yield from fx.scoped(body)


@testing.effect
def test_interrupting_the_caller_sends_its_interruptor():
    log: list[Any] = []

    @fx.gen
    def body():
        client, _ = yield from rpc_client.make_no_serialization(Group, _recorder(log))
        fiber = yield from client.ping().fork(start_immediately=True)
        me = Fiber.get_current()
        assert me is not None
        yield from fiber.interrupt()
        assert _interrupts(log) == [(me.id,)]

    yield from fx.scoped(body)


@testing.effect
def test_closing_a_stream_scope_sends_its_interruptors():
    log: list[Any] = []

    @fx.gen
    def body():
        client, _ = yield from rpc_client.make_no_serialization(Group, _recorder(log))
        scope = CloseableScope()
        yield from client.count(as_queue=True).pipe(fx.provide_service(Scope, scope))
        yield from scope.close(Exit.interrupt(9))
        assert _interrupts(log) == [(9,)]

    yield from fx.scoped(body)
