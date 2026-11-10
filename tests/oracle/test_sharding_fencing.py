"""Ports of the "Sharding shard fencing" cases of Effect's
``test/cluster/Sharding.test.ts``: a persisted request's final reply is
stored only once a lock refresh of its shard confirms this runner still
holds it. Each test's docstring is the Effect test title."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect._fiber import Fiber
from pyfect.cluster import message_storage, runner_health, runner_storage, runners, sharding
from pyfect.cluster.cluster_schema import Dynamic, Persisted, WithTransaction
from pyfect.cluster.entity import Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MemoryDriver, MemoryDriverService
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.shard_id import ShardId
from pyfect.context import Context
from pyfect.latch import Latch
from pyfect.queue import Queue
from pyfect.rpc import make as make_rpc

from ._sharding_fixtures import test_config


def _with_transaction(annotations: Context[Any], _request: Any) -> Context[Any]:
    return annotations.add(WithTransaction, True)


class FencedEntity(Entity, type="FencedEntity"):
    request = make_rpc("Request", success=S.Int).annotate(Persisted, True)
    transaction = (
        make_rpc("Transaction", success=S.Int)
        .annotate(Persisted, True)
        .annotate(Dynamic, _with_transaction)
    )


@dataclass(eq=False)
class _Probe:
    """Each handler produces its result only after ``release`` opens."""

    entered: Queue[str]
    release: Latch = field(default_factory=Latch)


@dataclass(eq=False)
class _ShardFence:
    fenced: bool = False
    """Once set, lock refreshes no longer return any shard, while the
    runner's periodic lock refresh is not due yet."""
    refreshes: list[list[ShardId]] = field(default_factory=list[list[ShardId]])
    """The shards of each lock refresh made while fenced."""


@dataclass(frozen=True)
class _Fenced:
    client: Any
    driver: MemoryDriverService
    fence: _ShardFence
    probe: _Probe
    service: sharding.ShardingService


def _handler(probe: _Probe, tag: str) -> Callable[[Request[None]], fx.Effect[int]]:
    return lambda _: probe.entered.offer(tag).and_then(probe.release.wait().as_(1))


def _with_fenced_entity(body: Callable[[_Fenced], fx.Effect[None, Any, Any]]) -> fx.Effect[None]:
    restarts: list[object] = []

    def log(options: Any) -> None:
        message = options.message
        if isinstance(message, (list, tuple)) and "Defect in entity, restarting" in message:
            restarts.append(options.message)

    fence = _ShardFence()

    def fenced_storage(storage: runner_storage.RunnerStorageService) -> Any:
        def refresh(
            address: RunnerAddress, shard_ids: Iterable[ShardId]
        ) -> fx.Effect[list[ShardId], Any]:
            shards = list(shard_ids)
            if not fence.fenced:
                return storage.refresh(address, shards)
            if shards:
                fence.refreshes.append(shards)
            return fx.succeed([])

        return replace(storage, refresh=refresh)

    storage_layer = fx.layer.effect(RunnerStorage, runner_storage.make_memory().map(fenced_storage))

    @fx.gen
    def run():
        probe = _Probe(entered=(yield from Queue[str].unbounded()))
        e = FencedEntity
        layer = (
            e.to_layer(
                e.handlers()
                .handle(e.request)(_handler(probe, "Request"))
                .handle(e.transaction)(_handler(probe, "Transaction"))
            )
            .pipe(fx.layer.provide_merge(sharding.layer))
            .pipe(fx.layer.provide(storage_layer))
            .pipe(fx.layer.provide(runner_health.layer_noop))
            .pipe(fx.layer.provide(runners.layer_noop))
            .pipe(fx.layer.provide_merge(message_storage.layer_memory))
            .pipe(fx.layer.provide(test_config))
        )

        @fx.gen
        def inner():
            driver = yield from MemoryDriver()
            make_client = yield from e.client()
            yield from testing.adjust("1 millis")
            service = yield from sharding.Sharding()
            yield from body(_Fenced(make_client("1"), driver, fence, probe, service))
            assert restarts == []

        yield from inner.pipe(fx.provide(layer))

    return run.with_logger(fx.Logger.make(log))


@testing.effect
def test_abandons_a_reply_once_lock_storage_no_longer_attributes_the_shard_to_this_runner():
    """abandons a reply once lock storage no longer attributes the shard to this runner"""

    @fx.fn
    def body(fenced: _Fenced):
        fork: fx.Effect[Fiber[int, Any]] = fenced.client.request().fork(start_immediately=True)
        result = yield from fork
        yield from testing.adjust("1 millis")
        assert (yield from fenced.probe.entered.take()) == "Request"

        fenced.fence.fenced = True
        yield from fenced.probe.release.open()
        # Past every retry of a failed reply write.
        yield from testing.adjust("1 second")

        assert len(fenced.driver.encoded.reply_ids) == 0
        # A rejected write is never retried: one lock refresh per handler run,
        # of the reply's shard only.
        refreshes = fenced.fence.refreshes
        assert len(refreshes) == 1 + fenced.probe.entered.size_unsafe()
        shard_id = fenced.service.get_shard_id(EntityId("1"), "default")
        assert refreshes == [[shard_id] for _ in refreshes]
        # The caller is not answered with this runner's result.
        assert result.poll_unsafe() is None

    yield from _with_fenced_entity(body)


@testing.effect
def test_abandons_a_fenced_transactional_reply_without_restarting_the_entity():
    """abandons a fenced transactional reply without restarting the entity"""

    @fx.fn
    def body(fenced: _Fenced):
        fork: fx.Effect[Fiber[int, Any]] = fenced.client.transaction().fork(start_immediately=True)
        result = yield from fork
        yield from testing.adjust("1 millis")
        assert (yield from fenced.probe.entered.take()) == "Transaction"

        fenced.fence.fenced = True
        yield from fenced.probe.release.open()
        yield from testing.adjust("1 second")

        assert len(fenced.driver.encoded.reply_ids) == 0
        assert len(fenced.fence.refreshes) == 1 + fenced.probe.entered.size_unsafe()
        assert result.poll_unsafe() is None

    yield from _with_fenced_entity(body)
