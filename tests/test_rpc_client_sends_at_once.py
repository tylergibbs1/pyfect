"""An RPC client call writes its request before the calling fiber goes on,
as Effect's client does (``runForkWith`` runs the send synchronously).
Sharding relies on it: requests forked together reach storage before the
storage loop, woken by the first, reads it."""

from __future__ import annotations

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.latch import Latch
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc.message import Request


class Group(RpcGroup):
    ping = make("Ping", success=S.String)


@testing.effect
def test_calls_forked_together_send_before_a_fiber_they_wake_runs():
    sent: list[str] = []
    seen: list[int] = []
    wake = Latch()

    def on_from_client(options: rpc_client.OnFromClient) -> fx.Effect[None]:
        if not isinstance(options.message, Request):
            return fx.void
        sent.append(options.message.tag)
        # Like a storage notification: the waiter runs on a later turn.
        return wake.open().as_void()

    @fx.gen
    def body():
        client, _ = yield from rpc_client.make_no_serialization(Group, on_from_client)
        yield from (
            wake.wait()
            .and_then(fx.sync(lambda: seen.append(len(sent))))
            .fork(start_immediately=True)
        )
        yield from client.ping().fork(start_immediately=True)
        yield from client.ping().fork(start_immediately=True)
        yield from fx.yield_now()

    yield from fx.scoped(body)
    assert seen == [2]
