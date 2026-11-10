"""Ports of the live-clock shutdown cases of Effect's
``test/cluster/Sharding.test.ts``: a runner shutting down while an entity's
finalizer still talks to another entity, and persisted failures that cannot
be written as JSON. Each test's docstring is the Effect test title."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MemoryDriver, MemoryDriverService
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.deferred import Deferred
from pyfect.duration import millis
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.rpc import make as make_rpc
from pyfect.rpc import rpc_schema

from ._cluster_entities import TestEntity
from ._sharding_fixtures import test_sharding


@testing.live
def test_defects_instead_of_hanging_when_persisted_failures_contain_non_json_error_values():
    """defects instead of hanging when persisted failures contain non-JSON Error values"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        cause = yield from client.fail().timeout("2 seconds").sandbox().flip()
        assert cause.has_dies
        assert "MalformedMessage" in cause.pretty()
        assert len(driver.encoded.reply_ids) == 1
        assert len(driver.encoded.unprocessed) == 0

    yield from body.pipe(fx.provide(test_sharding))


def _live_env(entities: Layer[Never, Never, Any], **changes: Any) -> Layer[Any]:
    defaults: dict[str, Any] = {
        "runner_address": RunnerAddress(host="localhost", port=1234),
        "shards_per_group": 8,
        "entity_termination_timeout": millis(0),
        "entity_message_poll_interval": millis(50),
        "refresh_assignments_interval": millis(20),
        "send_retry_interval": millis(10),
    }
    config = sharding_config.layer(replace(sharding_config.DEFAULTS, **(defaults | changes)))
    return (
        entities.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(config))
    )


def _arm_and_shut_down(
    env: Layer[Any], arm: Any, hang_message: str
) -> fx.Effect[tuple[Exit.Exit[Any, Any], MemoryDriverService], Any]:
    """Waits for the sender's shard, arms the sender, then interrupts the run
    so the Sharding scope closes and the sender's finalizer runs during
    teardown; gives the run's exit (it must not hang) and the driver."""

    @fx.gen
    def run():
        shard_acquired = Latch()
        armed = Latch()
        seen: dict[str, MemoryDriverService] = {}

        @fx.gen
        def runner():
            seen["driver"] = yield from MemoryDriver()
            service = yield from sharding.Sharding()
            shard_id = service.get_shard_id(EntityId("1"), "default")
            while not service.has_shard_id(shard_id):
                yield from fx.sleep("5 millis")
            yield from shard_acquired.open()
            yield from arm
            yield from armed.open()
            return (yield from fx.never)

        run_fiber = yield from fx.scoped(runner).pipe(fx.provide(env)).fork_daemon()
        acquired = yield from shard_acquired.wait().timeout_option("8 seconds")
        if acquired is None:
            run_fiber.interrupt_as_unsafe(None)
            yield from run_fiber.await_exit()
        assert acquired is not None, "Timed out waiting for sender shard acquisition"
        yield from armed.wait()

        # Interrupting the fiber closes the Sharding scope, running the entity
        # finalizer as part of teardown
        run_fiber.interrupt_as_unsafe(None)
        completed = yield from run_fiber.await_exit().timeout_option("4 seconds")
        assert completed is not None, hang_message
        return completed.value, seen["driver"]

    return run


@pytest.mark.parametrize("preemptive_shutdown", [True, False])
@pytest.mark.parametrize("persisted", [False, True])
@testing.live(timeout="20 seconds")
def test_shutdown_completes_when_a_finalizing_entity_sends_an_outgoing_message(
    persisted: bool, preemptive_shutdown: bool
):
    """shutdown completes when a finalizing entity sends an outgoing message (persisted=${persisted}, preemptiveShutdown=${preemptiveShutdown})"""  # noqa: E501

    class Receiver(Entity, type="ShutdownDeadlockReceiver"):
        ping = make_rpc("Ping").annotate(Persisted, persisted)

    class Sender(Entity, type="ShutdownDeadlockSender"):
        arm = make_rpc("Arm").annotate(Persisted, False)

    @fx.gen
    def body():
        discard_exit = yield from Deferred[Exit.Exit[None, Any], Never].make()

        @fx.gen
        def build_sender():
            receiver = yield from Receiver.client()
            # finalizer sends an outgoing message during entity teardown
            yield from fx.add_finalizer(
                lambda _: (
                    fx.sleep("300 millis")
                    .and_then(receiver("peer").ping.discard())
                    .exit()
                    .flat_map(discard_exit.succeed)
                    .as_void()
                    .uninterruptible()
                )
            )
            return Sender.handlers().handle(Sender.arm)(lambda _: fx.void)

        entities = fx.layer.merge(
            Sender.to_layer_effect(build_sender),
            Receiver.to_layer(Receiver.handlers().handle(Receiver.ping)(lambda _: fx.void)),
        )
        env = _live_env(entities, preemptive_shutdown=preemptive_shutdown)

        @fx.gen
        def arm():
            yield from (yield from Sender.client())("1").arm()

        _, driver = yield from _arm_and_shut_down(
            env, arm, "Sharding scope-close hung during shutdown (deadlock)"
        )
        assert isinstance((yield from discard_exit.wait()), Exit.Success), (
            "discard send failed during shutdown"
        )
        assert len(driver.encoded.journal) == (1 if persisted else 0)

    yield from body


