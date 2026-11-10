"""Ports of Effect's ``test/cluster/Sharding.test.ts``. Each test's
docstring is the Effect test title. The groups of that file live in:
``test_sharding_transactions`` (WithTransaction and storage-less replays),
``test_sharding_defect_recovery`` (entity-manager generations and mailbox
size), ``test_sharding_active_teardowns``, ``test_sharding_claims``,
``test_sharding_shutdown`` (live-clock shutdown cases),
``test_sharding_failover`` and ``test_sharding_forced_release`` (shard
lock failover over Effect's ``FailoverStorage``, ``_failover_storage``),
``test_sharding_handoff`` (shard handoff, singleton cancellation and
persisted sends to a shard awaiting its lock), ``test_sharding_restart``
(a runner restarted over shared, partly unread storage) and
``test_sharding_startup``; the shared fixtures are in
``_sharding_fixtures``. Every title of the file is ported.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Never, TypedDict, cast

import pyfect as fx
from pyfect import exit as Exit
from pyfect import metric, testing
from pyfect import schema as S
from pyfect._fiber import Fiber
from pyfect.cause import Die
from pyfect.cluster import (
    cluster_metrics,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    shard_id,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.cluster_error import (
    EntityNotAssignedToRunner,
    MailboxFull,
    RunnerUnavailable,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, EntityOptions, Request
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import Interrupt as EnvelopeInterrupt
from pyfect.cluster.message import Outgoing, codec_for_json
from pyfect.cluster.message_storage import (
    MemoryDriver,
    MemoryDriverService,
    MessageStorageService,
)
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners import Runners, RunnersTransport
from pyfect.cluster.sharding_config import ShardingConfig, ShardingConfigService
from pyfect.cluster.sharding_registration_event import EntityRegistered, SingletonRegistered
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context, Tag
from pyfect.deferred import Deferred
from pyfect.duration import millis
from pyfect.logger import LogLevel
from pyfect.queue import Queue
from pyfect.rpc import make as make_rpc
from pyfect.scope import scoped

from . import _cluster_entities as entities
from ._cluster_entities import (
    CallerId,
    ContextBleedEntity,
    KeyPayload,
    TestEntity,
    User,
    context_bleed_layer,
    test_entity_no_state,
    test_entity_state_layer,
)
from ._sharding_fixtures import (
    capped,
    make_config,
    patched,
    restart_env,
    restart_storage,
    save_get_user_request,
    series,
    test_config,
    test_sharding,
    test_sharding_without_runners,
    test_sharding_without_storage,
    unregistered,
    update_storage,
    without_storage_updated,
)

EntityState = entities.TestEntityState


@testing.effect
def test_delivers_volatile_requests_directly_to_the_entity():
    """delivers volatile requests directly to the entity"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        make_client = yield from TestEntity.client()
        client = make_client("1")
        user = yield from client.get_user_volatile({"id": 1})
        assert user == User(id=1, name="User 1")

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_persists_durable_requests_until_the_entity_replies():
    """persists durable requests until the entity replies"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        user = yield from client.get_user({"id": 1})
        assert user == User(id=1, name="User 1")
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.unprocessed) == 0

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_routes_durable_interrupts_through_storage():
    """routes durable interrupts through storage"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        fiber = yield from client.never().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        yield from fiber.interrupt()
        yield from testing.adjust("1 millis")
        assert len(driver.encoded.journal) == 2
        assert len(driver.encoded.reply_ids) == 1
        assert state.interrupts.size_unsafe() == 1

    yield from body.pipe(fx.provide(test_sharding))


class DiePayload(TypedDict):
    die: bool


class DefectingBox(Entity, type="DefectingBox"):
    send = make_rpc("Send", payload=S.Struct(DiePayload), success=S.String).annotate(
        Persisted, True
    )


@testing.effect
def test_interrupting_a_request_that_keeps_defecting_does_not_stall_other_entities():
    """interrupting a request that keeps defecting does not stall other entities"""

    def send(request: Request[DiePayload]) -> fx.Effect[str]:
        return fx.die(RuntimeError("boom")) if request.payload["die"] else fx.succeed("ok")

    layer = DefectingBox.to_layer(DefectingBox.handlers().handle(DefectingBox.send)(send)).pipe(
        fx.layer.provide_merge(test_sharding)
    )

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        client = yield from DefectingBox.client()
        dying = yield from client("a").send({"die": True}).fork(start_immediately=True)
        yield from testing.adjust("1 second")
        yield from dying.interrupt()

        healthy = yield from client("b").send({"die": False}).fork(start_immediately=True)
        yield from testing.adjust("1 second")
        assert healthy.poll_unsafe() == Exit.succeed("ok")

    yield from body.pipe(fx.provide(layer))


@testing.effect
def test_interrupts_arent_sent_for_durable_messages_on_shutdown():
    """interrupts aren't sent for durable messages on shutdown"""
    drivers: list[MemoryDriverService] = []

    @fx.gen
    def body():
        drivers.append((yield from MemoryDriver()))
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        yield from client.never().fork()
        yield from testing.adjust("1 millis")

    yield from body.pipe(fx.provide(test_sharding))
    # The request; the client interrupt is dropped.
    assert len(drivers[0].encoded.journal) == 1
    # The server interrupt is not sent.
    assert len(drivers[0].encoded.reply_ids) == 0


