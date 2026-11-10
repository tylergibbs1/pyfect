"""Ports of platform-node's ``cluster/ShardFence.integration.test.ts``: a
runner whose shard lock was lost while its process was paused must not store
the reply of a request it was still running, on the throwaway PostgreSQL
server (``_postgres.pg_server``; skips without one). Each test's docstring is
the Effect test title.

Effect gives each case its own database; here each one uses its own table
prefix, which also namespaces its advisory locks, so only this test's lock
sessions are terminated."""

from __future__ import annotations

import itertools
import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect import schema as S
from pyfect.clock import Clock, LiveClock
from pyfect.cluster import runner_health, runners, sharding, sharding_config
from pyfect.cluster import sql_message_storage as SqlMessageStorage
from pyfect.cluster import sql_runner_storage as SqlRunnerStorage
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import CurrentRunnerAddress, Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Duration, millis
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc
from pyfect.sql.client import SqlClient, SqlClientService

_prefixes = itertools.count()


class Hold(Entity, type="Hold"):
    hold = make_rpc("Hold", success=S.String).annotate(Persisted, True)


@dataclass(eq=False)
class _Probe:
    port: int
    entered: Deferred[Snowflake, Never] = field(default_factory=Deferred[Snowflake, Never])
    gate: Latch = field(default_factory=Latch)
    returned: Deferred[None, Never] = field(default_factory=Deferred[None, Never])


def _hold_layer(probe: _Probe) -> Layer[Never, Never, Any]:
    @fx.gen
    def build():
        address = yield from CurrentRunnerAddress()

        @fx.fn
        def hold(request: Request[None]):
            yield from probe.entered.succeed(request.request_id)
            yield from probe.gate.wait()
            yield from probe.returned.succeed(None)
            return str(address.port)

        return Hold.handlers().handle(Hold.hold)(hold)

    return Hold.to_layer_effect(build)


class _FreezableClock:
    """A clock whose timers stop firing while frozen, as in a paused
    process: the runner's lock refreshes, heartbeats and storage polls
    stall, while work that does not wait on a timer, such as a running
    handler, carries on."""

    def __init__(self) -> None:
        self._live = LiveClock()
        self.thawed = Latch(True)

    def current_time_millis_unsafe(self) -> float:
        return self._live.current_time_millis_unsafe()

    def monotonic_unsafe(self) -> float:
        return self._live.monotonic_unsafe()

    def now_nanos_unsafe(self) -> int:
        return self._live.now_nanos_unsafe()

    def monotonic_nanos_unsafe(self) -> int:
        return self._live.monotonic_nanos_unsafe()

    def sleep(self, duration: Duration) -> fx.Effect[None]:
        return self._live.sleep(duration).and_then(self.thawed.wait())


def _runner_layer(probe: _Probe, prefix: str, advisory: bool) -> Layer[Any, Never, SqlClient]:
    config = replace(
        sharding_config.DEFAULTS,
        shard_lock_disable_advisory=not advisory,
        runner_address=RunnerAddress(host="localhost", port=probe.port),
        shards_per_group=1,
        # Short enough for B to take over quickly, with lock operation
        # deadlines that tolerate CI latency.
        shard_lock_expiration=millis(3000),
        shard_lock_refresh_interval=millis(1000),
        entity_message_poll_interval=millis(100),
        refresh_assignments_interval=millis(100),
        entity_termination_timeout=millis(0),
    )
    return (
        _hold_layer(probe)
        .pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(
            fx.layer.provide(
                fx.layer.merge(
                    SqlRunnerStorage.layer_with(prefix=prefix),
                    runner_health.layer_noop,
                    runners.layer_noop,
                )
            )
        )
        .pipe(fx.layer.provide_merge(SqlMessageStorage.layer_with(prefix=prefix)))
        .pipe(fx.layer.provide(sharding_config.layer(config)))
    )


def _wait_for[A](check: Callable[[], fx.Effect[A | None, Any, Any]]) -> fx.Effect[A, Any, Any]:
    @fx.gen
    def run():
        while True:
            value = yield from check()
            if value is not None:
                return value
            yield from fx.sleep("20 millis")

    return run


