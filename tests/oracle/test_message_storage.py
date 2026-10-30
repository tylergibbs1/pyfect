"""Ports of Effect's ``test/cluster/MessageStorage.test.ts`` (the memory
storage). Each test's docstring is the Effect test title.

The encoded envelopes are Effect's JSON (camelCase keys, snowflakes as
strings); ``unprocessed_messages`` takes ``limit=`` and ``addresses=``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeIs

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Interrupt
from pyfect.cluster import entity_address, shard_id, snowflake
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner, MalformedMessage
from pyfect.cluster.cluster_schema import Abandon
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import PartialRequestEncoded
from pyfect.cluster.message import OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.message_storage import (
    MemoryDriver,
    MessageStorage,
    SaveDuplicate,
    SaveSuccess,
    layer_memory,
    memory_driver_layer,
)
from pyfect.cluster.reply import Reply, ReplyWithContext, WithExit
from pyfect.cluster.snowflake import Generator
from pyfect.exit import Failure
from pyfect.latch import Latch
from pyfect.rpc import make as make_rpc

from ._cluster_messages import (
    IdPayload,
    PrimaryKeyPayload,
    PrimaryKeyTest,
    StreamRpc,
    UnknownSuccessRpc,
    make_chunk_reply,
    make_reply,
    make_request,
)

memory = layer_memory.pipe(fx.layer.provide_merge(snowflake.layer_generator))


def _address(entity_id: str) -> entity_address.EntityAddress:
    return entity_address.make(
        shard_id=shard_id.make("default", 1),
        entity_type=EntityType("test"),
        entity_id=EntityId(entity_id),
    )


def _repro_request(request_id: str = "1") -> PartialRequestEncoded:
    return {
        "_tag": "Request",
        "requestId": request_id,
        "address": {
            "shardId": {"group": "default", "id": 1},
            "entityType": "Repro",
            "entityId": "one",
        },
        "tag": "Repro",
        "payload": {},
        "headers": {},
    }


def _payload_ids(messages: list[Any]) -> list[int]:
    return [m.envelope.payload["id"] for m in messages]


@testing.effect
def test_removes_primary_key_index_when_clearing_address():
    """removes the primary-key index when clearing an address"""

    def body():
        driver = yield from MemoryDriver()
        address = entity_address.make(
            shard_id=shard_id.make("default", 1),
            entity_type=EntityType("Repro"),
            entity_id=EntityId("one"),
        )
        yield from driver.encoded.save_envelope(_repro_request(), "dedup-key", None)
        yield from driver.encoded.clear_address(address)
        result = yield from driver.encoded.save_envelope(_repro_request("2"), "dedup-key", None)
        assert isinstance(result, SaveSuccess)

    yield from fx.gen(body).pipe(fx.provide(memory_driver_layer))


@testing.effect
def test_removes_queued_interrupt_when_clearing_address():
    """removes a queued Interrupt when clearing an address"""

    def body():
        storage = yield from MessageStorage()
        snowflakes = yield from Generator()
        request = yield from make_request()
        yield from storage.save_request(request)
        yield from storage.save_envelope(
            OutgoingEnvelope.interrupt(
                id=snowflakes.next_unsafe(),
                request_id=request.envelope.request_id,
                address=request.envelope.address,
            )
        )
        yield from storage.clear_address(request.envelope.address)
        messages = yield from storage.unprocessed_messages([request.envelope.address.shard_id])
        assert messages == []

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_encoded_unprocessed_messages_fails_closed_for_empty_address_filter():
    """encoded unprocessedMessages fails closed for an empty address filter"""

    def body():
        driver = yield from MemoryDriver()
        yield from driver.encoded.save_envelope(_repro_request(), None, None)
        messages = yield from driver.encoded.unprocessed_messages(["default:1"], 0, addresses=[])
        assert messages == []

    yield from fx.gen(body).pipe(fx.provide(memory_driver_layer))


@testing.effect
def test_encoded_reset_addresses_fails_closed_for_empty_address_list():
    """encoded resetAddresses fails closed for an empty address list"""

    def body():
        driver = yield from MemoryDriver()
        yield from driver.encoded.save_envelope(_repro_request(), None, None)
        claimed = yield from driver.encoded.unprocessed_messages(["default:1"], 0)
        assert len(claimed) == 1
        yield from driver.encoded.reset_addresses([])
        messages = yield from driver.encoded.unprocessed_messages(["default:1"], 1)
        assert messages == []

    yield from fx.gen(body).pipe(fx.provide(memory_driver_layer))


@testing.effect
def test_reset_requests_with_no_ids_leaves_claims():
    """resetRequests with no IDs leaves existing claims untouched"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        yield from storage.save_request(request)
        shards = [request.envelope.address.shard_id]
        assert len((yield from storage.unprocessed_messages(shards))) == 1
        yield from storage.reset_requests([])
        driver = yield from MemoryDriver()
        yield from driver.encoded.reset_requests([])
        assert (yield from storage.unprocessed_messages(shards)) == []

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_reset_requests_releases_only_selected_request():
    """resetRequests releases only the selected request at a shared address"""

    def body():
        storage = yield from MessageStorage()
        selected = yield from make_request()
        unrelated = yield from make_request()
        yield from storage.save_request(selected)
        yield from storage.save_request(unrelated)
        shards = [selected.envelope.address.shard_id]
        assert len((yield from storage.unprocessed_messages(shards))) == 2
        yield from storage.reset_requests([selected.envelope.request_id])
        messages = yield from storage.unprocessed_messages(shards)
        assert [m.envelope.request_id for m in messages] == [selected.envelope.request_id]
        assert (yield from storage.unprocessed_messages(shards)) == []

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_reset_requests_preserves_replies_and_completed_state():
    """resetRequests preserves chunk replies, exit replies, and completed state"""

    def body():
        storage = yield from MessageStorage()
        streaming = yield from make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=123))
        completed = yield from make_request()
        yield from storage.save_request(streaming)
        yield from storage.save_request(completed)
        yield from storage.save_reply((yield from make_chunk_reply(streaming)))
        yield from storage.save_reply((yield from make_reply(completed)))
        replies = yield from storage.replies_for([streaming, completed])
        assert len(replies) == 2
        shards = [streaming.envelope.address.shard_id]
        assert len((yield from storage.unprocessed_messages(shards))) == 1
        yield from storage.reset_requests(
            [streaming.envelope.request_id, completed.envelope.request_id]
        )
        messages = yield from storage.unprocessed_messages(shards)
        assert [m.envelope.request_id for m in messages] == [streaming.envelope.request_id]
        assert (yield from storage.replies_for([streaming, completed])) == replies

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_saves_a_request():
    """saves a request"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        result = yield from storage.save_request(request)
        assert isinstance(result, SaveSuccess)
        messages = yield from storage.unprocessed_messages([request.envelope.address.shard_id])
        assert len(messages) == 1

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_detects_duplicates():
    """detects duplicates"""

    def body():
        storage = yield from MessageStorage()
        payload = PrimaryKeyPayload(id=123)
        yield from storage.save_request(
            (yield from make_request(rpc=PrimaryKeyTest, payload=payload))
        )
        result = yield from storage.save_request(
            (yield from make_request(rpc=PrimaryKeyTest, payload=payload))
        )
        assert isinstance(result, SaveDuplicate)

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_unprocessed_messages_excludes_complete_requests():
    """unprocessedMessages excludes complete requests"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        yield from storage.save_request(request)
        yield from storage.save_reply((yield from make_reply(request)))
        messages = yield from storage.unprocessed_messages([request.envelope.address.shard_id])
        assert messages == []

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_unprocessed_messages_honors_limit():
    """unprocessedMessages honors the limit option"""

    def body():
        storage = yield from MessageStorage()
        for i in range(1, 6):
            yield from storage.save_request(
                (yield from make_request(payload={"id": i}, entity_id=str(i)))
            )
        shard = shard_id.make("default", 1)
        messages = yield from storage.unprocessed_messages([shard], limit=3)
        assert _payload_ids(messages) == [1, 2, 3]
        remaining = yield from storage.unprocessed_messages([shard])
        assert _payload_ids(remaining) == [4, 5]

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_unprocessed_messages_filters_by_address():
    """unprocessedMessages filters by address"""

    def body():
        storage = yield from MessageStorage()
        for i in range(1, 5):
            yield from storage.save_request(
                (yield from make_request(payload={"id": i}, entity_id=str(i)))
            )
        shard = shard_id.make("default", 1)
        messages = yield from storage.unprocessed_messages(
            [shard], addresses=[_address("2"), _address("4")]
        )
        assert _payload_ids(messages) == [2, 4]
        assert (yield from storage.unprocessed_messages([shard], addresses=[])) == []

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_reset_addresses_makes_claimed_messages_eligible():
    """resetAddresses makes claimed messages eligible again"""

    def body():
        storage = yield from MessageStorage()
        for i in range(1, 5):
            yield from storage.save_request(
                (yield from make_request(payload={"id": i}, entity_id=str(i)))
            )
        shard = shard_id.make("default", 1)
        yield from storage.unprocessed_messages([shard], limit=3)
        yield from storage.reset_addresses([_address("1"), _address("3")])
        messages = yield from storage.unprocessed_messages([shard])
        assert _payload_ids(messages) == [1, 3, 4]

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_replies_for():
    """repliesFor"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        yield from storage.save_request(request)
        assert (yield from storage.replies_for([request])) == []
        yield from storage.save_reply((yield from make_reply(request)))
        replies = yield from storage.replies_for([request])
        assert len(replies) == 1
        assert replies[0].request_id == request.envelope.request_id

    yield from fx.gen(body).pipe(fx.provide(memory))


def _with_respond(
    request: OutgoingRequest, respond: Callable[[Reply], fx.Effect[None]]
) -> OutgoingRequest:
    return OutgoingRequest(
        envelope=request.envelope,
        context=request.context,
        last_received_reply=request.last_received_reply,
        rpc=request.rpc,
        respond=respond,
        annotations=request.annotations,
    )


@testing.effect
def test_register_reply_handler():
    """registerReplyHandler"""

    def body():
        storage = yield from MessageStorage()
        latch = yield from Latch.make()
        request = yield from make_request()
        yield from storage.save_request(request)
        fiber = yield from storage.register_reply_handler(
            _with_respond(request, lambda _reply: latch.open().as_void())
        ).fork()
        yield from testing.adjust(0.001)
        yield from storage.save_reply((yield from make_reply(request)))
        yield from latch.wait()
        yield from fiber.await_exit()

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_unregister_shard_reply_handlers_fails_waiters_during_rebalance():
    """unregisterShardReplyHandlers fails parked waiters during rebalance"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        fiber = yield from storage.register_reply_handler(
            _with_respond(request, lambda _reply: fx.void)
        ).fork(start_immediately=True)
        yield from testing.adjust(0.001)
        yield from storage.unregister_shard_reply_handlers(request.envelope.address.shard_id)
        exit = yield from fiber.await_exit()
        assert isinstance(exit, Failure)
        error = exit.cause.find_error()
        assert isinstance(error, fx.Ok)
        assert isinstance(error.value, EntityNotAssignedToRunner)

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_unregister_shard_reply_handlers_annotates_waiters_during_shutdown():
    """unregisterShardReplyHandlers annotates parked waiters during shutdown"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        fiber = yield from storage.register_reply_handler(
            _with_respond(request, lambda _reply: fx.void)
        ).fork(start_immediately=True)
        yield from testing.adjust(0.001)
        yield from storage.unregister_shard_reply_handlers(
            request.envelope.address.shard_id, interrupt=True
        )
        exit = yield from fiber.await_exit()
        assert isinstance(exit, Failure)
        assert exit.cause.has_interrupts_only
        assert any(
            isinstance(r, Interrupt) and Abandon in r.annotations for r in exit.cause.reasons
        )

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_reply_handlers_receive_persisted_defect_fallback():
    """reply handlers receive the persisted defect fallback for unencodable replies"""

    def body():
        storage = yield from MessageStorage()
        snowflakes = yield from Generator()
        latch = yield from Latch.make()
        request = yield from make_request(rpc=UnknownSuccessRpc)
        yield from storage.save_request(request)
        received: list[Reply] = []

        def respond(reply: Reply) -> fx.Effect[None]:
            received.append(reply)
            return latch.open().as_void()

        fiber = yield from storage.register_reply_handler(_with_respond(request, respond)).fork()
        yield from testing.adjust(0.001)
        yield from storage.save_reply(
            ReplyWithContext(
                WithExit(
                    id=snowflakes.next_unsafe(),
                    request_id=request.envelope.request_id,
                    exit=fx.exit.succeed(ValueError("not json encodable")),
                ),
                request.context,
                request.rpc,
            )
        )
        yield from latch.wait()
        yield from fiber.await_exit()
        (reply,) = received
        assert isinstance(reply, WithExit)
        assert isinstance(reply.exit, Failure)
        assert "MalformedMessage" in repr(reply.exit)
        stored = yield from storage.replies_for_unfiltered([request.envelope.request_id])
        assert MalformedMessage.__name__ in json.dumps(stored)

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_malformed_stored_envelope_is_answered_with_effects_defect():
    """(pyfect) a stored envelope that does not decode is left out and its
    request ends with Effect's defect string (printed by Effect under Node)"""

    def body():
        driver = yield from MemoryDriver()
        bad: Any = {**_repro_request("123"), "tag": 5}
        yield from driver.encoded.save_envelope(bad, None, None)
        messages = yield from driver.storage.unprocessed_messages([shard_id.make("default", 1)])
        assert messages == []
        yield from fx.yield_now()
        [reply] = driver.encoded.requests["123"].replies
        assert reply["_tag"] == "WithExit"
        assert reply["exit"] == {
            "_tag": "Failure",
            "cause": [
                {"_tag": "Die", "defect": 'SchemaError(Expected string\n  at ["envelope"]["tag"])'}
            ],
        }

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_replies_for_keeps_decoding_defects():
    """(pyfect) repliesFor turns a reply that fails to decode into a defect
    reply, but a defect while decoding stays a defect (Effect catches only
    the failure)"""

    def boom(_value: object) -> TypeIs[int]:
        raise RuntimeError("boom")

    rpc = make_rpc("Dying", payload=S.Struct(IdPayload), success=S.declare(boom))

    def body():
        driver = yield from MemoryDriver()
        request = yield from make_request(rpc=rpc)
        yield from driver.storage.save_request(request)
        yield from driver.encoded.save_reply(
            {
                "_tag": "WithExit",
                "id": "99",
                "requestId": str(request.envelope.request_id),
                "exit": {"_tag": "Success", "value": 1},
            }
        )
        exit = yield from driver.storage.replies_for([request]).exit()
        assert isinstance(exit, Failure)
        assert isinstance(exit.cause.squash(), RuntimeError)

    yield from fx.gen(body).pipe(fx.provide(memory))


