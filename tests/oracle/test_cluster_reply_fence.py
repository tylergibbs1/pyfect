"""pyfect-only: a persisted reply is stored only once a lock refresh confirms
the runner still owns the request's shard, on the cluster harness
(``_cluster_harness``), SQLite.

Both match Effect (``cluster/internal/entityManager.ts`` ``isShardOwned``,
``cluster/Sharding.ts`` ``confirmShardLock``): when lock storage stalls past
``shard_lock_refresh_interval`` while a request is in flight, the
confirmation times out, the reply is not stored, and the request replays
once the runner's lock storage recovers. Its handler runs again: delivery is
at least once. A reply that was stored is served to every later caller, and
the handler never runs for it again.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, Request
from pyfect.context import Context
from pyfect.rpc import make as make_rpc

from ._cluster_harness import ClusterDatabase, MessageCounts, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]

STALL_SECONDS = 0.9
"""Longer than the harness's 500 ms lock refresh, so the confirmation of the
first run's reply times out."""


class FencePayload(S.Class, identifier="ClusterReplyFencePayload"):
    id: str

    def primary_key(self) -> str:
        return self.id


class FenceEntity(Entity, type="ClusterReplyFence", rpc_annotations=Context.make(Persisted, True)):
    run = make_rpc("Run", payload=FencePayload, success=S.Number)


@pytest.mark.parametrize("cluster_db", ["sqlite"], indirect=True)
@testing.live(timeout="1 minute")
def test_a_reply_fenced_by_a_lock_storage_stall_replays_and_is_then_served_from_storage(
    cluster_db: ClusterDatabase,
):
    """The first run's reply is fenced while the database stalls, so the
    request runs again; the second run's reply is stored, and a duplicate
    request reads it without running the handler."""
    runs: list[int] = []

    def handle(request: Request[FencePayload]) -> fx.Effect[float]:
        def run() -> float:
            runs.append(len(runs) + 1)
            return float(len(runs))

        stall = cluster_db.hold_write_lock(STALL_SECONDS) if not runs else fx.void
        return stall.and_then(fx.sync(run))

    entities = FenceEntity.to_layer(FenceEntity.handlers().handle(FenceEntity.run)(handle))

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=entities)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(FenceEntity)
        payload = FencePayload(id="fenced")

        assert (yield from client("fence").run(payload)) == 2
        assert runs == [1, 2]
        assert (yield from client("fence").run(payload)) == 2
        assert runs == [1, 2]
        assert (yield from cluster.message_counts()) == MessageCounts(0, 1, 0)

    yield from fx.scoped(fx.gen(body))