@testing.effect
def test_fails_volatile_requests_immediately_when_the_mailbox_is_full():
    """fails volatile requests immediately when the mailbox is full"""

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        for _ in range(10):
            yield from client.never_volatile().fork()
        yield from testing.adjust("1 millis")
        error = yield from client.never_volatile().flip()
        assert isinstance(error, MailboxFull)

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_interrupt_for_future_request_works_while_mailbox_is_full():
    """interrupt for future request works while mailbox is full"""

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        fibers: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(12), lambda _: client.never_fork().fork(start_immediately=True)
        )
        yield from testing.adjust("1 millis")
        assert state.envelopes.size_unsafe() == 10
        # Interrupt the 11th request.
        yield from fibers[10].interrupt()
        yield from testing.adjust("100 millis")
        # Interrupt the first request, and let the 11th come through.
        yield from fibers[0].interrupt()
        yield from testing.adjust("100 millis")
        assert state.envelopes.size_unsafe() == 12
        # The second interrupt is sent.
        assert state.interrupts.size_unsafe() == 2

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_delivers_durable_streams_and_acknowledges_each_chunk():
    """delivers durable streams and acknowledges each chunk"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        yield from testing.adjust("1 millis")
        make_client = yield from TestEntity.client()
        client = make_client("1")
        users = yield from client.get_all_users({"ids": [1, 2, 3]}).run_collect()
        assert users == [User(id=i, name=f"User {i}") for i in (1, 2, 3)]
        # 1 request, 3 acks, 4 replies
        assert len(driver.encoded.journal) == 4
        assert len(driver.encoded.reply_ids) == 4

    yield from body.pipe(fx.provide(test_sharding))


def _set_runner_address(config: ShardingConfigService, address: RunnerAddress) -> None:
    """Effect's tests move the runner after the shards were assigned, so
    the shards' owner looks remote."""
    object.__setattr__(config, "runner_address", address)


def _runners_layer(
    *,
    send: Callable[[RunnerAddress, Outgoing], fx.Effect[None, Any]] | None = None,
    notify: Callable[[RunnerAddress | None, Outgoing, bool], fx.Effect[None, Any]] | None = None,
) -> fx.Layer[Runners, Never, Any]:
    """``Runners.makeNoop`` with ``send`` or ``notify`` replaced."""

    def fail_send(_: RunnerAddress, message: Outgoing) -> fx.Effect[None, Any]:
        return fx.fail(EntityNotAssignedToRunner(address=message.envelope.address))

    def void_notify(_: RunnerAddress | None, __: Outgoing, ___: bool) -> fx.Effect[None, Any]:
        return fx.void

    transport = RunnersTransport(
        codec_for=codec_for_json,
        send=send or fail_send,
        notify=notify or void_notify,
        ping=lambda _: fx.void,
        on_runner_unavailable=lambda _: fx.void,
    )
    return fx.layer.effect(Runners, runners.make(transport))


@testing.effect
def test_durable_messages_are_retried_on_restart():
    """durable messages are retried on restart"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()

        @fx.gen
        def first():
            yield from testing.adjust("1 millis")
            make_client = yield from TestEntity.client()
            client = make_client("1")
            yield from client.request_with_key(KeyPayload(key="abc")).fork()
            yield from testing.adjust("1 millis")

        yield from scoped(first.pipe(fx.provide(restart_env)))
        # Only the request is in the journal.
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.reply_ids) == 0
        assert len(driver.encoded.unprocessed) == 1

        # Add the response.
        yield from state.messages.offer(None)
        # Let the shards get assigned and storage poll.
        yield from scoped(testing.adjust("5 seconds").pipe(fx.provide(restart_env)))
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0

        # The client reads the result from storage.
        @fx.gen
        def again():
            yield from testing.adjust("1 millis")
            make_client = yield from TestEntity.client()
            client = make_client("1")
            assert (yield from client.request_with_key(KeyPayload(key="abc"))) is None

        yield from scoped(again.pipe(fx.provide(restart_env)))
        # The request does not hit the entity.
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0

    yield from body.pipe(fx.provide(restart_storage))


@testing.effect
def test_durable_streams_are_resumed_on_restart():
    """durable streams are resumed on restart"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        # The first chunk.
        yield from state.stream_messages.offer_all([None, None])

        @fx.gen
        def first():
            yield from testing.adjust("2 seconds")
            make_client = yield from TestEntity.client()
            client = make_client("1")
            yield from client.stream_with_key(KeyPayload(key="abc")).run_drain().fork()
            yield from testing.adjust("2 seconds")
            # The second chunk.
            yield from state.stream_messages.offer(None)
            yield from testing.adjust("2 seconds")

        yield from scoped(first.pipe(fx.provide(restart_env)))
        # 1 request, 2 acks, 2 replies
        assert len(driver.encoded.journal) == 1 + 2
        assert len(driver.encoded.reply_ids) == 2
        assert len(driver.encoded.unprocessed) == 1

        # The third chunk.
        yield from state.stream_messages.offer_all([None, None])
        yield from state.stream_messages.end()

        @fx.gen
        def resumed():
            # Let the shards get assigned and storage poll.
            yield from testing.adjust("5 seconds")
            make_client = yield from TestEntity.client()
            client = make_client("1")
            # Let the reply loop run.
            yield from testing.adjust("500 millis").fork()
            results = yield from client.stream_with_key(KeyPayload(key="abc")).run_collect()
            assert results == [3, 4]

        yield from scoped(resumed.pipe(fx.provide(restart_env)))
        # 1 request, 3 acks, 4 replies (3 chunks and the exit)
        assert len(driver.encoded.journal) == 1 + 3
        assert len(driver.encoded.reply_ids) == 4
        assert len(driver.encoded.unprocessed) == 0

    yield from body.pipe(fx.provide(restart_storage))


