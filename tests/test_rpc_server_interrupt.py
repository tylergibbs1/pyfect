"""A request interrupted right after it arrives still runs its handler's
cleanup: Effect's server starts the handler fiber synchronously
(``runForkWith`` evaluates it at once), so an ``Interrupt`` handled next
finds the handler's ``on_interrupt`` and finalizers in place.

A process worker buffers messages until the child is ready and then hands
them over together, so the ``Never`` request and its ``Interrupt`` reach the
server in one batch: the flake of ``test_never[e2e worker process]``."""

import pyfect as fx
from pyfect import effect
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import server as rpc_server
from pyfect.rpc.message import Interrupt, Request


class Pending(RpcGroup):
    never = make("Never")


def test_an_interrupt_right_after_its_request_runs_the_handlers_cleanup() -> None:
    def body():
        cleaned: list[str] = []
        handlers = Pending.to_layer(
            Pending.handlers().handle(Pending.never)(
                lambda _: effect.never.on_interrupt(effect.sync(lambda: cleaned.append("never")))
            )
        )
        server = yield from rpc_server.make_no_serialization(
            Pending, lambda _response: effect.succeed(None)
        ).pipe(fx.provide(handlers))
        yield from server.write(1, Request("1", "Never", None))
        yield from server.write(1, Interrupt("1"))
        for _ in range(20):
            yield from effect.yield_now()
        return cleaned

    assert fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die()) == ["never"]
