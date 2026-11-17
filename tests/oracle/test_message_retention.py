"""Ports of Effect's ``test/cluster/MessageRetention.test.ts``
(``pyfect.cluster.message_retention``). Each test's docstring is the Effect
test title."""

from __future__ import annotations

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    message_retention,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.context import Context
from pyfect.duration import millis
from pyfect.rpc import make as make_rpc

from ._sharding_fixtures import make_config


class HitPayload(S.Class):
    id: str

    def primary_key(self) -> str:
        return self.id


hit = make_rpc("Hit", payload=HitPayload, success=S.Number)


class Retained(Entity, type="Retained", rpc_annotations=Context.make(Persisted, True)):
    hit = hit


class Unretained(Entity, type="Unretained", rpc_annotations=Context.make(Persisted, True)):
    hit = hit


# Effect's test refreshes assignments every 0 ms, so the sync loop never sleeps and
# runs a step budget of storage reads on every scheduler turn of the eleven minutes the
# test clock moves. Refreshing every minute still assigns the shards at the start.
config = make_config(refresh_assignments_interval=millis(60_000))

retention_sharding = (
    sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
    .pipe(fx.layer.provide(runner_health.layer_noop))
    .pipe(fx.layer.provide(runners.layer_noop))
    .pipe(fx.layer.provide_merge(message_storage.layer_memory))
    .pipe(fx.layer.provide(config))
)


@testing.effect
def test_forgets_completed_requests_of_entities_registered_with_message_retention():
    """forgets completed requests of entities registered with MessageRetention"""
    runs = {"retained": 0, "unretained": 0}

    def count(name: str) -> fx.Effect[int]:
        def bump() -> int:
            runs[name] += 1
            return runs[name]

        return fx.sync(bump)

    layer = fx.layer.merge(
        Retained.to_layer(Retained.handlers().handle(Retained.hit)(lambda _: count("retained"))),
        message_retention.make(entity=Retained, retention="10 minutes", interval="1 minute"),
        Unretained.to_layer(
            Unretained.handlers().handle(Unretained.hit)(lambda _: count("unretained"))
        ),
    ).pipe(fx.layer.provide_merge(retention_sharding))

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        retained = (yield from Retained.client())("one")
        unretained = (yield from Unretained.client())("one")
        hit_both = fx.all(retained.hit(HitPayload(id="a")), unretained.hit(HitPayload(id="a")))
        yield from hit_both

        # the reply is younger than the retention, so the duplicate is still answered from storage
        yield from testing.adjust("5 minutes")
        yield from hit_both
        assert runs == {"retained": 1, "unretained": 1}

        yield from testing.adjust("6 minutes")
        yield from hit_both
        assert runs == {"retained": 2, "unretained": 1}

    yield from body.pipe(fx.provide(layer))
