"""pyfect-only: what happens to a runner's shards while its shard lock
operations fail, on the cluster harness (``_cluster_harness``), SQLite and
PostgreSQL.

- While only its lock operations fail, the runner force-releases its shards.
  Its liveness probe (an empty ``refresh``) still heartbeats, but a probe that
  works does not show that the locks work again: once the lock operations
  have failed for ``shard_lock_expiration``, the runner unregisters itself,
  and the other runners take its shards over. A lock refresh that works
  again registers it again, and it gets its shards back.
- Once its heartbeats fail too, the other runners stop listing it after
  ``shard_lock_expiration`` and take its shards over.

Effect 4.1.4 kept such a runner registered and healthy, so its shards ran
nowhere until its lock operations recovered; pyfect follows Effect's fix
(Effect-TS/effect#10689).

The first test keeps the faulted runner's heartbeat an hour ahead
(``keep_registered``), so only its own unregistration can hand its shards
over, never an expired heartbeat. ``test_sharding_lock_failure_heartbeats``
pins how much heartbeat slack it has before then.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pyfect as fx
from pyfect import testing
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
def test_a_peer_takes_over_the_shards_of_a_runner_whose_lock_operations_keep_failing(
    cluster_db: ClusterDatabase,
):
    def body() -> Body:
        cluster, faulted, peer, shards = yield from two_runners(cluster_db)
        expiration = cluster.config.shard_lock_expiration.to_seconds()

        # Only the runner's own unregistration can hand its shards over.
        yield from cluster.keep_registered(faulted)
        probes = faulted.controller.probes
        clock = yield from fx.clock.Clock()
        start = clock.current_time_millis_unsafe()
        yield from cluster.fault_storage(faulted, "locks")
        yield from cluster.wait_until(
            "The peer did not take over the faulted runner's shards",
            fx.sync(lambda: shards <= held_by(cluster, peer)),
        )
        # The lock operations failed for a whole lock expiration first.
        took = elapsed_since(clock, start)
        assert took >= expiration, f"The peer took over after {took:.2f}s"
        assert faulted.controller.probes > probes, "The liveness probe never heartbeat"
        assert not held_by(cluster, faulted), "The faulted runner reacquired a shard"
        registrations = yield from cluster.registrations()
        assert address_of(faulted) not in [row["address"] for row in registrations], (
            f"The faulted runner stayed registered: {registrations}"
        )

        # A lock refresh that works again registers it again.
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
