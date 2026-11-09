"""Ports of platform-node's ``test/cluster-integration/Smoke.test.ts``,
``Transport.test.ts``, ``StreamDisconnect.test.ts`` and
``Residency.test.ts`` on the cluster harness (``_cluster_harness``): real
socket runners in this process over localhost, on SQLite and on the
throwaway PostgreSQL server where Effect uses PostgreSQL and MySQL. Each
test's docstring is the Effect test title, without its backend prefix.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cluster import entity_address, snowflake
from pyfect.cluster import envelope as envelope_
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.context import Context
from pyfect.latch import Latch
from pyfect.rpc import fork
from pyfect.rpc import make as make_rpc

from ._cluster_harness import ClusterDatabase, make, make_raw_runner_client


class Ping(S.Class, identifier="Ping"):
    id: str

    def primary_key(self) -> str:
        return self.id


class SmokeEntity(
    Entity, type="ClusterIntegrationSmoke", rpc_annotations=Context.make(Persisted, True)
):
    ping = make_rpc("Ping", payload=Ping, success=S.String)


smoke_entity_layer = SmokeEntity.to_layer(
    SmokeEntity.handlers().handle(SmokeEntity.ping)(
        lambda request: fx.succeed(f"pong:{request.payload.id}")
    )
)


@testing.live(timeout="1 minute")
def test_persists_messages_and_rebalances_after_an_abrupt_runner_death(cluster_db: ClusterDatabase):
    """persists messages and rebalances after an abrupt runner death"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        cluster = yield from make(cluster_db, entities=smoke_entity_layer)
        yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(SmokeEntity)
        assert (yield from client("entity-1").ping(Ping(id="request-1"))) == "pong:request-1"

        yield from cluster.wait_until(
            "The smoke entity had no active owner",
            cluster.owner_of_entity(SmokeEntity, "entity-1").map(lambda o: o is not None),
        )
        owner = yield from cluster.owner_of_entity(SmokeEntity, "entity-1")
        assert owner is not None
        yield from cluster.kill(owner)
        yield from cluster.wait_for_stable_assignments()

        assert (yield from client("entity-1").ping(Ping(id="request-2"))) == "pong:request-2"
        assert (yield from cluster.replied_message_count) == 2

    yield from fx.scoped(fx.gen(body))


class TransportRequest(S.Class, identifier="ClusterTransportRequest"):
    id: str

    def primary_key(self) -> str:
        return self.id


class TransportEntity(
    Entity, type="ClusterIntegrationTransport", rpc_annotations=Context.make(Persisted, True)
):
    persisted = make_rpc("Persisted", payload=TransportRequest, success=S.String)
    volatile = make_rpc("Volatile", payload=TransportRequest, success=S.String).annotate(
        Persisted, False
    )


