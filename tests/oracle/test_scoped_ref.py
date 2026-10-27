"""Ports of Effect's ``ScopedRef.test.ts``.

Each test's docstring is the Effect test title. ``Scope.provide(scope)`` is
``provide_service(fx.Scope, scope)`` and ``forkDetach`` is
``fork_daemon``. The ``utils/counter.ts`` helper is ``_Counter``. The last
test checks ``ref.pipe(identity) === ref`` in Effect; pyfect's refs are not
pipeable, so its port reads the value after the owning scope closed.
"""

from typing import Never

import pyfect as fx
from pyfect import testing


class _Counter:
    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self) -> fx.Effect[int, Never, fx.Scope]:
        def count_acquire() -> None:
            self.acquired += 1

        def count_release() -> None:
            self.released += 1

        return (
            fx.sync(count_acquire)
            .and_then(fx.add_finalizer(lambda _: fx.sync(count_release)))
            .and_then(fx.sync(lambda: self.acquired))
            .uninterruptible()
        )


def _logged(log: list[str], n: int) -> fx.Effect[int, Never, fx.Scope]:
    return fx.acquire_release(
        fx.succeed(n), lambda _a, _e: fx.sync(lambda: log.append(f"release {n}"))
    )


@testing.effect
def test_single_set():
    """single set"""
    counter = _Counter()
    ref = yield from fx.ScopedRef.make(lambda: 0)
    yield from ref.set(counter.acquire())
    assert (yield from ref.get()) == 1


@testing.effect
def test_dual_set():
    """dual set"""
    counter = _Counter()
    ref = yield from fx.ScopedRef.make(lambda: 0)
    yield from ref.set(counter.acquire()).and_then(ref.set(counter.acquire()))
    assert (yield from ref.get()) == 2


@testing.effect
def test_releases_the_previous_resource_when_replaced():
    """releases the previous resource when replaced"""
    counter = _Counter()
    ref = yield from fx.ScopedRef.make(lambda: 0)
    yield from ref.set(counter.acquire()).and_then(ref.set(counter.acquire()))
    assert (counter.acquired, counter.released) == (2, 1)


@testing.effect
def test_releases_each_previous_resource_across_multiple_replacements():
    """releases each previous resource across multiple replacements"""
    counter = _Counter()
    ref = yield from fx.ScopedRef.make(lambda: 0)
    yield from (
        ref.set(counter.acquire())
        .and_then(ref.set(counter.acquire()))
        .and_then(ref.set(counter.acquire()))
    )
    assert (counter.acquired, counter.released) == (3, 2)


@testing.effect
def test_releases_the_current_resource_when_the_scoped_ref_scope_closes():
    """releases the current resource when the scoped ref scope closes"""
    counter = _Counter()
    yield from fx.scoped(
        fx.ScopedRef.make(lambda: 0).flat_map(
            lambda ref: (
                ref.set(counter.acquire())
                .and_then(ref.set(counter.acquire()))
                .and_then(ref.set(counter.acquire()))
            )
        )
    )
    assert (counter.acquired, counter.released) == (3, 3)


@testing.effect
def test_owner_finalizers_registered_after_the_ref_still_see_a_live_value_after_set():
    """owner finalizers registered after the ref still see a live value after set"""
    log: list[str] = []
    owner = fx.CloseableScope()
    ref = yield from fx.ScopedRef.from_acquire(_logged(log, 1)).pipe(
        fx.provide_service(fx.Scope, owner)
    )
    yield from owner.add_finalizer(
        lambda _: ref.get().flat_map(lambda n: fx.sync(lambda: log.append(f"use {n}")))
    )
    yield from ref.set(_logged(log, 2))
    yield from owner.close(fx.Success(None))
    assert log == ["release 1", "use 2", "release 2"]


@testing.effect
def test_keeps_the_current_resource_when_replacement_acquisition_fails():
    """keeps the current resource when replacement acquisition fails"""
    released = False

    def release() -> None:
        nonlocal released
        released = True

    ref = yield from fx.ScopedRef.from_acquire(
        fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.sync(release))
    )

    yield from ref.set(fx.fail("boom")).catch_all(lambda _: fx.void)

    assert not released, "failed replacement must not release the current resource"
    assert (yield from ref.get()) == 1


@testing.effect
def test_releases_a_replacement_when_the_old_finalizer_defects():
    """releases a replacement when the old finalizer defects"""
    old_released = yield from fx.Ref.make(0)
    replacement_acquired = yield from fx.Ref.make(0)
    replacement_released = yield from fx.Ref.make(0)
    owner_scope = fx.CloseableScope()
    defect = Exception("old-release-defect")
    ref = yield from fx.ScopedRef.from_acquire(
        fx.acquire_release(
            fx.succeed(0),
            lambda _a, _e: old_released.update(lambda n: n + 1).and_then(fx.die(defect)),
        )
    ).pipe(fx.provide_service(fx.Scope, owner_scope))

    set_exit = yield from ref.set(
        fx.acquire_release(
            replacement_acquired.update_and_get(lambda n: n + 1),
            lambda _a, _e: replacement_released.update(lambda n: n + 1),
        )
    ).exit()
    assert (yield from ref.get()) == 0
    owner_close_exit = yield from owner_scope.close(fx.Success(None)).exit()

    assert set_exit == fx.exit.die(defect)
    assert owner_close_exit == fx.Success(None)
    assert (yield from old_released.get()) == 1
    assert (yield from replacement_acquired.get()) == 1
    assert (yield from replacement_released.get()) == 1


@testing.effect
def test_a_set_in_flight_when_the_owning_scope_closes_releases_its_value():
    """a set in flight when the owning scope closes releases its value"""
    released: list[int] = []
    owner = fx.CloseableScope()
    ref = yield from fx.ScopedRef.make(lambda: 0).pipe(fx.provide_service(fx.Scope, owner))
    gate = yield from fx.Latch.make(False)
    setter = yield from ref.set(
        fx.acquire_release(gate.wait().as_(1), lambda n, _: fx.sync(lambda: released.append(n)))
    ).fork_daemon(start_immediately=True)
    yield from owner.close(fx.Success(None))
    yield from gate.open()
    yield from setter.await_exit()
    assert released == [1]


@testing.effect
def test_from_acquire_tracks_the_initial_resource_through_replacement_and_scope_close():
    """fromAcquire tracks the initial resource through replacement and scope close"""
    ref = yield from fx.scoped(fx.ScopedRef.make(lambda: 0))
    assert (yield from ref.get()) == 0