@testing.effect
def test_interrupts_are_sent_for_volatile_messages_on_shutdown():
    """interrupts are sent for volatile messages on shutdown"""
    interrupted: list[bool] = []
    clock = yield from testing.test_clock()

    def send(_: RunnerAddress, message: Outgoing) -> fx.Effect[None, Any]:
        if isinstance(message.envelope, EnvelopeInterrupt):
            interrupted.append(True)
            return fx.void
        return fx.fail(EntityNotAssignedToRunner(address=message.envelope.address))

    env = (
        test_sharding_without_runners.pipe(fx.layer.provide(_runners_layer(send=send)))
        .pipe(
            fx.layer.provide(
                fx.layer.merge(message_storage.layer_memory, snowflake.layer_generator)
            )
        )
        .pipe(
            fx.layer.provide_merge(
                make_config(
                    entity_termination_timeout=millis(30_000),
                    refresh_assignments_interval=millis(100),
                )
            )
        )
    )

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        client = make_client("1")
        fiber = yield from client.never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        _set_runner_address(
            (yield from ShardingConfig()), RunnerAddress(host="localhost", port=1234)
        )
        parent = Fiber.get_current()
        assert parent is not None

        def task() -> None:
            fiber.interrupt_as_unsafe(None)
            parent._fork(clock.adjust("30 seconds"), daemon=True, start_immediately=True)

        fiber._scheduler.schedule(task)

    yield from body.pipe(fx.provide(env))
    assert interrupted == [True]


@testing.effect
def test_client_discard_stores_durable_requests_without_waiting_for_replies():
    """client discard stores durable requests without waiting for replies"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        assert (yield from client.get_user.discard({"id": 123})) is None
        yield from testing.adjust("1 millis")
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.unprocessed) == 0

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_client_discard_returns_while_the_durable_request_keeps_processing():
    """client discard returns while the durable request keeps processing"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        assert (yield from client.never.discard()) is None
        yield from testing.adjust("1 millis")
        assert len(driver.encoded.journal) == 1
        # Still processing.
        assert len(driver.encoded.unprocessed) == 1

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_client_discard_returns_while_the_volatile_request_keeps_processing():
    """client discard returns while the volatile request keeps processing"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        assert (yield from client.never_volatile.discard()) is None
        yield from testing.adjust("1 millis")
        assert state.envelopes.size_unsafe() == 1

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_client_volatile_discard_retries_a_failed_delivery():
    """client volatile discard retries a failed delivery"""
    attempts: list[int] = []

    def notify(address: RunnerAddress | None, _: Outgoing, __: bool) -> fx.Effect[None, Any]:
        attempts.append(1)
        assert address is not None
        if len(attempts) == 1:
            return fx.fail(RunnerUnavailable(address=address))
        return fx.void

    env = (
        test_sharding_without_runners.pipe(fx.layer.provide(_runners_layer(notify=notify)))
        .pipe(
            fx.layer.provide(
                fx.layer.merge(message_storage.layer_memory, snowflake.layer_generator)
            )
        )
        .pipe(fx.layer.provide_merge(test_config))
    )

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        _set_runner_address(
            (yield from ShardingConfig()), RunnerAddress(host="localhost", port=1234)
        )
        make_client = yield from TestEntity.client()
        client = make_client("1")
        fiber = yield from client.never_volatile.discard().fork(start_immediately=True)
        assert len(attempts) == 1
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("100 millis")
        yield from fiber.join()
        assert len(attempts) == 2

    yield from body.pipe(fx.provide(env))


@testing.effect
def test_defects_when_a_durable_request_has_no_message_storage():
    """defects when a durable request has no MessageStorage"""

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        client = make_client("1")
        cause = yield from client.never().sandbox().flip()
        assert cause.has_dies

    yield from body.pipe(
        fx.provide(test_sharding_without_storage.pipe(fx.layer.provide(message_storage.layer_noop)))
    )


@testing.effect
def test_restarts_the_entity_layer_after_a_handler_defect():
    """restarts the entity layer after a handler defect"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        state.defect_trigger[0] = True
        result = yield from client.get_user({"id": 123})
        assert result == User(id=123, name="User 123")
        assert state.layer_builds[0] == 2

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_replays_in_flight_requests_when_restarting_after_a_defect():
    """replays in-flight requests when restarting after a defect"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        yield from client.never_fork().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert state.envelopes.size_unsafe() == 1
        state.defect_trigger[0] = True
        result = yield from client.get_user({"id": 123})
        assert result == User(id=123, name="User 123")
        assert state.layer_builds[0] == 2
        yield from testing.adjust("1 millis")
        assert state.envelopes.size_unsafe() == 4

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_malformed_message_in_storage():
    """malformed message in storage"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        fiber = yield from client.never().fork()
        yield from testing.adjust("1 millis")
        request = driver.encoded.journal[0]
        malformed: Any = {
            "id": "boom",
            "_tag": "Interrupt",
            "requestId": request["requestId"],
            "address": {"shardId": request["address"]["shardId"]},
        }
        yield from driver.encoded.save_envelope(malformed, None, None)
        # Wait for storage to poll.
        yield from testing.adjust("5 seconds")
        exit = fiber.poll_unsafe()
        assert isinstance(exit, Exit.Failure)
        assert exit.cause.has_dies
        # The malformed message is left in storage.
        assert len(driver.encoded.journal) == 2
        # A defect reply is saved.
        assert len(driver.encoded.reply_ids) == 1
        reply: Any = driver.encoded.requests[request["requestId"]].replies[0]
        assert reply["_tag"] == "WithExit"
        assert reply["exit"]["_tag"] == "Failure"
        assert reply["exit"]["cause"][0]["_tag"] == "Die"

    yield from body.pipe(fx.provide(test_sharding))


