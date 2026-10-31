"""``singleton.make`` registers its effect with ``Sharding``;
``SingletonAddress`` is equal by name and shard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.cluster import singleton
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.singleton_address import SingletonAddress
from pyfect.effect import Effect


@dataclass
class _Sharding:
    registered: list[tuple[str, Effect[None, Any, Any], str | None]] = field(
        default_factory=list[tuple[str, Effect[None, Any, Any], str | None]]
    )

    def register_singleton(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None
    ) -> Effect[None]:
        return fx.sync(lambda: self.registered.append((name, run, shard_group)))


@testing.effect
def test_registers_the_singleton_with_sharding():
    sharding = _Sharding()
    run: Effect[None] = fx.void
    layers = singleton.make("leader", run).pipe(
        fx.layer.provide_merge(singleton.make("cron", run, shard_group="jobs"))
    )
    yield from fx.void.pipe(fx.provide(layers)).pipe(
        fx.provide_service(Sharding, cast("ShardingService", sharding))
    )
    assert sorted((name, group) for name, _, group in sharding.registered) == [
        ("cron", "jobs"),
        ("leader", None),
    ]
    assert all(registered is run for _, registered, _ in sharding.registered)


def test_singleton_address_is_equal_by_name_and_shard():
    shard = ShardId(group="default", id=1)
    assert SingletonAddress(shard_id=shard, name="a") == SingletonAddress(shard_id=shard, name="a")
    assert SingletonAddress(shard_id=shard, name="a") != SingletonAddress(shard_id=shard, name="b")
    other = ShardId(group="default", id=2)
    assert SingletonAddress(shard_id=shard, name="a") != SingletonAddress(shard_id=other, name="a")
    assert hash(SingletonAddress(shard_id=shard, name="a")) == hash(
        SingletonAddress(shard_id=shard, name="a")
    )
