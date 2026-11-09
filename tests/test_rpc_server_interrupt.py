"""A request interrupted right after it arrives still runs its handler's
cleanup: Effect's server starts the handler fiber synchronously
(``runForkWith`` evaluates it at once), so an ``Interrupt`` handled next
finds the handler's ``on_interrupt`` and finalizers in place.

A process worker buffers messages until the child is ready and then hands
them over together, so the ``Never`` request and its ``Interrupt`` reach the
server in one batch: the flake of ``test_never[e2e worker process]``."""

import pyfect as fx
from pyfect import effect
from pyfect.latch import Latch
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import server as rpc_server
from pyfect.rpc.message import Eof, FromServer, Interrupt, Request


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

    assert fx.run_blocking(fx.scoped(effect.gen(body)).timeout("5 seconds").or_die()) == ["never"]


class Gated(RpcGroup):
    work = make("Work")


def _messages_when_the_handler_signals(follow_up: Interrupt | Eof) -> list[str]:
    """The handler opens a latch as its first step, which runs the fiber
    waiting on it at once, nested in the handler's start (pyfect's and
    Effect's synchronous resume). That fiber writes ``follow_up`` before the
    server's ``write`` of the request has returned."""

    def body():
        seen: list[str] = []
        started = Latch()

        def work(_: object) -> effect.Effect[None]:
            return (
                effect.sync(started.open_unsafe)
                .and_then(fx.sleep("50 millis"))
                .and_then(effect.sync(lambda: seen.append("handler finished")))
                .on_interrupt(effect.sync(lambda: seen.append("handler interrupted")))
            )

        def on_from_server(response: FromServer) -> effect.Effect[None]:
            return effect.sync(lambda: seen.append(type(response).__name__))

        handlers = Gated.to_layer(Gated.handlers().handle(Gated.work)(work))
        server = yield from rpc_server.make_no_serialization(Gated, on_from_server).pipe(
            fx.provide(handlers)
        )
        signal = started.wait().and_then(server.write(0, follow_up))
        ended = yield from signal.fork(start_immediately=True)
        yield from server.write(0, Request("1", "Work", None))
        yield from ended.join()
        yield from fx.sleep("200 millis")
        return seen

    return fx.run_blocking(fx.scoped(effect.gen(body)).timeout("5 seconds").or_die())


def test_eof_written_while_the_handler_starts_waits_for_the_handler() -> None:
    """Effect registers the handler fiber before it runs ("to catch
    synchronous cancellation"), so an ``Eof`` that arrives during its first
    step ends the client only once the handler is done; the cluster's
    drain relies on it (a runner stopped as its entity's job starts)."""
    assert _messages_when_the_handler_signals(Eof()) == [
        "handler finished",
        "ResponseExit",
        "ClientEnd",
    ]


def test_an_interrupt_written_while_the_handler_starts_interrupts_it() -> None:
    assert _messages_when_the_handler_signals(Interrupt("1")) == [
        "handler interrupted",
        "ResponseExit",
        "ClientEnd",  # the server's shutdown, as the scope closes
    ]