def _spy_unprocessed_by_id(
    requested: Queue[list[Snowflake], Never],
) -> Callable[[MessageStorageService], MessageStorageService]:
    def transform(storage: MessageStorageService) -> MessageStorageService:
        def by_id(message_ids: Any) -> fx.Effect[Any, Any]:
            ids = list(message_ids)
            requested.offer_unsafe(ids)
            return storage.unprocessed_messages_by_id(ids)

        return patched(storage, unprocessed_messages_by_id=by_id)

    return transform


@testing.effect
def test_durable_messages_are_retried_when_mailbox_is_full():
    """durable messages are retried when mailbox is full"""
    requested = yield from Queue[list[Snowflake], Never].unbounded()

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        client = make_client("1")
        fibers: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(11), lambda _: client.never_fork().fork()
        )
        yield from testing.adjust("1 millis")
        # The entity resumes from storage and asks for the ids.
        ids = yield from requested.take()
        assert len(ids) == 1
        # The entity still has only 10 requests.
        assert state.envelopes.size_unsafe() == 10
        # Interrupt the first request and let the retry happen.
        yield from fibers[0].interrupt()
        yield from testing.adjust("100 millis")
        # The last request comes through.
        assert state.envelopes.size_unsafe() == 11
        # Interrupt the second: the entity is back in the storage loop.
        yield from fibers[1].interrupt()
        # A request within the mailbox capacity.
        yield from client.never_fork().fork()
        yield from testing.adjust("1 millis")
        yield from Fiber.interrupt_all(fibers)
        yield from testing.adjust("100 millis")
        # No more ids were asked for.
        assert requested.size_unsafe() == 0

    yield from body.pipe(fx.provide(without_storage_updated(_spy_unprocessed_by_id(requested))))


@testing.effect
def test_durable_stream_while_mailbox_is_full():
    """durable stream while mailbox is full"""
    requested = yield from Queue[list[Snowflake], Never].unbounded()

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        fibers: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(10), lambda _: client.never_fork().fork(start_immediately=True)
        )
        yield from testing.adjust("1 millis")
        fiber = yield from (
            client.get_all_users({"ids": [1, 2, 3]}).run_collect().fork(start_immediately=True)
        )
        # Keep the entity in resume mode.
        yield from client.never_fork().fork(start_immediately=True)
        yield from client.never_fork().fork(start_immediately=True)
        ids = yield from requested.take()
        assert len(ids) == 3
        assert state.envelopes.size_unsafe() == 10
        # Interrupt the first request and let the retry happen.
        yield from fibers[0].interrupt()
        yield from testing.adjust("500 millis")
        # The last request and a NeverFork come through.
        assert state.envelopes.size_unsafe() == 12
        # Acks may be sent.
        users = yield from fiber.join()
        assert users == [User(id=i, name=f"User {i}") for i in (1, 2, 3)]
        driver = yield from MemoryDriver()
        # 13 requests, 3 acks, 1 interrupt, 5 replies
        assert len(driver.encoded.journal) == 13 + 3 + 1
        assert len(driver.encoded.reply_ids) == 1 + 4

    yield from body.pipe(fx.provide(without_storage_updated(_spy_unprocessed_by_id(requested))))


def _late_env(
    config: fx.Layer[ShardingConfig],
    *,
    delay: float | None = None,
    transform: Callable[[MessageStorageService], MessageStorageService] | None = None,
) -> fx.Layer[Any, Never, Any]:
    entity = test_entity_no_state
    if delay is not None:
        entity = entity.pipe(
            fx.layer.provide(fx.layer.effect_discard(fx.sleep(fx.duration.seconds(delay))))
        )
    built = (
        entity.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(config))
    )
    if transform is not None:
        built = built.pipe(fx.layer.provide(update_storage(transform)))
    return built


late_storage = fx.layer.merge(
    message_storage.layer_memory.pipe(fx.layer.provide(sharding_config.layer())),
    test_entity_state_layer,
)


@fx.fn
def _send_request_with_key(key: str):
    yield from testing.adjust("1 millis")
    make_client = yield from TestEntity.client()
    client = make_client("1")
    yield from client.request_with_key(KeyPayload(key=key)).fork()
    yield from testing.adjust("1 millis")


@testing.effect
def test_holds_durable_messages_while_entity_layers_are_still_building():
    """holds durable messages while entity layers are still building"""
    config = make_config(
        entity_registration_timeout=millis(6000), entity_message_poll_interval=millis(100)
    )

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        yield from scoped(
            _send_request_with_key("slow-registration").pipe(fx.provide(_late_env(config)))
        )
        assert len(driver.encoded.journal) == 1
        assert len(driver.encoded.reply_ids) == 0
        assert len(driver.encoded.unprocessed) == 1
        fiber = yield from scoped(fx.never.pipe(fx.provide(_late_env(config, delay=10)))).fork(
            start_immediately=True
        )
        yield from testing.adjust("7500 millis")
        assert len(driver.encoded.reply_ids) == 0
        assert len(driver.encoded.unprocessed) == 1
        yield from testing.adjust("2500 millis")
        yield from state.messages.offer(None)
        yield from testing.adjust("100 millis")
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0
        yield from fiber.interrupt()

    yield from body.pipe(fx.provide(late_storage))