@testing.live(timeout="1 minute")
def test_treats_a_directional_socket_cut_as_runner_unavailable(cluster_db: ClusterDatabase):
    """treats a directional socket cut as RunnerUnavailable for volatile and recovers persisted"""
    backend = cluster_db.backend

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        volatile_entered, volatile_gate = Latch(), Latch()
        persisted_entered, persisted_gate = Latch(), Latch()
        attempts = {"volatile": 0, "persisted": 0}

        def persisted(request: Request[TransportRequest]) -> fx.Effect[str]:
            def enter() -> None:
                attempts["persisted"] += 1
                persisted_entered.open_unsafe()

            return (
                fx.sync(enter)
                .and_then(persisted_gate.wait())
                .as_(f"persisted:{request.payload.id}")
            )

        def volatile(request: Request[TransportRequest]) -> fx.Effect[str]:
            def enter() -> None:
                attempts["volatile"] += 1
                volatile_entered.open_unsafe()

            return (
                fx.sync(enter).and_then(volatile_gate.wait()).as_(f"volatile:{request.payload.id}")
            )

        entities = TransportEntity.to_layer(
            TransportEntity.handlers()
            .handle(TransportEntity.persisted)(persisted)
            .handle(TransportEntity.volatile)(volatile)
        )
        cluster = yield from make(cluster_db, entities=entities)
        [runner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(TransportEntity)

        volatile_call = (
            yield from client("volatile")
            .volatile(TransportRequest(id=f"{backend}-volatile"))
            .fork(start_immediately=True)
        )
        persisted_call = (
            yield from client("persisted")
            .persisted(TransportRequest(id=f"{backend}-persisted"))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The volatile request did not enter the runner before the socket cut",
            volatile_entered.wait().as_(True),
        )
        yield from cluster.wait_until(
            "The persisted request did not enter the runner before the socket cut",
            persisted_entered.wait().as_(True),
        )
        yield from cluster.cut_socket(runner, peer="client", direction="inbound")
        volatile_gate.open_unsafe()
        persisted_gate.open_unsafe()

        assert (yield from volatile_call.join()) == f"volatile:{backend}-volatile"
        assert (yield from persisted_call.join()) == f"persisted:{backend}-persisted"
        assert runner.state() == "running"
        # Volatile requests have no storage fallback, so the second attempt
        # proves the cut surfaced as RunnerUnavailable and was retried.
        assert attempts["volatile"] == 2
        # The persisted caller instead recovered the stored reply.
        assert attempts["persisted"] == 1

    yield from fx.scoped(fx.gen(body))


class WatchPayload(TypedDict):
    id: str


watch_rpc = make_rpc("Watch", payload=S.Struct(WatchPayload), success=S.Int, stream=True)


class WatchEntity(
    Entity,
    type="ClusterIntegrationStreamDisconnect",
    rpc_annotations=Context.make(Persisted, False),
):
    watch = watch_rpc


@testing.live(timeout="1 minute")
def test_dead_caller_socket_closed_with_no_further_messages(cluster_db: ClusterDatabase):
    """dead caller: socket closed with no further messages"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        counts = {"starts": 0, "stops": 0}

        def watch(_: Request[WatchPayload]) -> Any:
            def stopped() -> None:
                counts["stops"] += 1

            counts["starts"] += 1
            return fork(stream.never.ensuring(fx.sync(stopped)))

        entities = WatchEntity.to_layer(WatchEntity.handlers().handle(WatchEntity.watch)(watch))
        cluster = yield from make(cluster_db, entities=entities)
        [owner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()

        raw = yield from make_raw_runner_client(owner)
        entity_id = EntityId("watch-1")
        generator = yield from snowflake.Generator().pipe(fx.provide(snowflake.layer_generator))
        payload = yield from S.encode_effect(raw.codec_for(watch_rpc.payload_schema))({"id": "x"})
        request: envelope_.PartialRequest = envelope_.Request(
            request_id=generator.next_unsafe(),
            address=entity_address.EntityAddress(
                shard_id=owner.sharding.get_shard_id(
                    entity_id, WatchEntity.get_shard_group(entity_id)
                ),
                entity_type=EntityType(WatchEntity.type),
                entity_id=entity_id,
            ),
            tag="Watch",
            payload=payload,
        )

        @fx.gen
        def take_forever():
            queue = yield from raw.client.stream(
                {"request": request, "persisted": False}, as_queue=True
            )
            yield from queue.take().forever()

        caller = yield from fx.scoped(take_forever).fork(start_immediately=True)
        yield from cluster.wait_until(
            "host handler did not start", fx.sync(lambda: counts["starts"] == 1)
        )
        assert counts == {"starts": 1, "stops": 0}

        # The caller "dies": its socket closes and nothing else is ever sent.
        yield from raw.disconnect
        yield from cluster.wait_until(
            "host handler did not stop after the caller died",
            fx.sync(lambda: counts["stops"] == 1),
        )
        assert counts == {"starts": 1, "stops": 1}
        yield from caller.interrupt()

    yield from fx.scoped(fx.gen(body))


class IdPayload(TypedDict):
    id: str


class ResidencyEntity(
    Entity, type="ClusterIntegrationResidency", rpc_annotations=Context.make(Persisted, True)
):
    ping = make_rpc("Ping", payload=S.Struct(IdPayload), success=S.String)
    hold = make_rpc("Hold", payload=S.Struct(IdPayload))


@testing.live(timeout="90 seconds")
def test_stays_at_the_entity_cap_and_keeps_residents_moving(cluster_db: ClusterDatabase):
    """stays at the entity cap and keeps residents moving"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        hold_gate = Latch()
        entities = ResidencyEntity.to_layer(
            ResidencyEntity.handlers()
            .handle(ResidencyEntity.ping)(lambda request: fx.succeed(request.payload["id"]))
            .handle(ResidencyEntity.hold)(lambda _: hold_gate.wait()),
            max_idle_time="1 second",
            concurrency=2,
        )
        cluster = yield from make(
            cluster_db, entities=entities, config={"max_resident_entities": 3}
        )
        [runner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(ResidencyEntity)

        # fill every entity slot with a held request
        held: list[Any] = []
        for entity_id in ("held-1", "held-2", "held-3"):
            held.append(  # noqa: PERF401 - a comprehension cannot ``yield from``
                (yield from client(entity_id).hold({"id": entity_id}).fork(start_immediately=True))
            )
        yield from cluster.wait_until(
            "The held entities did not become resident",
            runner.sharding.active_entity_count.map(lambda count: count == 3),
        )

        # a backlog of messages for new entity ids stays in storage
        for i in range(1, 9):
            yield from client(f"backlog-{i}").ping.discard({"id": f"backlog-{i}"})

        # resident entities keep receiving messages while at the cap
        assert (yield from client("held-1").ping({"id": "first"})) == "first"
        assert (yield from client("held-2").ping({"id": "second"})) == "second"

        # the runner never spawned entities for the backlog
        assert (yield from runner.sharding.active_entity_count) == 3
        assert (yield from cluster.unprocessed_message_count) >= 8

        # release the held entities: as slots free up, the backlog drains in
        # waves without ever exceeding the cap
        hold_gate.open_unsafe()
        for fiber in held:
            yield from fiber.join()

        @fx.gen
        def drained():
            assert (yield from runner.sharding.active_entity_count) <= 3
            counts = yield from cluster.message_counts()
            return counts.unprocessed == 0 and counts.failed == 0

        yield from cluster.wait_until(
            "The backlog did not drain after entity slots freed up", drained, 45
        )

    yield from fx.scoped(fx.gen(body))