@pytest.mark.parametrize("persisted", [False, True])
@testing.live(timeout="20 seconds")
def test_shutdown_completes_when_a_finalizing_entity_awaits_a_reply_from_an_unroutable_entity(
    persisted: bool,
):
    """shutdown completes when a finalizing entity awaits a reply from an unroutable entity (persisted=${persisted})"""  # noqa: E501

    class Receiver(Entity, type="StrandReceiver"):
        ping = make_rpc("Ping").annotate(Persisted, persisted)

    class Sender(Entity, type="StrandSender"):
        arm = make_rpc("Arm").annotate(Persisted, False)

    @fx.gen
    def body():
        request_exit = yield from Deferred[Exit.Exit[None, Any], Never].make()

        @fx.gen
        def build_sender():
            receiver = yield from Receiver.client()
            # uninterruptible finalizer that awaits a reply from another entity
            yield from fx.add_finalizer(
                lambda _: (
                    fx.sleep("300 millis")
                    .and_then(receiver("peer").ping())
                    .exit()
                    .flat_map(request_exit.succeed)
                    .as_void()
                    .uninterruptible()
                )
            )
            return Sender.handlers().handle(Sender.arm)(lambda _: fx.void)

        entities = fx.layer.merge(
            Sender.to_layer_effect(build_sender),
            Receiver.to_layer(Receiver.handlers().handle(Receiver.ping)(lambda _: fx.void)),
        )

        @fx.gen
        def arm():
            yield from (yield from Sender.client())("1").arm()

        completed, driver = yield from _arm_and_shut_down(
            _live_env(entities), arm, "Sharding scope-close hung during shutdown (stranded caller)"
        )
        assert not (isinstance(completed, Exit.Failure) and completed.cause.has_dies), (
            "finalizer defected instead of failing cleanly"
        )
        exit = yield from request_exit.wait()
        assert isinstance(exit, Exit.Failure), (
            "request succeeded instead of failing during shutdown"
        )
        if persisted:
            # A persisted request is durable, so a transient routing state is
            # not an error: the caller is interrupted instead, and the request
            # is served under the next owner.
            assert exit.cause.has_interrupts_only, "persisted request was not interrupted"
        else:
            failure = exit.cause.find_error()
            assert isinstance(failure, fx.Ok), "request did not fail with a typed error"
            assert isinstance(failure.value, EntityNotAssignedToRunner)
        assert len(driver.encoded.journal) == (1 if persisted else 0)

    yield from body


class ShutdownStreamReceiver(Entity, type="ShutdownStreamReceiver"):
    values = make_rpc("Values", success=rpc_schema.Stream(S.Number, S.Never)).annotate(
        Persisted, True
    )


class ShutdownStreamSender(Entity, type="ShutdownStreamSender"):
    arm = make_rpc("Arm").annotate(Persisted, False)


@testing.live(timeout="20 seconds")
def test_fails_a_stream_when_its_chunk_acknowledgement_is_abandoned_during_shutdown():
    """fails a stream when its chunk acknowledgement is abandoned during shutdown"""

    @fx.gen
    def body():
        chunks = yield from Queue[float, Never].unbounded()
        stream_started = yield from Deferred[None, Never].make()
        stream_exit = yield from Deferred[Exit.Exit[None, Any], Never].make()
        r = ShutdownStreamReceiver
        s = ShutdownStreamSender

        @fx.gen
        def build_sender():
            receiver = yield from r.client()
            stream_fiber = yield from (
                receiver("peer")
                .values()
                .run_drain()
                .uninterruptible()
                .fork_scoped(start_immediately=True)
            )
            yield from stream_started.wait()
            yield from fx.add_finalizer(
                lambda _: (
                    chunks.offer(1)
                    .and_then(stream_fiber.await_exit())
                    .flat_map(stream_exit.succeed)
                    .as_void()
                    .uninterruptible()
                )
            )
            return s.handlers().handle(s.arm)(lambda _: fx.void)

        entities = fx.layer.merge(
            s.to_layer_effect(build_sender),
            r.to_layer(
                r.handlers().handle(r.values)(
                    lambda _: stream.from_queue(chunks).on_start(stream_started.succeed(None))
                )
            ),
        )

        @fx.gen
        def arm():
            yield from (yield from s.client())("1").arm()

        _, driver = yield from _arm_and_shut_down(
            _live_env(entities, entity_termination_timeout=millis(1000)),
            arm,
            "Sharding scope-close hung after abandoning a stream chunk acknowledgement",
        )
        exit = yield from stream_exit.wait()
        assert isinstance(exit, Exit.Failure), "stream succeeded instead of failing during shutdown"
        failure = exit.cause.find_error()
        assert isinstance(failure, fx.Ok), "stream did not fail with a typed error"
        assert isinstance(failure.value, EntityNotAssignedToRunner)
        acks = [e for e in driver.encoded.journal if e["_tag"] == "AckChunk"]
        assert len(acks) == 1

    yield from body