@testing.effect
def test_reads_durable_messages_from_storage_when_a_late_entity_registers():
    """reads durable messages from storage when a late entity registers"""
    config = make_config(
        entity_registration_timeout=millis(6000), entity_message_poll_interval=millis(3_600_000)
    )
    reset_started = Deferred[None, Never]()
    release_reset = Deferred[None, Never]()

    def gate(reset: fx.Effect[None, Any]) -> fx.Effect[None, Any]:
        return reset_started.succeed(None).and_then(release_reset.wait()).and_then(reset)

    def transform(storage: MessageStorageService) -> MessageStorageService:
        def reset_address(address: EntityAddress) -> fx.Effect[None, Any]:
            return gate(storage.reset_address(address))

        def reset_addresses(addresses: list[EntityAddress]) -> fx.Effect[None, Any]:
            return gate(storage.reset_addresses(addresses))

        return patched(storage, reset_address=reset_address, reset_addresses=reset_addresses)

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        yield from scoped(
            _send_request_with_key("late-registration").pipe(fx.provide(_late_env(config)))
        )
        assert len(driver.encoded.unprocessed) == 1
        delayed = _late_env(config, delay=1, transform=transform)
        fiber = yield from scoped(fx.never.pipe(fx.provide(delayed))).fork(start_immediately=True)
        # The startup read sees the message before the entity registers, and
        # the entity registers while the claim reset is pending.
        yield from testing.adjust("999 millis")
        assert reset_started.is_done_unsafe()
        yield from testing.adjust("1 millis")
        # The reset completes before the read woken by registration, without
        # waiting for the poll interval or new client traffic.
        yield from release_reset.succeed(None)
        yield from state.messages.offer(None)
        yield from testing.adjust("100 millis")
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0
        yield from fiber.interrupt()

    yield from body.pipe(fx.provide(late_storage))


@testing.effect
def test_defects_durable_messages_when_no_entity_ever_registers():
    """defects durable messages when no entity ever registers"""
    config = make_config(
        entity_registration_timeout=millis(1000), entity_message_poll_interval=millis(100)
    )
    no_entities = (
        sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(config))
    )
    warnings: list[Any] = []

    def log(options: Any) -> None:
        if options.log_level == LogLevel.WARN:
            warnings.append(options.message)

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        yield from scoped(
            _send_request_with_key("missing-registration").pipe(fx.provide(_late_env(config)))
        )
        fiber = yield from (
            scoped(fx.never.pipe(fx.provide(no_entities)))
            .with_logger(fx.Logger.make(log))
            .fork(start_immediately=True)
        )
        yield from testing.adjust("8 seconds")
        assert any(
            "Could not find entity manager for address, retrying" in _messages(message)
            for message in warnings
        )
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0
        yield from fiber.interrupt()

    yield from body.pipe(fx.provide(late_storage))


def _messages(message: Any) -> list[Any]:
    return list(cast("tuple[Any, ...]", message)) if isinstance(message, tuple) else [message]


class MissingRegistrationEntity(Entity, type="MissingRegistrationEntity"):
    call = make_rpc("Call").annotate(Persisted, False)


class FirstRegistrationEntity(Entity, type="FirstRegistrationEntity"):
    call = make_rpc("Call").annotate(Persisted, False)


def _defect_message(exit: Exit.Exit[Any, Any] | None) -> str:
    assert exit is not None
    assert isinstance(exit, Exit.Failure)
    dies = [reason for reason in exit.cause.reasons if isinstance(reason, Die)]
    assert dies
    return str(dies[0].defect)


@testing.effect
def test_bounds_local_sends_while_entity_registration_is_missing():
    """bounds local sends while entity registration is missing"""

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_id = EntityId("one")
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(service.get_shard_id(entity_id, "default"))
        client = (yield from MissingRegistrationEntity.client())(entity_id)
        fiber = yield from client.call().fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("1 second")
        assert (
            _defect_message(fiber.poll_unsafe())
            == "Entity type 'MissingRegistrationEntity' not registered"
        )

    yield from body.pipe(fx.provide(capped(entity_registration_timeout=millis(1000))))


@testing.effect
def test_recomputes_the_missing_entity_deadline_when_registration_starts():
    """recomputes the missing entity deadline when registration starts"""

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_id = EntityId("one")
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(service.get_shard_id(entity_id, "default"))
        client = (yield from MissingRegistrationEntity.client())(entity_id)
        fiber = yield from client.call().fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("1500 millis")
        handlers = FirstRegistrationEntity.handlers().handle(FirstRegistrationEntity.call)(
            lambda _: fx.void
        )
        yield from service.register_entity(
            FirstRegistrationEntity, fx.succeed(handlers), EntityOptions()
        )
        # The registration-start deadline is a second from now: the elapsed
        # fallback deadline no longer wins the race.
        yield from testing.adjust("600 millis")
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("400 millis")
        assert (
            _defect_message(fiber.poll_unsafe())
            == "Entity type 'MissingRegistrationEntity' not registered"
        )

    yield from scoped(body.pipe(fx.provide(unregistered(entity_registration_timeout=millis(1000)))))


@testing.effect
def test_keeps_a_shared_registration_latch_when_one_waiter_is_interrupted():
    """keeps a shared registration latch when one waiter is interrupted"""

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_id = EntityId("one")
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(service.get_shard_id(entity_id, "default"))
        client = (yield from MissingRegistrationEntity.client())(entity_id)
        interrupted = yield from client.call().fork_daemon(start_immediately=True)
        remaining = yield from client.call().fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        assert interrupted.poll_unsafe() is None
        assert remaining.poll_unsafe() is None
        interrupted.interrupt_as_unsafe(None)
        yield from fx.yield_now()
        handlers = MissingRegistrationEntity.handlers().handle(MissingRegistrationEntity.call)(
            lambda _: fx.void
        )
        yield from service.register_entity(
            MissingRegistrationEntity, fx.succeed(handlers), EntityOptions()
        )
        exit = yield from interrupted.await_exit()
        assert isinstance(exit, Exit.Failure)
        assert exit.cause.has_interrupts_only
        yield from remaining.join()

    yield from scoped(body.pipe(fx.provide(unregistered(entity_registration_timeout=millis(1000)))))


