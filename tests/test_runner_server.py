"""``runner_server.layer_handlers`` against a sharding that answers each
message itself: what the handlers hand to ``Sharding`` and what they send
back to the calling runner. (Effect's own RunnerServer tests need
``Sharding.layer``; see ``tests/oracle/test_runner_server.py``.)"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import envelope, message_storage, runner_server, snowflake
from pyfect.cluster.cluster_error import AlreadyProcessingMessage, EntityNotAssignedToRunner
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import Incoming, IncomingEnvelope, IncomingRequest
from pyfect.cluster.reply import Chunk, ReplyWithContext, WithExit
from pyfect.cluster.runners import Rpcs
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.snowflake import Generator, Snowflake, SnowflakeGenerator
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.rpc import make as make_rpc
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.server import ServerProtocol, ServerProtocolService
from pyfect.rpc.test import make_client

Double = make_rpc("Double", success=S.Int)
Count = make_rpc("Count", success=S.Int, stream=True)

type _Answer = Callable[[IncomingRequest], fx.Effect[None, Any]]


def _no_answer(_: IncomingRequest) -> fx.Effect[None]:
    return fx.void


@dataclass
class _Sharding:
    """Records what it is handed; answers requests with ``answer``."""

    answer: _Answer = _no_answer
    notify_error: Any = None
    sent: list[Incoming] = field(default_factory=list[Incoming])
    notified: list[Incoming] = field(default_factory=list[Incoming])

    def send(self, message: Incoming) -> fx.Effect[None, Any]:
        self.sent.append(message)
        return self.answer(message) if isinstance(message, IncomingRequest) else fx.void

    def notify(self, message: Incoming, *, wait_until_read: bool = False) -> fx.Effect[None, Any]:
        """A request read with ``wait_until_read`` is answered (or fails
        with ``notify_error``)."""
        self.notified.append(message)
        if not wait_until_read or not isinstance(message, IncomingRequest):
            return fx.void
        if self.notify_error is not None:
            return fx.fail(self.notify_error)
        return self.answer(message)


def _protocol() -> fx.Effect[ServerProtocolService]:
    def make(disconnects: Queue[int, Any]) -> ServerProtocolService:
        return ServerProtocolService(
            run=lambda _: fx.never,
            disconnects=cast("Queue[int]", disconnects),
            send=lambda _client, _message: fx.void,
            end=lambda _client: fx.void,
            supports_ack=False,
            supports_span_propagation=False,
            codec_for=S.to_codec_json,
        )

    return Queue[int, Any].unbounded().map(make)


def _layer(sharding: _Sharding) -> Layer[HandlersFor[Rpcs] | Generator]:
    return (
        runner_server.layer_handlers.pipe(
            fx.layer.provide(fx.layer.effect(ServerProtocol, _protocol()))
        )
        .pipe(fx.layer.provide(fx.layer.succeed(Sharding, cast("ShardingService", sharding))))
        .pipe(fx.layer.provide(message_storage.layer_noop))
        .pipe(fx.layer.provide_merge(snowflake.layer_generator))
    )


def _request(request_id: Snowflake, tag: str) -> envelope.PartialRequest:
    return envelope.make_request(
        request_id=request_id,
        address=EntityAddress(
            shard_id=ShardId(group="default", id=1),
            entity_type=EntityType("Entity"),
            entity_id=EntityId("1"),
        ),
        tag=tag,
        payload=cast("object", {}),
    )


def _reply_with(rpc: Any, value: object, ids: SnowflakeGenerator) -> _Answer:
    def answer(message: IncomingRequest) -> fx.Effect[None, Any]:
        reply = WithExit(
            request_id=message.envelope.request_id,
            id=ids.next_unsafe(),
            exit=Exit.succeed(value),
        )
        return message.respond(ReplyWithContext(reply, rpc=rpc))

    return answer


@testing.effect
def test_answers_a_ping():
    @fx.gen
    def body():
        client = yield from make_client(Rpcs)
        yield from client.ping()

    yield from fx.scoped(body).pipe(fx.provide(_layer(_Sharding())))


@testing.effect
def test_sends_a_volatile_request_and_answers_with_its_encoded_reply():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        sharding.answer = _reply_with(Double, 42, ids)
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Double")
        encoded = yield from client.effect({"request": request, "persisted": False})
        assert encoded["_tag"] == "WithExit"
        assert encoded["requestId"] == str(request.request_id)
        assert cast("dict[str, Any]", encoded)["exit"] == {"_tag": "Success", "value": 42}
        assert sharding.notified == []
        [sent] = sharding.sent
        assert isinstance(sent, IncomingRequest) and sent.envelope == request
        assert sent.caller_scope is not None, "the request runs in its caller's scope"

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_a_reply_that_fails_to_serialize_answers_with_a_defect():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        sharding.answer = _reply_with(Double, "not an int", ids)
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Double")
        encoded = yield from client.effect({"request": request, "persisted": False})
        assert encoded["_tag"] == "WithExit"
        exit = cast("dict[str, Any]", encoded)["exit"]
        assert exit["_tag"] == "Failure"
        assert "Die" in str(exit["cause"])

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_streams_chunks_and_ends_after_the_exit_reply():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()

        def answer(message: IncomingRequest) -> fx.Effect[None, Any]:
            request_id = message.envelope.request_id
            chunk = Chunk(request_id=request_id, id=ids.next_unsafe(), sequence=0, values=(1, 2))
            done = WithExit(request_id=request_id, id=ids.next_unsafe(), exit=Exit.succeed(None))
            return message.respond(ReplyWithContext(chunk, rpc=Count)).and_then(
                message.respond(ReplyWithContext(done, rpc=Count))
            )

        sharding.answer = answer
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Count")
        queue = yield from client.stream({"request": request, "persisted": False}, as_queue=True)
        first = yield from queue.take()
        assert first["_tag"] == "Chunk"
        assert list(cast("dict[str, Any]", first)["values"]) == [1, 2]
        last = yield from queue.take()
        assert last["_tag"] == "WithExit"
        ended = yield from queue.take().exit()
        assert isinstance(ended, Exit.Failure)
        assert isinstance(ended.cause.squash(), Done)

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_hands_envelopes_to_sharding_and_notifies_persisted_messages():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Double")
        interrupt = envelope.Interrupt(
            id=ids.next_unsafe(), request_id=request.request_id, address=request.address
        )
        yield from client.envelope({"envelope": interrupt, "persisted": False})
        yield from client.notify({"envelope": request, "persisted": True})
        yield from client.notify({"envelope": interrupt, "persisted": False})
        assert sharding.sent == [IncomingEnvelope(envelope=interrupt)] * 2
        [notified] = sharding.notified
        assert isinstance(notified, IncomingRequest) and notified.envelope == request

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


def _count_answer(ids: SnowflakeGenerator, first: object) -> _Answer:
    """Answers a ``Count`` request with a chunk holding ``first`` and an exit."""

    def answer(message: IncomingRequest) -> fx.Effect[None, Any]:
        request_id = message.envelope.request_id
        chunk = Chunk(request_id=request_id, id=ids.next_unsafe(), sequence=0, values=(first,))
        done = WithExit(request_id=request_id, id=ids.next_unsafe(), exit=Exit.succeed(None))
        return message.respond(ReplyWithContext(chunk, rpc=Count)).and_then(
            message.respond(ReplyWithContext(done, rpc=Count))
        )

    return answer


@testing.effect
def test_a_stream_reply_that_fails_to_serialize_ends_the_stream_with_the_defect():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        sharding.answer = _count_answer(ids, "not an int")
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Count")
        replies = yield from client.stream({"request": request, "persisted": False}).run_collect()
        [last] = replies
        assert last["_tag"] == "WithExit"
        assert last["requestId"] == str(request.request_id)
        exit = cast("dict[str, Any]", last)["exit"]
        assert exit["_tag"] == "Failure"
        assert "MalformedMessage" in str(exit["cause"])

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_a_persisted_request_is_notified_and_answered_through_its_reply_handler():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        sharding.answer = _reply_with(Double, 42, ids)
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Double")
        encoded = yield from client.effect({"request": request, "persisted": True})
        assert cast("dict[str, Any]", encoded)["exit"] == {"_tag": "Success", "value": 42}
        assert sharding.sent == []
        [notified] = sharding.notified
        assert isinstance(notified, IncomingRequest) and notified.envelope == request

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_a_persisted_request_fails_when_its_entity_is_not_on_this_runner():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        request = _request(ids.next_unsafe(), "Double")
        sharding.notify_error = EntityNotAssignedToRunner(address=request.address)
        client = yield from make_client(Rpcs)
        exit = yield from client.effect({"request": request, "persisted": True}).exit()
        assert isinstance(exit, Exit.Failure)
        assert exit.cause.squash() == sharding.notify_error

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_a_persisted_request_already_processing_waits_for_its_reply():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        request = _request(ids.next_unsafe(), "Double")
        sharding.notify_error = AlreadyProcessingMessage(
            envelope_id=request.request_id, address=request.address
        )
        client = yield from make_client(Rpcs)
        call = yield from client.effect({"request": request, "persisted": True}).fork()
        for _ in range(5):
            yield from fx.yield_now()
        assert call.poll_unsafe() is None, "the reply comes from the request already running"
        [notified] = sharding.notified
        assert isinstance(notified, IncomingRequest)
        yield from _reply_with(Double, 7, ids)(notified)
        encoded = yield from call.join()
        assert cast("dict[str, Any]", encoded)["exit"] == {"_tag": "Success", "value": 7}

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))


@testing.effect
def test_a_persisted_stream_is_notified_and_streams_its_replies():
    sharding = _Sharding()

    @fx.gen
    def body():
        ids = yield from Generator()
        sharding.answer = _count_answer(ids, 1)
        client = yield from make_client(Rpcs)
        request = _request(ids.next_unsafe(), "Count")
        replies = yield from client.stream({"request": request, "persisted": True}).run_collect()
        assert [reply["_tag"] for reply in replies] == ["Chunk", "WithExit"]
        assert sharding.sent == []

    yield from fx.scoped(body).pipe(fx.provide(_layer(sharding)))
