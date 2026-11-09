"""pyfect-only checks of the cluster harness (``_cluster_harness``) itself:
what a test built on it can rely on."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect.latch import Latch

from ._cluster_harness import ClusterDatabase, make
from .test_cluster_integration_entity import (
    EntityRequest,
    StateEntity,
    address_string,
    standard_entities,
)

type Body = Generator[fx.Effect[Any, Any, Any], Any]


class Boom(Exception):
    pass


@testing.live(timeout="30 seconds")
def test_a_test_failing_while_a_runner_is_frozen_reports_its_failure(
    cluster_db: ClusterDatabase,
):
    """A frozen runner waits uninterruptibly for its storage: the cluster's
    teardown releases it, so a failing test fails with its own error
    instead of hanging in the runner's finalizers."""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=standard_entities, lock_mode="row")
        [runner] = yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.freeze(runner)
        yield from cluster.freeze_client()
        return (yield from fx.fail(Boom()))

    exit = yield from fx.scoped(fx.gen(body)).exit()
    assert isinstance(exit, Exit.Failure)
    assert isinstance(exit.cause.squash(), Boom)


@testing.live(timeout="1 minute")
def test_the_client_routes_by_the_runners_of_its_last_sync(cluster_db: ClusterDatabase):
    """A runner sees a shard move before the client does: the client
    routes by the runners it last read, so a test that sends right after
    a move waits for ``wait_for_client_sync`` first."""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=standard_entities, lock_mode="row")
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_for_client_sync()
        id = f"client-view-{backend}"
        old_owner = yield from cluster.owner_of_entity(StateEntity, id)
        assert old_owner is not None
        yield from cluster.freeze_client()
        yield from cluster.freeze(old_owner)
        yield from cluster.wait_until(
            "The frozen runner's row lock did not expire",
            cluster.owner_of_entity(StateEntity, id).map(
                lambda owner: owner is not None and owner is not old_owner
            ),
            12,
        )
        # The runners moved the shard; the client still routes to the
        # frozen runner.
        assert not cluster.client_in_sync()
        yield from cluster.resume_client()
        yield from cluster.wait_for_client_sync()
        client = yield from cluster.get_client(StateEntity)
        sequence = [0]

        def replies_from_its_owner() -> Generator[fx.Effect[Any, Any, Any], Any, bool]:
            # Under load a lock operation can pass its 500 ms and a healthy runner gives its
            # shards up, as in Effect, so the owner may move during the call: ask again then.
            owner = yield from cluster.owner_of_entity(StateEntity, id)
            if owner is None:
                return False
            sequence[0] += 1
            reply = yield from client(id).increment(
                EntityRequest(id=f"{backend}-view", sequence=sequence[0] - 1)
            )
            if (yield from cluster.owner_of_entity(StateEntity, id)) is not owner:
                return False
            assert reply["runner"] == address_string(owner.address)
            return True

        yield from cluster.wait_until("The owner kept moving", fx.gen(replies_from_its_owner), 12)
        yield from cluster.kill(old_owner)

    yield from fx.scoped(fx.gen(body))


@testing.live(timeout="20 seconds")
def test_wait_until_fails_at_its_deadline_on_a_condition_that_never_returns(
    cluster_db: ClusterDatabase,
):
    """A condition that blocks (``deferred.wait()`` on a request that never
    starts) is bounded by the deadline too: the test fails with the
    description instead of hanging until the test's own timeout."""

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=standard_entities, lock_mode="row")
        clock = yield from fx.clock.Clock()
        never = Latch()
        started = clock.monotonic_unsafe()
        exit = yield from cluster.wait_until(
            "The request did not start", never.wait().as_(True), 0.5
        ).exit()
        elapsed = clock.monotonic_unsafe() - started
        assert isinstance(exit, Exit.Failure)
        error = exit.cause.squash()
        assert isinstance(error, AssertionError)
        assert str(error).startswith("The request did not start")
        assert elapsed < 5

    yield from fx.scoped(fx.gen(body))