@testing.effect
def test_bounds_client_interruption_while_entity_registration_is_missing():
    """bounds client interruption while entity registration is missing"""

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_id = EntityId("one")
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(service.get_shard_id(entity_id, "default"))
        client = (yield from MissingRegistrationEntity.client())(entity_id)
        fiber = yield from client.call().fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        # The client's interrupt message goes through the same registration
        # wait: fork it so the clock can reach the shared deadline.
        interrupt_fiber = yield from fiber.interrupt().fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        assert interrupt_fiber.poll_unsafe() is None
        yield from testing.adjust("1 second")
        yield from interrupt_fiber.join()
        exit = yield from fiber.await_exit()
        assert isinstance(exit, Exit.Failure)
        assert exit.cause.has_interrupts_only

    yield from body.pipe(fx.provide(capped(entity_registration_timeout=millis(1000))))


# --- Sharding residency cap ------------------------------------------------------------------


@testing.effect
def test_bounds_resident_entities_to_max_resident_entities():
    """bounds resident entities to maxResidentEntities"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        fibers: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(1, 7),
            lambda i: make_client(str(i)).get_user({"id": i}).fork(start_immediately=True),
        )
        yield from testing.adjust("1 millis")
        assert (yield from service.active_entity_count) <= 2
        # Idle entities are reaped over time, freeing slots for the backlog.
        for _ in range(12):
            yield from testing.adjust("5 seconds")
            assert (yield from service.active_entity_count) <= 2
        users = yield from Fiber.join_all(fibers)
        assert [user.id for user in users] == [1, 2, 3, 4, 5, 6]

    yield from body.pipe(
        fx.provide(capped(max_resident_entities=2, entity_max_idle_time=millis(1000)))
    )


@testing.effect
def test_volatile_sends_to_new_entities_fail_with_mailbox_full_at_the_cap():
    """volatile sends to new entities fail with MailboxFull at the cap"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        # Occupy the only slot.
        yield from make_client("1").never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert (yield from service.active_entity_count) == 1
        error = yield from make_client("2").get_user_volatile({"id": 2}).flip()
        assert isinstance(error, MailboxFull)
        # Persisted sends still succeed and wait in storage.
        yield from make_client("2").get_user.discard({"id": 2})
        yield from testing.adjust("5 seconds")
        assert (yield from service.active_entity_count) == 1
        assert len(driver.encoded.unprocessed) == 1
        assert len(driver.encoded.reply_ids) == 0

    yield from body.pipe(fx.provide(capped(max_resident_entities=1)))


@testing.effect
def test_keeps_delivering_to_resident_entities_at_the_cap():
    """keeps delivering to resident entities at the cap"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        # Make entity "1" resident and keep it busy.
        yield from make_client("1").never_fork().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert state.envelopes.size_unsafe() == 1
        # A backlog of new entity ids in front of the resident's next message.
        for i in range(2, 5):
            yield from make_client(str(i)).get_user.discard({"id": i})
        fiber = yield from make_client("1").get_user({"id": 1}).fork(start_immediately=True)
        yield from testing.adjust("5 seconds")
        # The resident entity got its message despite the backlog.
        assert (yield from fiber.join()) == User(id=1, name="User 1")
        # The new ids were not admitted; their requests stay in storage.
        assert (yield from service.active_entity_count) == 1
        assert len(driver.encoded.unprocessed) == 4
        assert len(driver.encoded.reply_ids) == 1

    yield from body.pipe(
        fx.provide(capped(max_resident_entities=1, unprocessed_message_batch_size=2))
    )


@testing.effect
def test_unbounded_max_resident_entities_does_not_limit_spawning():
    """unbounded maxResidentEntities does not limit spawning"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        for i in range(1, 16):
            yield from make_client(str(i)).never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert (yield from service.active_entity_count) == 15

    yield from body.pipe(fx.provide(capped(max_resident_entities="unbounded")))


@testing.effect
def test_drains_a_full_batch_without_waiting_for_the_poll_interval():
    """drains a full batch without waiting for the poll interval"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        driver = yield from MemoryDriver()
        for i in range(1, 6):
            yield from save_get_user_request(str(i), i)
        assert len(driver.encoded.reply_ids) == 0
        # One poll drains the whole backlog in batches of 2.
        yield from testing.adjust("5 seconds")
        assert len(driver.encoded.reply_ids) == 5

    yield from body.pipe(fx.provide(capped(unprocessed_message_batch_size=2)))


@testing.effect
def test_advances_past_in_flight_memory_requests_when_reading_bounded_batches():
    """advances past in-flight memory requests when reading bounded batches"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        make_client = yield from TestEntity.client()
        yield from make_client("1").never().fork(start_immediately=True)
        yield from make_client("2").never().fork(start_immediately=True)
        fiber = yield from make_client("3").get_user({"id": 3}).fork(start_immediately=True)
        yield from testing.adjust("5 seconds")
        assert (yield from fiber.join()) == User(id=3, name="User 3")

    yield from body.pipe(fx.provide(capped(unprocessed_message_batch_size=2)))