def _recording(storage: Any, request: OutgoingRequest, seen: list[str]) -> fx.Effect[Any, Any, Any]:
    def respond(reply: Reply) -> fx.Effect[None]:
        return fx.sync(lambda: seen.append(type(reply).__name__))

    return storage.register_reply_handler(_with_respond(request, respond)).fork(
        start_immediately=True
    )


@testing.effect
def test_with_transaction_notifies_exits_after_the_outermost_commit():
    """(pyfect) withTransaction: chunks notify at once, exits after the
    outermost commit (Effect's MessageStorage.make contract, exercised by
    Sharding.test.ts)"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=1))
        yield from storage.save_request(request)
        seen: list[str] = []
        fiber = yield from _recording(storage, request, seen)
        chunk = yield from make_chunk_reply(request)
        exit_reply = yield from make_reply(request)

        def inner():
            yield from storage.save_reply(chunk)
            assert seen == ["Chunk"]
            yield from storage.save_reply(exit_reply)
            assert seen == ["Chunk"]

        def outer():
            yield from storage.with_transaction(fx.gen(inner))
            assert seen == ["Chunk"]  # the inner commit is not the outermost

        yield from storage.with_transaction(fx.gen(outer))
        assert seen == ["Chunk", "WithExit"]
        assert isinstance((yield from fiber.await_exit()), fx.exit.Success)

    yield from fx.gen(body).pipe(fx.provide(memory))


@testing.effect
def test_with_transaction_drops_exit_notifications_of_a_failed_transaction():
    """(pyfect) withTransaction: a failed transaction does not notify its exits"""

    def body():
        storage = yield from MessageStorage()
        request = yield from make_request()
        yield from storage.save_request(request)
        seen: list[str] = []
        yield from _recording(storage, request, seen)
        exit_reply = yield from make_reply(request)
        failed = storage.with_transaction(
            storage.save_reply(exit_reply).flat_map(lambda _: fx.fail("rollback"))
        )
        assert (yield from failed.flip()) == "rollback"
        assert seen == []

    yield from fx.gen(body).pipe(fx.provide(memory))
