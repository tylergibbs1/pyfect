"""Ports of the last "Sharding shard lock failover" cases of Effect's
``test/cluster/Sharding.test.ts``: graceful handoff while the lock is still
held, a remote request held until the lock is acquired, and forced releases,
over Effect's ``FailoverStorage`` (``_failover_storage``). Each test's
docstring is the Effect test title."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cluster import (
    cluster_metrics,
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import IncomingRequest
from pyfect.cluster.message_storage import MessageStorageService
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.duration import Seconds
from pyfect.layer import Layer

from . import _cluster_entities as entities
from ._cluster_entities import TestEntity, test_entity_no_state, test_entity_state_layer
from ._failover_storage import FailoverState, failover_storage_layer
from ._sharding_fixtures import patched, update_storage

EntityState = entities.TestEntityState

_runner_address = RunnerAddress(host="localhost", port=1234)


def _config(**changes: Any) -> Layer[sharding_config.ShardingConfig]:
    return sharding_config.layer(
        replace(sharding_config.DEFAULTS, runner_address=_runner_address, **changes)
    )


def _entity_sharding(
    state: FailoverState, sharding_layer: Layer[Any, Any, Any] = sharding.layer, **config: Any
) -> Layer[Any]:
    return (
        test_entity_no_state.pipe(fx.layer.provide_merge(sharding_layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(_config(**config)))
    )


def _graceful_handoff_sharding(state: FailoverState) -> Layer[Any]:
    """Effect's ``GracefulHandoffSharding``."""
    return _entity_sharding(
        state,
        shards_per_group=1,
        entity_termination_timeout=Seconds(1),
        entity_message_poll_interval=Seconds(0.01),
        refresh_assignments_interval=Seconds(0.01),
        send_retry_interval=Seconds(0.01),
    )


def _forced_release_sharding(state: FailoverState, **changes: Any) -> Layer[Any]:
    defaults: dict[str, Any] = {
        "shards_per_group": 1,
        "shard_lock_expiration": Seconds(0.3),
        "shard_lock_refresh_interval": Seconds(1),
        "entity_termination_timeout": Seconds(0),
        "entity_message_poll_interval": Seconds(0.01),
        "refresh_assignments_interval": Seconds(0.01),
        "send_retry_interval": Seconds(0.01),
    }
    return _entity_sharding(state, **(defaults | changes))


@fx.fn
def _await_shard(service: sharding.ShardingService, shard_id: ShardId):
    while not service.has_shard_id(shard_id):
        yield from testing.adjust(0.01)


@fx.fn
def _await_release(service: sharding.ShardingService, shard_id: ShardId):
    while service.has_shard_id(shard_id):
        yield from testing.adjust(0.01)