def _within[A](
    effect: fx.Effect[A, Any, Any], seconds: float, failure: str
) -> fx.Effect[A, Any, Any]:
    def timed_out(found: Any) -> fx.Effect[A]:
        return fx.die(AssertionError(failure)) if found is None else fx.succeed(found.value)

    return effect.timeout_option(fx.duration.seconds(seconds)).flat_map(timed_out)


def _pg_client(pg_server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import pg

    return pg.make(pg.PgPoolConfig(url=pg_server.url)).pipe(fx.provide(reactivity.layer))


def _stale_owner_test(pg_server: Any, *, advisory: bool) -> fx.Effect[None, Any, Any]:
    prefix = f"fence_{os.getpid()}_{next(_prefixes)}"

    @fx.gen
    def body():
        sql = yield from _pg_client(pg_server)
        pause_a = _FreezableClock()
        probe_a = _Probe(1234)
        probe_b = _Probe(5678)

        context_a: Context[Any] = yield from (
            _runner_layer(probe_a, prefix, advisory)
            .build()
            .pipe(fx.provide_service(SqlClient, sql))
            .pipe(fx.provide_service(Clock, pause_a))
        )
        storage = context_a.get_unsafe(MessageStorage)
        make_client = yield from Hold.client().pipe(fx.provide(context_a))
        yield from make_client("1").hold.discard()
        request_id = yield from _within(
            probe_a.entered.wait(), 10, "runner A never started the request"
        )

        # A is paused, and its lock session is lost.
        pause_a.thawed.close_unsafe()
        if advisory:
            namespace = SqlRunnerStorage.postgres_lock_namespace(prefix) & 0xFFFFFFFF
            yield from sql.unsafe(
                "SELECT pg_terminate_backend(pid, 10000) FROM pg_locks "
                "WHERE locktype = 'advisory' AND objsubid = 2 "
                f"AND classid = {namespace} "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            )

        context_b: Context[Any] = yield from (
            _runner_layer(probe_b, prefix, advisory)
            .build()
            .pipe(fx.provide_service(SqlClient, sql))
        )
        sharding_b = context_b.get_unsafe(sharding.Sharding)
        shard_id = sharding_b.get_shard_id(EntityId("1"), "default")
        yield from _within(
            _wait_for(lambda: fx.sync(lambda: sharding_b.has_shard_id(shard_id) or None)),
            15,
            "runner B never acquired the shard",
        )
        yield from _within(probe_b.entered.wait(), 15, "runner B never started the request")

        # A's handler finishes before A's lock refresh has run again.
        yield from probe_a.gate.open()
        yield from probe_a.returned.wait()

        def stored_exit() -> fx.Effect[dict[str, Any] | None, Any]:
            return storage.replies_for_unfiltered([request_id]).map(
                lambda replies: next((r for r in replies if r["_tag"] == "WithExit"), None)
            )

        # An unfenced write lands within milliseconds of the handler returning.
        stale = yield from _wait_for(stored_exit).timeout_option("2 seconds")
        assert stale is None, "the stale owner stored its reply"

        yield from probe_b.gate.open()
        reply = yield from _within(_wait_for(stored_exit), 10, "runner B never stored its reply")
        assert reply["exit"] == {"_tag": "Success", "value": "5678"}

        # Resume A so it can shut down. It may legitimately own the shard
        # again from here, so nothing about it is asserted.
        yield from pause_a.thawed.open()

    # Release both runners before the database.
    return fx.scoped(body)


@pytest.fixture
def _psycopg() -> None:
    pytest.importorskip("psycopg")


@pytest.mark.usefixtures("_psycopg")
@testing.live(timeout="60 seconds")
def test_a_runner_that_lost_its_advisory_lock_cannot_store_a_reply(pg_server: Any):
    """a runner that lost its advisory lock cannot store a reply"""
    yield from _stale_owner_test(pg_server, advisory=True)


@pytest.mark.usefixtures("_psycopg")
@testing.live(timeout="60 seconds")
def test_a_runner_that_lost_its_lease_cannot_store_a_reply(pg_server: Any):
    """a runner that lost its lease cannot store a reply"""
    yield from _stale_owner_test(pg_server, advisory=False)