@testing.effect
def test_keeps_full_sized_storage_reads_when_approaching_the_entity_cap():
    """keeps full-sized storage reads when approaching the entity cap"""
    limits: list[int] = []

    def transform(storage: MessageStorageService) -> MessageStorageService:
        def unprocessed(shard_ids: Any, *, limit: int | None = None, **options: Any) -> Any:
            if limit is not None:
                limits.append(limit)
            return storage.unprocessed_messages(shard_ids, limit=limit, **options)

        return patched(storage, unprocessed_messages=unprocessed)

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        for i in range(1, 5):
            yield from make_client(str(i)).never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert (yield from service.active_entity_count) == 4
        limits.clear()
        for i in range(10):
            yield from save_get_user_request(str(i % 4 + 1), i)
        yield from testing.adjust("5 seconds")
        assert limits
        assert set(limits) == {100}

    yield from body.pipe(
        fx.provide(capped(transform, max_resident_entities=5, unprocessed_message_batch_size=100))
    )


@testing.effect
def test_normalizes_programmatic_batch_sizes_below_one():
    """normalizes programmatic batch sizes below one"""
    for batch_size in (0, -1):

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            make_client = yield from TestEntity.client()
            fiber = yield from make_client("1").get_user({"id": 1}).fork(start_immediately=True)
            yield from testing.adjust("5 seconds")
            assert fiber.poll_unsafe() is not None
            assert (yield from fiber.join()) == User(id=1, name="User 1")

        yield from body.pipe(fx.provide(capped(unprocessed_message_batch_size=batch_size)))


@testing.effect
def test_does_not_busy_poll_storage_at_the_cap():
    """does not busy-poll storage at the cap"""
    reads: list[int] = []

    def transform(storage: MessageStorageService) -> MessageStorageService:
        def unprocessed(shard_ids: Any, **options: Any) -> Any:
            reads.append(1)
            return storage.unprocessed_messages(shard_ids, **options)

        return patched(storage, unprocessed_messages=unprocessed)

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        make_client = yield from TestEntity.client()
        yield from make_client("1").never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        # A backlog for a new id that cannot be admitted.
        yield from make_client("2").get_user.discard({"id": 2})
        yield from testing.adjust("1 millis")
        before = len(reads)
        # Less than the poll interval.
        yield from testing.adjust("4 seconds")
        assert len(reads) - before <= 1

    yield from body.pipe(fx.provide(capped(transform, max_resident_entities=1)))


# --- context ---------------------------------------------------------------------------------


@testing.effect
def test_does_not_freeze_the_first_callers_context_into_the_entity_server():
    """does not freeze the first caller's context into the entity server"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        make_client = yield from ContextBleedEntity.client()
        client = make_client("1")
        first = yield from client.read_caller().pipe(fx.provide_service(CallerId, "A"))
        assert first == "A"
        assert (yield from client.read_caller()) == "none"
        assert (yield from client.read_caller_persisted()) == "none"

    yield from body.pipe(
        fx.provide(context_bleed_layer.pipe(fx.layer.provide_merge(test_sharding)))
    )


class RegistrationContext(Tag[str], key="RegistrationContext"):
    pass


class RegistrationContextEntity(Entity, type="RegistrationContextEntity"):
    read = make_rpc("Read", success=S.String).annotate(Persisted, False)


@testing.effect
def test_uses_services_provided_when_registering_an_entity():
    """uses services provided when registering an entity"""

    @fx.gen
    def build():
        value = yield from RegistrationContext()
        return RegistrationContextEntity.handlers().handle(RegistrationContextEntity.read)(
            lambda _: fx.succeed(value)
        )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        yield from service.register_entity(RegistrationContextEntity, build, EntityOptions()).pipe(
            fx.provide_service(RegistrationContext, "registration")
        )
        yield from testing.adjust("1 millis")
        client = (yield from RegistrationContextEntity.client())("1")
        assert (yield from client.read()) == "registration"

    yield from scoped(
        body.pipe(fx.provide(test_sharding)).pipe(
            fx.provide_service(RegistrationContext, "construction")
        )
    )


@testing.effect
def test_with_transaction_persists_a_client_interrupt_instead_of_replaying_the_request():
    """WithTransaction persists a client interrupt instead of replaying the request"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        fiber = yield from make_client("1").never_with_transaction().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        yield from fiber.interrupt()
        yield from testing.adjust("1 millis")
        assert len(driver.encoded.reply_ids) == 1
        assert state.envelopes.size_unsafe() == 1

    yield from body.pipe(fx.provide(test_sharding))


def _wait_for_idle_reap(service: sharding.ShardingService, remaining: int) -> fx.Effect[None]:
    @fx.gen
    def run():
        for _ in range(12):
            if (yield from service.active_entity_count) <= remaining:
                return
            yield from testing.adjust("5 seconds")
        assert (yield from service.active_entity_count) <= remaining

    return run


@testing.effect
def test_reports_entity_mailbox_sizes_until_entities_are_released():
    """reports entity mailbox sizes until entities are released"""
    registry: dict[Any, Any] = {}

    def sizes() -> list[tuple[Any, Any]]:
        return series(registry, cluster_metrics.entity_mailbox_size.id)

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        first: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(2), lambda _: make_client("1").never_volatile().fork()
        )
        yield from make_client("2").never_volatile().fork()
        yield from testing.adjust("1 millis")

        def shard(id: str) -> str:
            return str(service.get_shard_id(EntityId(id), "default"))

        assert sizes() == [
            ({"type": "TestEntity", "id": "1", "shard": shard("1")}, metric.GaugeState(2)),
            ({"type": "TestEntity", "id": "2", "shard": shard("2")}, metric.GaugeState(1)),
        ]
        yield from Fiber.interrupt_all(first)
        yield from _wait_for_idle_reap(service, 1)
        assert sizes() == [
            ({"type": "TestEntity", "id": "2", "shard": shard("2")}, metric.GaugeState(1)),
        ]

    yield from body.pipe(
        fx.provide(capped(entity_mailbox_metrics=True, entity_max_idle_time=millis(1)))
    ).pipe(fx.provide_service(metric.MetricRegistry, registry))
    # Shutting down releases every shard, tearing down the remaining entity.
    assert sizes() == []


