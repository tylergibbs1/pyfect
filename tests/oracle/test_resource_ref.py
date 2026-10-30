"""Ports of Effect's ``test/cluster/ResourceRef.test.ts`` for
``pyfect.cluster._resource_ref``. Each test's docstring is the Effect
test title."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.cluster import entity_address, shard_id
from pyfect.cluster._interruptors import is_active
from pyfect.cluster._resource_ref import ResourceRef
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.deferred import Deferred
from pyfect.exit import Exit, Failure, Success
from pyfect.scope import CloseableScope, Scope

_void: Exit[None, Any] = Success(None)


@dataclass
class _Gate:
    reached: Deferred[None] = field(default_factory=Deferred[None])
    open: Deferred[None] = field(default_factory=Deferred[None])

    def pass_(self) -> fx.Effect[None]:
        return self.reached.succeed(None).flat_map(lambda _: self.open.wait())


@dataclass
class _Acquire:
    """Acquires 1, 2, 3, ...; a gated acquisition (or release) waits at its
    gate."""

    gated: dict[int, _Gate]
    gated_release: dict[int, _Gate]
    acquisitions: int = 0
    completed: int = 0
    releases: int = 0

    def acquire(self, scope: CloseableScope) -> fx.Effect[int]:
        def body() -> Generator[fx.Effect[Any, Any, Any], Any, int]:
            self.acquisitions += 1
            acquisition = self.acquisitions
            release_gate = self.gated_release.get(acquisition)

            def released(_: Exit[Any, Any]) -> fx.Effect[None]:
                wait = fx.void if release_gate is None else release_gate.pass_()
                return wait.flat_map(lambda _: fx.sync(self._released))

            yield from scope.add_finalizer(released)
            gate = self.gated.get(acquisition)
            if gate is not None:
                yield from gate.pass_()
            self.completed += 1
            return acquisition

        return fx.gen(body)

    def _released(self) -> None:
        self.releases += 1


def _make_acquire(gated: tuple[int, ...] = (), gated_release: tuple[int, ...] = ()) -> _Acquire:
    return _Acquire({n: _Gate() for n in gated}, {n: _Gate() for n in gated_release})


def _settle() -> Generator[fx.Effect[Any, Any, Any], Any]:
    for _ in range(10):
        yield from fx.yield_now()


def _interrupted(exit: Exit[Any, Any] | None) -> bool:
    return isinstance(exit, Failure) and exit.cause.has_interrupts


def _address(group: str, entity_type: str):
    return entity_address.make(
        shard_id=shard_id.make(group, 1),
        entity_type=EntityType(entity_type),
        entity_id=EntityId("1"),
    )


@testing.effect
def test_rebuilds_only_the_current_generation():
    """rebuilds only the current generation"""
    parent = CloseableScope()
    acquire = _make_acquire()
    ref = yield from ResourceRef.make(parent, acquire.acquire)
    assert ref.unsafe_get() == 1

    first = ref.unsafe_rebuild(from_=1)
    assert first is not None
    yield from first
    assert ref.unsafe_get() == 2
    assert ref.unsafe_rebuild(from_=1) is None

    rebuild = ref.unsafe_rebuild()
    assert rebuild is not None
    yield from rebuild
    assert ref.unsafe_get() == 3
    assert ref.unsafe_rebuild(from_=2) is None

    yield from parent.close(_void)
    assert ref.unsafe_get() is None
    assert ref.unsafe_rebuild(from_=3) is None
    assert ref.unsafe_rebuild() is None
    assert _interrupted((yield from ref.await_.exit()))


@testing.effect
def test_refuses_second_rebuild_of_a_generation():
    """refuses a second rebuild of a generation without disturbing the accepted one"""
    parent = yield from Scope()
    acquire = _make_acquire(gated=(2,))
    ref = yield from ResourceRef.make(parent, acquire.acquire)

    accepted = ref.unsafe_rebuild(from_=1)
    assert accepted is not None
    assert ref.unsafe_get() is None
    assert ref.unsafe_rebuild(from_=1) is None
    assert ref.unsafe_rebuild() is None

    rebuild = yield from accepted.fork()
    yield from acquire.gated[2].reached.wait()
    assert ref.unsafe_rebuild(from_=1) is None
    assert ref.unsafe_rebuild() is None

    yield from acquire.gated[2].open.succeed(None)
    assert (yield from rebuild.await_exit()) == _void
    assert ref.unsafe_get() == 2
    assert (yield from ref.await_) == 2


@testing.effect
def test_interrupts_prepare_when_generation_replaced():
    """interrupts prepare when its generation is replaced"""
    parent = yield from Scope()
    acquire = _make_acquire()
    ref = yield from ResourceRef.make(parent, acquire.acquire)
    newer: list[fx.Effect[None]] = []
    finished_preparing: list[bool] = []

    def prepare(value: int) -> fx.Effect[None]:
        def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
            replaced = ref.unsafe_rebuild(from_=value)
            assert replaced is not None
            newer.append(replaced)
            yield from fx.yield_now()
            finished_preparing.append(True)

        return fx.gen(body)

    rebuild = ref.unsafe_rebuild(from_=1, prepare=prepare)
    assert rebuild is not None
    superseded = yield from rebuild.fork()
    assert _interrupted((yield from superseded.await_exit()))
    assert finished_preparing == [], "prepare must be interrupted"
    assert len(newer) == 1

    waiter = yield from ref.await_.fork()
    yield from fx.yield_now()
    assert ref.unsafe_get() is None
    assert waiter.unsafe_poll() is None

    yield from newer[0]
    assert (yield from waiter.join()) == 3
    assert ref.unsafe_get() == 3


@testing.effect
def test_closes_replaced_generation_whose_rebuild_never_ran():
    """closes a replaced generation whose rebuild never ran when the ref closes"""
    parent = CloseableScope()
    acquire = _make_acquire()
    ref = yield from ResourceRef.make(parent, acquire.acquire)

    rebuild = ref.unsafe_rebuild(from_=1)
    assert rebuild is not None
    waiter = yield from ref.await_.fork()
    yield from fx.yield_now()

    yield from parent.close(_void)
    assert acquire.releases == 1, "the replaced generation must be closed"
    assert _interrupted((yield from waiter.await_exit()))

    assert _interrupted((yield from rebuild.exit()))
    assert acquire.acquisitions == 1


@testing.effect
def test_no_teardown_leak_when_rebuild_discarded():
    """does not leak teardown membership when a rebuild is discarded"""
    parent = CloseableScope()
    address = _address("resource-ref-discard", "ResourceRefDiscard")
    acquire = _make_acquire()
    ref = yield from ResourceRef.make(parent, acquire.acquire, address)
    assert ref.unsafe_rebuild(from_=1) is not None
    assert not is_active(address)
    yield from parent.close(_void)
    assert not is_active(address)


@testing.effect
def test_no_teardown_leak_when_rebuild_interrupted():
    """does not leak teardown membership when a rebuild is interrupted"""
    parent = yield from Scope()
    address = _address("resource-ref-interrupt", "ResourceRefInterrupt")
    acquire = _make_acquire(gated_release=(1,))
    ref = yield from ResourceRef.make(parent, acquire.acquire, address)
    rebuild = ref.unsafe_rebuild(from_=1)
    assert rebuild is not None
    fiber = yield from rebuild.fork()
    yield from fiber.interrupt()
    yield from acquire.gated_release[1].open.succeed(None)
    assert not is_active(address)


@testing.effect
def test_stays_rebuildable_when_failed_replacement_cannot_be_released():
    """stays rebuildable when a failed replacement cannot be released"""
    parent = yield from Scope()
    acquire = _make_acquire(gated=(2,), gated_release=(2,))
    ref = yield from ResourceRef.make(parent, acquire.acquire)

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        rebuild = ref.unsafe_rebuild(from_=1)
        assert rebuild is not None
        fiber = yield from rebuild.fork()
        yield from acquire.gated[2].reached.wait()
        fiber.unsafe_interrupt_as(None)
        yield from _settle()
        assert ref.unsafe_rebuild() is not None, "a hung release must not block the next rebuild"

    yield from fx.gen(body).ensuring(acquire.gated_release[2].open.succeed(None))


@testing.effect
def test_interrupts_acquiring_rebuild_when_ref_closes():
    """interrupts a rebuild that is acquiring when the ref closes"""
    parent = CloseableScope()
    acquire = _make_acquire(gated=(2,))
    ref = yield from ResourceRef.make(parent, acquire.acquire)

    rebuild = ref.unsafe_rebuild(from_=1)
    assert rebuild is not None
    fiber = yield from rebuild.fork()
    yield from acquire.gated[2].reached.wait()
    waiter = yield from ref.await_.fork()
    yield from parent.close(_void)
    yield from _settle()
    exit = fiber.unsafe_poll()
    assert exit is not None, "closing the ref must interrupt acquisition"
    assert _interrupted(exit)
    assert _interrupted((yield from waiter.await_exit()))

    yield from acquire.gated[2].open.succeed(None)
    yield from _settle()
    assert acquire.completed == 1, "acquisition must not continue after the close"


@testing.effect
def test_rebuild_from_compares_resources_by_identity():
    """(pyfect) rebuildUnsafe's ``from`` is Effect's ``!==``: a rebuild
    from a stale resource equal to the current one is refused"""
    acquired: list[list[int]] = []

    def acquire(_scope: CloseableScope) -> fx.Effect[list[int]]:
        def make() -> list[int]:
            acquired.append([])
            return acquired[-1]

        return fx.sync(make)

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        parent = yield from Scope()
        assert isinstance(parent, CloseableScope)
        ref = yield from ResourceRef.make(parent, acquire)
        stale = yield from ref.await_
        rebuild = ref.unsafe_rebuild(from_=stale)
        assert rebuild is not None
        yield from rebuild
        current = yield from ref.await_
        assert current is not stale and current == stale
        assert ref.unsafe_rebuild(from_=stale) is None
        assert len(acquired) == 2

    yield from fx.scoped(fx.gen(body))
