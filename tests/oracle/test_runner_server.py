# pyright: reportCallIssue=false, reportArgumentType=false
"""Ports of Effect's ``test/cluster/RunnerServer.test.ts``. Each test's
docstring is the Effect test title.

Adapted, with the reason: "caller disconnect preserves ... streams" counts
the live subscriptions of the handler's stream itself, where Effect reads
``pubsub.subscribers.size`` (pyfect's ``PubSub`` keeps its subscriber count
private); the stream is subscribed exactly while it runs, as Effect's is.
"""

from __future__ import annotations

import json
from collections.abc import Generator as Generator_
from typing import Any, Never, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cluster import (
    envelope,
)
from pyfect.cluster.cluster_error import MailboxFull
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity import Entity, EntityHandlers, Request
from pyfect.cluster.message import IncomingEnvelope
from pyfect.cluster.message_storage import MemoryDriver
from pyfect.cluster.runners import Rpcs
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.snowflake import Generator, Snowflake
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.rpc import fork, rpc_schema
from pyfect.rpc import make as make_rpc
from pyfect.rpc.test import make_client
from pyfect.scope import CloseableScope

from ._runner_server_handlers import (
    codec_for_json_string,
    incoming,
    live_timeout,
    make_handlers,
    make_request,
    make_server,
    write_request,
)


class IdPayload(TypedDict):
    id: int


class ReproEntity(Entity, type="ReproRunnerServer"):
    repro_stream = make_rpc(
        "ReproStream", success=rpc_schema.Stream(S.Int, S.Never), payload=S.Struct(IdPayload)
    )


ReproEntityVolatile = ReproEntity.annotate_rpcs(Persisted, False)


class HoleCodecEntity(Entity, type="HoleCodecEntity"):
    double = make_rpc("Double", success=S.Int, payload=S.Struct(IdPayload))


HoleCodecEntityVolatile = HoleCodecEntity.annotate_rpcs(Persisted, False)


