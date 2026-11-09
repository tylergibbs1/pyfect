"""``entity_resource``: a resource acquired once per entity, kept across
gets, released by ``close`` (not by the entity shutting down), and keeping
its entity alive while held."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.cluster import entity_resource, snowflake
from pyfect.cluster.entity import CurrentAddress, KeepAliveLatch
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import Effect
from pyfect.latch import Latch
from pyfect.scope import scoped

_ADDRESS = EntityAddress(
    shard_id=ShardId(group="default", id=1),
    entity_type=EntityType("Resourceful"),
    entity_id=EntityId("1"),
)


@dataclass
class _Sharding:
    generator: snowflake.SnowflakeGenerator
    outgoing: list[OutgoingRequest] = field(default_factory=list[OutgoingRequest])

    @property
    def get_snowflake(self) -> Effect[Snowflake]:
        return fx.sync(self.generator.next_unsafe)

    def send_outgoing(self, message: OutgoingRequest, discard: bool) -> Effect[None]:
        return fx.sync(lambda: self.outgoing.append(message))


@dataclass
class _Counter:
    acquired: int = 0
    released: int = 0

    @property
    def acquire(self) -> Effect[int, Any, entity_resource.CloseScope]:
        @fx.gen
        def run():
            scope = yield from entity_resource.CloseScope()

            def release(_: Any) -> Effect[None]:
                return fx.sync(lambda: setattr(self, "released", self.released + 1))

            yield from scope.add_finalizer(release)
            self.acquired += 1
            return self.acquired

        return run


def _provide[A, E](
    effect: Effect[A, E, Any], sharding: _Sharding, latch: Latch | None = None
) -> Effect[A, E]:
    provided = effect.pipe(fx.provide_service(CurrentAddress, _ADDRESS)).pipe(
        fx.provide_service(Sharding, cast("ShardingService", sharding))
    )
    if latch is None:
        return provided
    return provided.pipe(fx.provide_service(KeepAliveLatch, latch))


def _sharding():
    return snowflake.make_generator().map(_Sharding)


@testing.effect
def test_acquires_once_until_closed():
    counter = _Counter()
    sharding = yield from _sharding()

    @fx.gen
    def body():
        resource = yield from entity_resource.make(counter.acquire)
        assert counter.acquired == 0, "acquired on first get"
        assert (yield from scoped(resource.get)) == 1
        assert (yield from scoped(resource.get)) == 1
        assert counter.released == 0, "held without an idle time to live"
        yield from resource.close
        assert counter.released == 1
        assert (yield from scoped(resource.get)) == 2

    yield from _provide(scoped(body), sharding)


@testing.effect
def test_acquires_eagerly_and_survives_the_entity_shutting_down():
    counter = _Counter()
    sharding = yield from _sharding()

    @fx.gen
    def body():
        yield from entity_resource.make(counter.acquire, acquire_eagerly=True)
        assert counter.acquired == 1

    yield from _provide(scoped(body), sharding)
    assert counter.released == 0, "an entity shutting down keeps the resource"


@testing.effect
def test_releases_after_its_idle_time_to_live():
    counter = _Counter()
    sharding = yield from _sharding()

    @fx.gen
    def body():
        resource = yield from entity_resource.make(counter.acquire, idle_time_to_live="1 minute")
        yield from scoped(resource.get)
        yield from testing.adjust("59 seconds")
        assert counter.released == 0
        yield from testing.adjust("1 second")
        assert counter.released == 1

    yield from _provide(scoped(body), sharding)


@testing.effect
def test_keeps_the_entity_alive_while_held():
    counter = _Counter()
    sharding = yield from _sharding()
    latch = Latch(open=True)

    @fx.gen
    def body():
        resource = yield from entity_resource.make(counter.acquire)
        yield from scoped(resource.get)
        assert not latch.is_open()
        [keep_alive] = sharding.outgoing
        assert keep_alive.envelope.address == _ADDRESS
        assert keep_alive.envelope.tag == "Cluster/Entity/keepAlive"
        yield from resource.close
        assert latch.is_open()

    yield from _provide(scoped(body), sharding, latch)


@testing.effect
def test_each_run_of_make_has_its_own_lifetime():
    # One ``make`` effect run by two activations: the first one shutting
    # down must not stop the second from releasing its resource on close.
    counter = _Counter()
    sharding = yield from _sharding()
    make = entity_resource.make(counter.acquire)

    @fx.gen
    def first():
        resource = yield from make
        yield from scoped(resource.get)

    @fx.gen
    def second():
        resource = yield from make
        yield from scoped(resource.get)
        yield from resource.close
        assert counter.released == 1, "close releases the second activation's resource"

    yield from _provide(scoped(first), sharding)
    yield from _provide(scoped(second), sharding)
