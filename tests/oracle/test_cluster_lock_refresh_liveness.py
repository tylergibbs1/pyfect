"""pyfect-only: what happens to a runner's shards while its shard lock
operations fail, on the cluster harness (``_cluster_harness``), SQLite and
PostgreSQL.

Both match Effect 4.1.4 (``cluster/Sharding.ts``, ``SqlRunnerStorage.ts``):

- While only its lock operations fail, the runner force-releases its shards
  but stays registered (the liveness probe, an empty ``refresh``, is a
  heartbeat on the shared pool) and healthy, so the hash ring keeps its
  shards assigned to it. Their locks expire, yet no other runner asks for
  them: they run nowhere until the runner's lock operations recover.
- Once its heartbeats fail too, the other runners stop listing it after
  ``shard_lock_expiration`` and take its shards over.

The first is a liveness gap in Effect: ``markShardLocksUnhealthy``
force-releases the shards, and ``probeShardLocks`` keeps the runner healthy
with an empty ``refresh`` (``Sharding.ts`` lines 700-756 at effect@4.1.4).
When Effect fixes it (Effect-TS/effect#10676, open), follow the fix and turn
that test around.

That test keeps the faulted runner registered (``keep_registered``): with
its lock refreshes failing it heartbeats only on every other refresh tick,
once a second, and SQLite's second-resolution heartbeats can expire it a
little over a second after one, so any delay under load let the peer
take its shards. ``test_sharding_lock_failure_heartbeats`` pins that margin.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.cluster import runner_address, sql_runner_storage
from pyfect.cluster import shard_id as shard_id_
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.scope import Scope

from ._cluster_harness import Cluster, ClusterDatabase, ClusterRunner, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]

CONFIG = {"shards_per_group": 8}


def address_of(runner: ClusterRunner) -> str:
    return f"{runner.address.host}:{runner.address.port}"


def held_by(cluster: Cluster, runner: ClusterRunner) -> set[str]:
    key = address_of(runner)
    return {shard for shard, owners in cluster.assignment_map().items() if key in owners}


def two_runners(
    cluster_db: ClusterDatabase,
) -> fx.Effect[tuple[Cluster, ClusterRunner, ClusterRunner, set[str]], Any, Scope]:
    """A stable cluster of two runners, the first's shards."""

    @fx.gen
    def start():
        cluster = yield from make(cluster_db, entities=fx.layer.empty, config=CONFIG)
        [faulted, peer] = yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        shards = held_by(cluster, faulted)
        assert shards, "The first runner held no shards"
        return cluster, faulted, peer, shards

    return start


def elapsed_since(clock: Any, start: float) -> float:
    return (clock.current_time_millis_unsafe() - start) / 1000


def run(body: Callable[[], Body]) -> fx.Effect[None, Any]:
    return fx.scoped(fx.gen(body))


@testing.live(timeout="90 seconds")
def test_shards_stay_assigned_to_a_registered_runner_whose_lock_operations_fail(
    cluster_db: ClusterDatabase,
):
    def body() -> Body:
        cluster, faulted, peer, shards = yield from two_runners(cluster_db)
        expiration = cluster.config.shard_lock_expiration.to_seconds()

        # Registration expiry is not what this test is about; the heartbeat
        # margin is test_sharding_lock_failure_heartbeats's.
        yield from cluster.keep_registered(faulted)
        yield from cluster.fault_storage(faulted, "locks")
        yield from cluster.wait_until(
            "The faulted runner did not release its shards",
            fx.sync(lambda: not held_by(cluster, faulted)),
        )

        # Four lock expirations: every lock of the faulted runner has
        # expired, and the peer has read the runners many times over.
        clock = yield from fx.clock.Clock()
        start = clock.current_time_millis_unsafe()
        probes = faulted.controller.probes
        while elapsed_since(clock, start) < 4 * expiration:
            taken = held_by(cluster, peer) & shards
            assert not taken, f"The peer took over {taken}"
            assert not held_by(cluster, faulted), "The faulted runner reacquired a shard"
            yield from fx.sleep("100 millis")
        assert faulted.controller.probes > probes, "The liveness probe never heartbeat"

        registrations = yield from cluster.registrations()
        faulted_rows = [row for row in registrations if row["address"] == address_of(faulted)]
        assert faulted_rows and faulted_rows[0]["healthy"], (
            f"The faulted runner was not registered healthy: {registrations}"
        )

        # The locks are free: a runner asking for them gets every one.
        scope = yield from Scope()
        probe_context = yield from (
            sql_runner_storage.layer_with(prefix=cluster.prefix)
            .pipe(fx.layer.provide(sharding_config_.layer(cluster.config)))
            .build_with_scope(scope)
            .pipe(fx.provide(cluster.database))
        )
        probe = probe_context.get_unsafe(RunnerStorage)
        probe_address = runner_address.make("127.0.0.1", 1)
        wanted = [shard_id_.from_string(shard) for shard in sorted(shards)]
        acquired = yield from probe.acquire(probe_address, wanted)
        yield from probe.release_all(probe_address)
        assert {str(shard) for shard in acquired} == shards, (
            f"The faulted runner's locks were still held: got {acquired}"
        )

        yield from cluster.fault_storage(faulted, "none")
        yield from cluster.wait_until(
            "The recovered runner did not reacquire its shards",
            fx.sync(lambda: held_by(cluster, faulted) == shards),
        )

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_a_runner_whose_heartbeats_fail_too_loses_its_shards_after_the_lock_expiration(
    cluster_db: ClusterDatabase,
):
    def body() -> Body:
        cluster, faulted, peer, shards = yield from two_runners(cluster_db)
        expiration = cluster.config.shard_lock_expiration.to_seconds()
        refresh = cluster.config.shard_lock_refresh_interval.to_seconds()

        clock = yield from fx.clock.Clock()
        start = clock.current_time_millis_unsafe()
        yield from cluster.fault_storage(faulted, "storage")
        yield from cluster.wait_until(
            "The peer did not take over the faulted runner's shards",
            fx.sync(lambda: shards <= held_by(cluster, peer)),
        )
        # Its last heartbeat was at most one refresh interval before the fault.
        took = elapsed_since(clock, start)
        assert took >= expiration - refresh, f"The peer took over after {took:.2f}s"

        yield from cluster.fault_storage(faulted, "none")
        yield from cluster.wait_for_stable_assignments()

    yield from run(body)
