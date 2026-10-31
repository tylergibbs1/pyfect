"""Ports of platform-node's ``test/cluster-integration/Locks.test.ts`` on the
cluster harness (``_cluster_harness``). Each test's docstring is the Effect
test title, without its backend prefix.

They run on the throwaway PostgreSQL server only: the faults act on the
runner storage's reserved lock connection, which SQLite does not have (its
shard locks are rows written through the shared client). Effect runs them on
PostgreSQL and MySQL.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing

from ._cluster_harness import ClusterDatabase, ClusterRunner, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]

CONFIG = {"shards_per_group": 4}


def address_of(runner: ClusterRunner) -> str:
    return f"{runner.address.host}:{runner.address.port}"


def run(cluster_db: ClusterDatabase, body: Callable[[], Body]) -> fx.Effect[None, Any]:
    if cluster_db.backend != "pg":
        pytest.skip("SQLite has no reserved lock connection to fault")
    return fx.scoped(fx.gen(body))


@testing.live(timeout=90)
def test_rebuilds_a_blackholed_reserved_lock_connection_and_rejoins_without_split_brain(
    cluster_db: ClusterDatabase,
):
    """rebuilds a blackholed reserved lock connection and rejoins without split brain"""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=fx.layer.empty, config=CONFIG)
        [faulted] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        faulted_address = address_of(faulted)

        yield from cluster.fault_lock(faulted, "blackhole")
        [peer] = yield from cluster.start(1)
        peer_address = address_of(peer)

        @fx.gen
        def taken_over():
            yield from cluster.fault_lock(faulted, "blackhole")
            assignments = list(cluster.assignment_map().values())
            assert all(len(owners) <= 1 for owners in assignments), "A shard had multiple owners"
            return all(faulted_address not in owners for owners in assignments) and any(
                peer_address in owners for owners in assignments
            )

        yield from cluster.wait_until(
            "The peer did not take over shards after the lock connection was blackholed",
            taken_over,
        )

        yield from cluster.fault_lock(faulted, "clear")
        recovered = yield from cluster.wait_for_stable_assignments()
        assert any(faulted_address in owners for owners in recovered.values()), (
            "The recovered runner did not rejoin the assignment ring"
        )

    yield from run(cluster_db, body)


@testing.live(timeout=90)
def test_does_not_reacquire_a_shard_before_forced_release_completes(
    cluster_db: ClusterDatabase,
):
    """does not reacquire a shard before forced release completes"""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=fx.layer.empty, config=CONFIG)
        [faulted] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        faulted_address = address_of(faulted)

        def single_owners() -> list[list[str]]:
            owners = list(cluster.assignment_map().values())
            assert all(len(shard) <= 1 for shard in owners), "A shard had multiple owners"
            return owners

        yield from cluster.fault_lock(faulted, "hangRelease")
        yield from cluster.wait_until(
            "The faulted runner did not drop its shards",
            fx.sync(lambda: all(faulted_address not in shard for shard in single_owners())),
        )

        [peer] = yield from cluster.start(1)
        peer_address = address_of(peer)
        yield from cluster.wait_until(
            "The peer did not make progress while the forced release was pending",
            fx.sync(lambda: any(peer_address in shard for shard in single_owners())),
        )

        yield from cluster.fault_lock(faulted, "clear")
        previous = [""]
        stable_polls = [0]

        def terminal() -> bool:
            assignments = cluster.assignment_map()
            owners = list(assignments.values())
            assert all(len(shard) <= 1 for shard in owners), "A shard had multiple owners"
            complete = (
                all(len(shard) == 1 for shard in owners)
                and any(faulted_address in shard for shard in owners)
                and any(peer_address in shard for shard in owners)
            )
            encoded = json.dumps(assignments, sort_keys=True) if complete else ""
            stable_polls[0] = stable_polls[0] + 1 if encoded and encoded == previous[0] else 0
            previous[0] = encoded
            return stable_polls[0] >= 3

        yield from cluster.wait_until(
            "The cluster did not reach a terminal assignment after the forced release",
            fx.sync(terminal),
        )

    yield from run(cluster_db, body)


@testing.live(timeout=90)
def test_keeps_peers_progressing_when_a_lock_query_is_permanently_stuck(
    cluster_db: ClusterDatabase,
):
    """keeps peers progressing when a lock query is permanently stuck"""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=fx.layer.empty, config=CONFIG)
        [faulted] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        faulted_address = address_of(faulted)

        yield from cluster.fault_lock(faulted, "stuck")
        yield from cluster.wait_until(
            "The permanently stuck runner did not drop its shards",
            fx.sync(
                lambda: all(
                    faulted_address not in owners for owners in cluster.assignment_map().values()
                )
            ),
        )

        [peer] = yield from cluster.start(1)
        peer_address = address_of(peer)

        def peer_progressed() -> bool:
            owners = list(cluster.assignment_map().values())
            assert all(faulted_address not in shard for shard in owners)
            return any(peer_address in shard for shard in owners)

        yield from cluster.wait_until(
            "The peer did not acquire shards while the other lock query remained stuck",
            fx.sync(peer_progressed),
        )

        yield from cluster.fault_lock(faulted, "clear")
        yield from cluster.wait_for_stable_assignments()

    yield from run(cluster_db, body)


@testing.live(timeout=90)
def test_converges_after_repeated_lock_connection_rebuilds_and_a_hung_release(
    cluster_db: ClusterDatabase,
):
    """converges after repeated lock-connection rebuilds and a hung release"""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=fx.layer.empty, config=CONFIG)
        [faulted] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        faulted_address = address_of(faulted)

        yield from cluster.fault_lock(faulted, "fail")
        healthy_polls = [0]

        @fx.gen
        def kept_shards():
            yield from cluster.fault_lock(faulted, "fail")
            assignments = list(cluster.assignment_map().values())
            assert all(owners == [faulted_address] for owners in assignments), (
                "The runner lost a shard during lock-connection rebuild"
            )
            healthy_polls[0] += 1
            return healthy_polls[0] >= 10

        yield from cluster.wait_until(
            "The runner lost shards while rebuilding failed lock connections", kept_shards
        )

        yield from cluster.fault_lock(faulted, "hangRelease")
        yield from cluster.wait_until(
            "The runner did not drop its shards while the previous connection release hung",
            fx.sync(
                lambda: all(
                    faulted_address not in owners for owners in cluster.assignment_map().values()
                )
            ),
        )

        [peer] = yield from cluster.start(1)
        peer_address = address_of(peer)
        yield from cluster.wait_until(
            "The peer did not acquire shards during the repeated rebuild",
            fx.sync(
                lambda: any(peer_address in owners for owners in cluster.assignment_map().values())
            ),
        )

        yield from cluster.fault_lock(faulted, "clear")
        yield from cluster.wait_for_stable_assignments()

    yield from run(cluster_db, body)