@testing.effect
def test_completes_a_successful_runner_stream():
    """completes a successful runner stream"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        ids = yield from Generator()
        request = yield from make_request(ReproEntityVolatile, "one")
        client = yield from make_client(Rpcs)
        queue = yield from client.stream({"request": request, "persisted": False}, as_queue=True)
        first = yield from live_timeout(queue.take())
        assert first["_tag"] == "Chunk", "expected the stream value before the terminal reply"
        chunk = cast("dict[str, Any]", first)
        assert list(chunk["values"]) == [1]
        yield from client.envelope(
            {
                "envelope": envelope.AckChunk(
                    id=ids.next_unsafe(),
                    address=request.address,
                    request_id=request.request_id,
                    reply_id=Snowflake(int(chunk["id"])),
                ),
                "persisted": False,
            }
        )

        @fx.gen
        def completion():
            last = yield from queue.take()
            yield from queue.take().pipe(fx.catch_tag(Done, lambda _: fx.void))
            return last

        last = yield from live_timeout(completion)
        assert last["_tag"] == "WithExit"

    entities = ReproEntityVolatile.to_layer(
        ReproEntityVolatile.handlers().handle(ReproEntityVolatile.repro_stream)(
            lambda _: stream.make(1)
        )
    )
    yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))


@testing.effect
def test_releases_a_non_persisted_effect_handler_when_the_runner_caller_disconnects():
    """releases a non-persisted Effect handler when the runner caller disconnects"""

    @fx.gen
    def outer():
        started = yield from Deferred[None, Never].make()
        stopped = yield from Deferred[None, Never].make()

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            request = yield from make_request(
                HoleCodecEntityVolatile, "effect-disconnect", tag="Double"
            )
            server = yield from make_server()
            yield from write_request(server, "Effect", request)
            yield from testing.adjust("1 millis")
            assert (yield from started.is_done())
            assert not (yield from stopped.is_done())
            yield from server.disconnect(0)
            yield from testing.adjust("1 millis")
            assert (yield from stopped.is_done())

        e = HoleCodecEntityVolatile
        entities = e.to_layer(
            e.handlers().handle(e.double)(
                lambda _: fork(
                    started.succeed(None).and_then(fx.never).ensuring(stopped.succeed(None))
                )
            )
        )
        yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))

    yield from outer


@testing.effect
def test_forgets_departed_callers_during_rebuild_without_replaying_or_retaining_mailbox_slots():
    """forgets departed callers during rebuild without replaying or retaining mailbox slots"""

    @fx.gen
    def outer():
        rebuilding = yield from Deferred[None, Never].make()
        release_build = yield from Deferred[None, Never].make()
        starts: list[int] = []
        builds = [0]
        e = ReproEntityVolatile

        def repro_stream(request: Request[IdPayload]) -> Any:
            starts.append(request.payload["id"])
            return fork(
                stream.die(RuntimeError("trigger entity rebuild"))
                if len(starts) == 1
                else stream.never
            )

        @fx.gen
        def build() -> Generator_[Any, Any, EntityHandlers[Any, Never]]:
            builds[0] += 1
            if builds[0] == 2:
                yield from rebuilding.succeed(None)
                yield from release_build.wait()
            return e.handlers().handle(e.repro_stream)(repro_stream)

        entities = e.to_layer_effect(build, mailbox_capacity=2)

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            service = yield from Sharding()
            server = yield from make_server()

            def request(id_: int) -> fx.Effect[envelope.PartialRequest, Never, Any]:
                return make_request(e, "mailbox-during-rebuild", payload={"id": id_})

            def send(client_id: int, id_: int) -> fx.Effect[None, Never, Any]:
                return request(id_).flat_map(
                    lambda r: write_request(server, "Stream", r, client_id=client_id)
                )

            def probe(id_: int) -> fx.Effect[None, Any, Any]:
                return request(id_).flat_map(lambda r: service.send(incoming(r)))

            yield from send(0, 1)
            yield from testing.adjust("5 seconds")
            assert (yield from rebuilding.is_done())
            yield from send(1, 2)
            yield from testing.adjust("1 millis")
            assert starts == [1]

            # A and B fill both slots, proving B was admitted before its disconnect.
            full = yield from probe(3).flip()
            assert isinstance(full, MailboxFull)
            yield from live_timeout(server.disconnect(0))
            yield from live_timeout(server.disconnect(1))
            assert not (yield from release_build.is_done())
            yield from release_build.succeed(None)
            yield from testing.adjust("1 millis")
            assert starts == [1]

            # Both the interrupted handler and the never-delivered request
            # release their slots. Neither may run again when the rebuild
            # finishes.
            yield from probe(3)
            yield from probe(4)
            yield from testing.adjust("1 millis")
            assert starts == [1, 3, 4]

        yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))

    yield from outer


@testing.effect
def test_releases_a_replayed_handler_when_its_caller_disconnects_during_acquisition():
    """releases a replayed handler when its caller disconnects during acquisition"""

    @fx.gen
    def outer():
        caller_scope = yield from fx.acquire_release(
            fx.sync(CloseableScope), lambda scope, _: scope.close(Exit.succeed(None))
        )
        crash = yield from Deferred[None, Never].make()
        replaying = yield from Deferred[None, Never].make()
        disconnected = yield from Deferred[None, Never].make()
        counts = {"starts": 0, "stops": 0, "crashes": 0}
        e = ReproEntityVolatile

        def stopped() -> None:
            counts["stops"] += 1

        def repro_stream(request: Request[IdPayload]) -> Any:
            if request.payload["id"] == 1:
                counts["starts"] += 1
                invocation = counts["starts"]

                @fx.gen
                def run():
                    if invocation == 2:
                        yield from replaying.succeed(None)
                    return (yield from fx.never)

                return fork(stream.from_effect(run).ensuring(fx.sync(stopped)))
            counts["crashes"] += 1
            if counts["crashes"] == 1:
                return fork(
                    stream.from_effect(
                        crash.wait().and_then(fx.die(RuntimeError("trigger entity rebuild")))
                    )
                )
            return fork(stream.never)

        entities = e.to_layer(e.handlers().handle(e.repro_stream)(repro_stream))

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            service = yield from Sharding()

            def request(id_: int) -> fx.Effect[envelope.PartialRequest, Never, Any]:
                return make_request(e, "disconnect-during-replay", payload={"id": id_})

            yield from service.send(incoming((yield from request(1)), caller_scope))
            yield from service.send(incoming((yield from request(2))))
            yield from testing.adjust("1 millis")
            assert counts["starts"] == 1
            assert counts["stops"] == 0

            # Close from another fiber as soon as the replacement handler
            # starts, while the entity is still acquiring and replaying its
            # requests.
            yield from (
                replaying.wait()
                .and_then(caller_scope.close(Exit.succeed(None)))
                .and_then(disconnected.succeed(None))
                .fork(start_immediately=True)
            )
            yield from crash.succeed(None)
            yield from testing.adjust("5 seconds")
            assert counts["starts"] == 2
            assert (yield from disconnected.is_done())
            # Both the original handler and its replacement must release resources.
            assert counts["stops"] == 2

        yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))

    yield from fx.scoped(outer)


@testing.effect
def test_does_not_admit_a_request_with_an_already_closed_caller_scope():
    """does not admit a request with an already-closed caller scope"""
    starts = [0]
    e = ReproEntityVolatile

    def repro_stream(_: Request[IdPayload]) -> Any:
        starts[0] += 1
        return fork(stream.never)

    entities = e.to_layer(e.handlers().handle(e.repro_stream)(repro_stream), mailbox_capacity=1)

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from Sharding()
        caller_scope = CloseableScope()
        yield from caller_scope.close(Exit.succeed(None))
        closed = incoming((yield from make_request(e, "closed-scope")), caller_scope)
        yield from service.send(closed).exit()
        yield from testing.adjust("1 millis")
        assert starts[0] == 0
        # A live request must still fit in the only mailbox slot.
        live = incoming((yield from make_request(e, "closed-scope")))
        admitted = yield from service.send(live).exit()
        assert isinstance(admitted, Exit.Success)
        yield from testing.adjust("1 millis")
        assert starts[0] == 1

    yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))


@pytest.mark.parametrize("persisted", [False, True], ids=["Uninterruptible", "persisted"])
@testing.effect
def test_caller_disconnect_preserves_streams(persisted: bool):
    """caller disconnect preserves ${persisted ? "persisted" : "Uninterruptible"} streams"""
    subscribers = [0]
    entity = (
        ReproEntityVolatile.annotate_rpcs(Persisted, True)
        if persisted
        else ReproEntityVolatile.annotate_rpcs(Uninterruptible, True)
    )

    def subscribe() -> stream.Stream[int]:
        subscribers[0] += 1

        def unsubscribe() -> None:
            subscribers[0] -= 1

        return stream.never.ensuring(fx.sync(unsubscribe))

    entities = entity.to_layer(
        entity.handlers().handle(entity.repro_stream)(
            lambda _: fork(stream.unwrap(fx.sync(subscribe)))
        )
    )

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        request = yield from make_request(entity, "protected-caller")
        if persisted:
            driver = yield from MemoryDriver()
            yield from driver.encoded.save_envelope(envelope.encode(request), None, None)
        server = yield from make_server()
        yield from write_request(server, "Stream", request, persisted=persisted)
        yield from testing.adjust("1 millis")
        assert subscribers[0] == 1
        yield from server.disconnect(0)
        yield from testing.adjust("1 millis")
        assert subscribers[0] == 1

        if not persisted:
            # An exemption from caller cleanup must not block explicit interrupts.
            service = yield from Sharding()
            ids = yield from Generator()
            yield from service.send(
                IncomingEnvelope(
                    envelope=envelope.Interrupt(
                        id=ids.next_unsafe(),
                        address=request.address,
                        request_id=request.request_id,
                    )
                )
            )
            yield from testing.adjust("1 millis")
            assert subscribers[0] == 0

    yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities)))


@testing.effect
def test_fills_the_entity_payload_and_reply_holes_with_the_serializations_codec():
    """fills the entity payload and reply holes with the serialization's codec"""
    e = HoleCodecEntityVolatile
    entities = e.to_layer(
        e.handlers().handle(e.double)(lambda request: fx.succeed(request.payload["id"] * 2))
    )

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        # already encoded by the sender with the same hole codec
        request = yield from make_request(e, "hole", tag="Double", payload=json.dumps({"id": 21}))
        client = yield from make_client(Rpcs)
        reply = yield from live_timeout(client.effect({"request": request, "persisted": False}))
        assert isinstance(reply, str), "the reply hole must carry the codec's output"
        decoded = json.loads(reply)
        assert decoded["_tag"] == "WithExit"
        assert decoded["exit"] == {"_tag": "Success", "value": 42}

    yield from fx.scoped(body).pipe(fx.provide(make_handlers(entities, codec_for_json_string)))