@testing.effect
def test_keeps_the_graceful_timeout_and_records_release_duration_across_retries_for_shard_reassignment():  # noqa: E501
    """keeps the graceful timeout and records release duration across retries for shard reassignment"""  # noqa: E501
    state = FailoverState(release_failures=1)
    unregister_interrupts: list[bool] = []

    def track(storage: MessageStorageService) -> MessageStorageService:
        def unregister(shard_id: ShardId, *, interrupt: bool = False) -> fx.Effect[None]:
            def record() -> None:
                unregister_interrupts.append(interrupt)

            return fx.sync(record).and_then(
                storage.unregister_shard_reply_handlers(shard_id, interrupt=interrupt)
            )

        return patched(storage, unregister_shard_reply_handlers=unregister)

    layer = _entity_sharding(
        state,
        sharding.layer.pipe(fx.layer.provide(update_storage(track))),
        shards_per_group=1,
        shard_lock_expiration=Seconds(3),
        shard_lock_refresh_interval=Seconds(0.1),
        entity_termination_timeout=Seconds(1),
        entity_message_poll_interval=Seconds(0.01),
        refresh_assignments_interval=Seconds(0.01),
        send_retry_interval=Seconds(0.01),
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        client = (yield from TestEntity.client())("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        before = cluster_metrics.shard_release_duration.value_unsafe(Context.empty())

        yield from _await_shard(service, shard_id)
        entity_fiber = yield from client.never_volatile().fork(start_immediately=True)
        yield from testing.adjust(0.001)

        state.assign_self = False
        yield from _await_release(service, shard_id)
        while (yield from service.active_entity_count) > 0:
            yield from testing.adjust(0.001)

        assert entity_fiber.poll_unsafe() is None
        assert len(state.release_calls) == 0
        yield from testing.adjust(0.9)
        assert entity_fiber.poll_unsafe() is None
        assert len(state.release_calls) == 0

        for _ in range(20):
            if entity_fiber.poll_unsafe() is not None:
                break
            yield from testing.adjust(0.01)
        entity_exit = entity_fiber.poll_unsafe()
        assert isinstance(entity_exit, Exit.Failure) and entity_exit.cause.has_interrupts
        assert len(state.release_calls) == 1
        assert (
            cluster_metrics.shard_release_duration.value_unsafe(Context.empty()).count
            == before.count
        )
        yield from testing.adjust(0.05)
        assert len(state.release_calls) == 2
        assert unregister_interrupts == [False]
        after = cluster_metrics.shard_release_duration.value_unsafe(Context.empty())
        assert after.count - before.count == 1
        assert after.sum - before.sum == 1050

    yield from fx.scoped(body).pipe(fx.provide(layer))


@testing.effect
def test_delivers_a_client_interrupt_to_a_request_still_draining_on_the_lock_holder():
    """delivers a client interrupt to a request still draining on the lock holder"""
    state = FailoverState()

    @fx.gen
    def body():
        entity_state = yield from EntityState()
        service = yield from sharding.Sharding()
        client = (yield from TestEntity.client())("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        yield from _await_shard(service, shard_id)
        request = yield from client.never_volatile().fork(start_immediately=True)
        yield from entity_state.envelopes.take()
        state.assign_self = False
        yield from _await_release(service, shard_id)
        assert len(state.release_calls) == 0, "the shard lock must still be held"

        yield from request.interrupt().fork(start_immediately=True)
        yield from testing.adjust(0.1)
        assert entity_state.interrupts.size_unsafe() == 1

    yield from fx.scoped(body).pipe(fx.provide(_graceful_handoff_sharding(state)))


@testing.effect
def test_acknowledges_stream_chunks_from_a_request_still_draining_on_the_lock_holder():
    """acknowledges stream chunks from a request still draining on the lock holder"""
    state = FailoverState()

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        client = (yield from TestEntity.client())("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        yield from _await_shard(service, shard_id)
        # With one buffered chunk, the second is acknowledged only once the
        # first is consumed.
        users = yield from client.get_all_users_volatile(
            {"ids": [1, 2]}, as_queue=True, stream_buffer_size=1
        )
        yield from testing.adjust(0.001)
        state.assign_self = False
        yield from _await_release(service, shard_id)

        consumed = yield from (stream.from_queue(users).run_collect().fork(start_immediately=True))
        yield from testing.adjust(0.1)
        exit = consumed.poll_unsafe()
        assert isinstance(exit, Exit.Success), exit
        assert [user.id for user in exit.value] == [1, 2]

    yield from fx.scoped(body).pipe(fx.provide(_graceful_handoff_sharding(state)))


@testing.effect
def test_holds_a_remote_request_on_the_new_owner_until_it_acquires_the_shard_lock():
    """holds a remote request on the new owner until it acquires the shard lock"""
    state = FailoverState(lock_held_elsewhere=True)

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_id = EntityId("1")
        shard_id = service.get_shard_id(entity_id, "default")
        while not state.acquire_calls:
            yield from testing.adjust(0.01)
        delivery = yield from service.send(
            IncomingRequest(
                envelope=make_request(
                    request_id=Snowflake(1),
                    address=EntityAddress(
                        shard_id=shard_id, entity_type=TestEntity.type, entity_id=entity_id
                    ),
                    tag="GetUserVolatile",
                    payload={"id": 1},
                ),
                last_sent_reply=None,
                respond=lambda _: fx.void,
                codec_for=S.to_codec_json,
            )
        ).fork(start_immediately=True)
        yield from testing.adjust(0.01)
        assert delivery.poll_unsafe() is None, "delivery must wait for the shard lock"

        state.lock_held_elsewhere = False
        yield from _await_shard(service, shard_id)
        assert (yield from delivery.await_exit()) == Exit.succeed(None)

    yield from fx.scoped(body).pipe(fx.provide(_graceful_handoff_sharding(state)))


@testing.effect
def test_does_not_wait_for_entity_construction_before_a_forced_shard_release():
    """does not wait for entity construction before a forced shard release"""
    state = FailoverState()

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_state = yield from EntityState()
        client = (yield from TestEntity.client())("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        yield from _await_shard(service, shard_id)
        while not any(call.shards for call in state.refresh_calls):
            yield from testing.adjust(0.1)

        @fx.gen
        def blocked():
            entity_state.build_latch.close_unsafe()
            entity_fiber = yield from client.get_user_volatile({"id": 1}).fork(
                start_immediately=True
            )
            while entity_state.layer_builds[0] == 0:
                yield from testing.adjust(0.001)

            state.blackholed = True
            yield from testing.adjust(0.201)
            assert not service.has_shard_id(shard_id)

            state.blackholed = False
            yield from testing.adjust(1)

            assert len(state.release_all_calls) == 1
            entity_state.build_latch.open_unsafe()
            yield from testing.adjust(0.001)
            yield from entity_fiber.interrupt()

        yield from blocked.ensuring(entity_state.build_latch.open())

    yield from fx.scoped(body).pipe(fx.provide(_forced_release_sharding(state)))


@testing.effect
def test_does_not_register_an_entity_built_after_shard_release():
    """does not register an entity built after shard release"""
    state = FailoverState()

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_state = yield from EntityState()
        client = (yield from TestEntity.client())("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        yield from _await_shard(service, shard_id)

        @fx.gen
        def blocked():
            entity_state.build_latch.close_unsafe()
            entity_fiber = yield from client.get_user_volatile({"id": 1}).fork(
                start_immediately=True
            )
            while entity_state.layer_builds[0] == 0:
                yield from testing.adjust(0.001)

            state.assign_self = False
            while not state.release_calls:
                yield from testing.adjust(0.01)
            assert not service.has_shard_id(shard_id)

            entity_state.build_latch.open_unsafe()
            yield from testing.adjust(0.01)

            assert (yield from service.active_entity_count) == 0
            assert entity_state.envelopes.size_unsafe() == 0
            assert entity_fiber.poll_unsafe() is None

        yield from blocked.ensuring(entity_state.build_latch.open())

    yield from fx.scoped(body).pipe(
        fx.provide(
            _forced_release_sharding(
                state, shard_lock_expiration=Seconds(3), shard_lock_refresh_interval=Seconds(0.1)
            )
        )
    )


@testing.effect
def test_does_not_acquire_shards_while_a_forced_release_is_pending():
    """does not acquire shards while a forced release is pending"""
    shards_per_group = 4
    state = FailoverState(other_runner_healthy=True, release_all_duration=0.5)

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        all_shards = [shard("default", i + 1) for i in range(shards_per_group)]

        def owned_count() -> int:
            return len([s for s in all_shards if service.has_shard_id(s)])

        # The other runner holds part of the ring, so this runner starts with
        # a strict subset of the shards.
        while owned_count() == 0:
            yield from testing.adjust(0.01)
        assert owned_count() < shards_per_group
        while not any(call.shards for call in state.refresh_calls):
            yield from testing.adjust(0.1)

        acquires_before_outage = len(state.acquire_calls)
        state.blackholed = True
        yield from testing.adjust(0.201)
        assert owned_count() == 0

        # The other runner's shards are reassigned to this runner during the
        # outage, so they are not part of the forced release set.
        state.other_runner_healthy = False
        yield from testing.adjust(0.1)
        assert len(state.release_all_calls) == 0

        # Recovery runs the forced release, which stays in flight for
        # ``release_all_duration``.
        state.blackholed = False
        while not state.release_all_calls:
            yield from testing.adjust(0.01)
        while not state.release_all_calls[0].completed:
            yield from testing.adjust(0.01)
        # Keep shutdown from blocking on the finalizer release.
        state.release_all_duration = 0

        while owned_count() < shards_per_group:
            yield from testing.adjust(0.01)

        # ``release_all`` drops every lock held by this runner, so nothing may
        # be acquired before it has completed.
        assert len(state.release_all_calls) == 1
        assert all(
            call.completed_release_alls > 0 for call in state.acquire_calls[acquires_before_outage:]
        )

    yield from fx.scoped(body).pipe(
        fx.provide(_forced_release_sharding(state, shards_per_group=shards_per_group))
    )