@testing.effect
def test_creates_no_entity_mailbox_series_by_default():
    """creates no entity mailbox series by default"""
    registry: dict[Any, Any] = {}

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        yield from make_client("1").never_volatile().fork()
        yield from testing.adjust("1 millis")
        assert (yield from service.active_entity_count) == 1
        assert series(registry, cluster_metrics.entity_mailbox_size.id) == []

    yield from body.pipe(fx.provide(test_sharding)).pipe(
        fx.provide_service(metric.MetricRegistry, registry)
    )


@testing.effect
def test_reports_the_active_entity_count_on_snapshot_until_the_entity_manager_closes():
    """reports the active entity count on snapshot until the entity manager closes"""
    registry: dict[Any, Any] = {}

    def counts() -> list[Any]:
        return [
            state
            for attributes, state in series(registry, cluster_metrics.entities.id)
            if attributes.get("type") == "TestEntity"
        ]

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        yield from make_client("1").never_volatile().fork()
        yield from testing.adjust("1 millis")
        assert counts() == [metric.GaugeState(1)]
        # Well within a second, so the count cannot come from a periodic update.
        yield from make_client("2").never_volatile().fork()
        yield from testing.adjust("1 millis")
        assert counts() == [metric.GaugeState(2)]

    yield from body.pipe(fx.provide(test_sharding)).pipe(
        fx.provide_service(metric.MetricRegistry, registry)
    )
    assert counts() == []


@testing.effect
def test_reports_the_largest_entity_mailbox_size_per_type_by_default():
    """reports the largest entity mailbox size per type by default"""
    registry: dict[Any, Any] = {}

    def size_max() -> list[tuple[Any, Any]]:
        return series(registry, cluster_metrics.entity_mailbox_size_max.id)

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        yield from testing.adjust("1 millis")
        first: list[Fiber[Any, Any]] = yield from fx.for_each(
            range(2), lambda _: make_client("1").never_volatile().fork()
        )
        yield from make_client("2").never_volatile().fork()
        yield from testing.adjust("1 millis")
        assert size_max() == [({"type": "TestEntity"}, metric.GaugeState(2))]
        yield from Fiber.interrupt_all(first)
        yield from _wait_for_idle_reap(service, 1)
        assert size_max() == [({"type": "TestEntity"}, metric.GaugeState(1))]

    yield from body.pipe(fx.provide(capped(entity_max_idle_time=millis(1)))).pipe(
        fx.provide_service(metric.MetricRegistry, registry)
    )
    # Shutting down closes the entity manager, which removes the series.
    assert size_max() == []


@testing.effect
def test_updates_the_shards_gauge_after_reassignment():
    """updates the shards gauge after reassignment"""
    storage = yield from runner_storage.make_memory()
    config = sharding_config.layer(
        replace(
            sharding_config.DEFAULTS,
            runner_address=RunnerAddress(host="localhost", port=1234),
            shards_per_group=8,
            refresh_assignments_interval=millis(10),
        )
    )
    built = (
        sharding.layer.pipe(
            fx.layer.provide(fx.layer.succeed(runner_storage.RunnerStorage, storage))
        )
        .pipe(fx.layer.provide(fx.layer.merge(runner_health.layer_noop, runners.layer_noop)))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(config))
    )

    @fx.gen
    def body():
        context = yield from built.build()
        service = context.get_unsafe(sharding.Sharding)
        shard_ids = [shard_id.make("default", i + 1) for i in range(8)]

        def held() -> int:
            return sum(1 for s in shard_ids if service.has_shard_id(s))

        while held() != 8:
            yield from testing.adjust("10 millis")
        assert cluster_metrics.shards.value_unsafe(Context.empty()).value == 8
        other = Runner(
            address=RunnerAddress(host="localhost", port=5678), groups=("default",), weight=1
        )
        yield from storage.register(other, True)
        while held() != 4:
            yield from testing.adjust("10 millis")
        assert cluster_metrics.shards.value_unsafe(Context.empty()).value == 4

    yield from scoped(body)


@testing.effect
def test_streams_registration_events_for_entities_and_singletons():
    """Not an Effect title: ``getRegistrationEvents`` publishes each entity
    and singleton registered after a subscriber starts."""

    @fx.gen
    def build():
        value = yield from RegistrationContext()
        return RegistrationContextEntity.handlers().handle(RegistrationContextEntity.read)(
            lambda _: fx.succeed(value)
        )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        collected = (
            yield from service.get_registration_events.take(2)
            .run_collect()
            .fork(start_immediately=True)
        )
        yield from service.register_entity(RegistrationContextEntity, build, EntityOptions()).pipe(
            fx.provide_service(RegistrationContext, "registration")
        )
        yield from service.register_singleton("tick", fx.never, None)
        events = yield from collected.join()
        assert events[0] == EntityRegistered(RegistrationContextEntity)
        assert isinstance(events[1], SingletonRegistered)
        assert events[1].address.name == "tick"

    yield from scoped(body.pipe(fx.provide(test_sharding)))
