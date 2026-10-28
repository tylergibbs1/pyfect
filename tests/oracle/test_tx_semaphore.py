"""Ports of Effect's ``TxSemaphore.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxSemaphore.acquireN(s, 3)`` is ``s.acquire_n(3)``,
``withPermits(s, 3, eff)`` is ``s.with_permits(eff, 3)``); ``capacity`` is a
property; ``isTxSemaphore`` is ``isinstance``.
"""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing

from ._tx import in_tx

# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_make_creates_semaphore_with_specified_permits():
    """make creates semaphore with specified permits"""
    semaphore = yield from fx.TxSemaphore.make(5)
    assert (yield from semaphore.available()) == 5
    assert semaphore.capacity == 5


@testing.effect
@in_tx
def test_make_with_zero_permits_creates_empty_semaphore():
    """make with zero permits creates empty semaphore"""
    semaphore = yield from fx.TxSemaphore.make(0)
    assert (yield from semaphore.available()) == 0
    assert semaphore.capacity == 0


@testing.effect
@in_tx
def test_make_with_negative_permits_causes_defect():
    """make with negative permits causes defect"""
    ex = yield from fx.TxSemaphore.make(-1).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


# --- basic operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_acquire_and_release_work_correctly():
    """acquire and release work correctly"""
    semaphore = yield from fx.TxSemaphore.make(3)
    yield from semaphore.acquire()
    assert (yield from semaphore.available()) == 2
    yield from semaphore.release()
    assert (yield from semaphore.available()) == 3


@testing.effect
@in_tx
def test_acquire_n_and_release_n_work_correctly():
    """acquireN and releaseN work correctly"""
    semaphore = yield from fx.TxSemaphore.make(5)
    yield from semaphore.acquire_n(3)
    assert (yield from semaphore.available()) == 2
    yield from semaphore.release_n(2)
    assert (yield from semaphore.available()) == 4


@testing.effect
@in_tx
def test_try_acquire_succeeds_when_permits_available():
    """tryAcquire succeeds when permits available"""
    semaphore = yield from fx.TxSemaphore.make(2)
    assert (yield from semaphore.try_acquire()) is True
    assert (yield from semaphore.available()) == 1


@testing.effect
@in_tx
def test_try_acquire_fails_when_no_permits_available():
    """tryAcquire fails when no permits available"""
    semaphore = yield from fx.TxSemaphore.make(1)
    yield from semaphore.acquire()
    assert (yield from semaphore.try_acquire()) is False
    assert (yield from semaphore.available()) == 0


@testing.effect
@in_tx
def test_try_acquire_n_succeeds_when_enough_permits_available():
    """tryAcquireN succeeds when enough permits available"""
    semaphore = yield from fx.TxSemaphore.make(5)
    assert (yield from semaphore.try_acquire_n(3)) is True
    assert (yield from semaphore.available()) == 2


@testing.effect
@in_tx
def test_try_acquire_n_fails_when_not_enough_permits_available():
    """tryAcquireN fails when not enough permits available"""
    semaphore = yield from fx.TxSemaphore.make(2)
    assert (yield from semaphore.try_acquire_n(3)) is False
    assert (yield from semaphore.available()) == 2


# --- scoped operations --------------------------------------------------------


@testing.effect
def test_with_permit_automatically_manages_permit_lifecycle():
    """withPermit automatically manages permit lifecycle"""
    semaphore = yield from fx.tx(fx.TxSemaphore.make(2))

    @fx.fn
    def body():
        assert (yield from fx.tx(semaphore.available())) == 1
        return "success"

    assert (yield from semaphore.with_permit(body())) == "success"
    assert (yield from fx.tx(semaphore.available())) == 2


@testing.effect
def test_with_permits_automatically_manages_multiple_permits():
    """withPermits automatically manages multiple permits"""
    semaphore = yield from fx.tx(fx.TxSemaphore.make(5))

    @fx.fn
    def body():
        assert (yield from fx.tx(semaphore.available())) == 2
        return ["result1", "result2", "result3"]

    result = yield from semaphore.with_permits(body(), 3)
    assert result == ["result1", "result2", "result3"]
    assert (yield from fx.tx(semaphore.available())) == 5


@testing.effect
def test_with_permit_scoped_works_within_scoped_context():
    """withPermitScoped works within scoped context"""
    semaphore = yield from fx.tx(fx.TxSemaphore.make(3))

    @fx.fn
    def body():
        yield from semaphore.with_permit_scoped()
        assert (yield from fx.tx(semaphore.available())) == 2

    yield from fx.scoped(body())
    assert (yield from fx.tx(semaphore.available())) == 3


# --- edge cases ---------------------------------------------------------------


@testing.effect
@in_tx
def test_acquire_n_with_zero_permits_causes_defect():
    """acquireN with zero permits causes defect"""
    semaphore = yield from fx.TxSemaphore.make(5)
    ex = yield from semaphore.acquire_n(0).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


@testing.effect
@in_tx
def test_acquire_n_with_negative_permits_causes_defect():
    """acquireN with negative permits causes defect"""
    semaphore = yield from fx.TxSemaphore.make(5)
    ex = yield from semaphore.acquire_n(-1).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


@testing.effect
@in_tx
def test_release_n_with_zero_permits_causes_defect():
    """releaseN with zero permits causes defect"""
    semaphore = yield from fx.TxSemaphore.make(5)
    ex = yield from semaphore.release_n(0).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


@testing.effect
@in_tx
def test_release_n_with_negative_permits_causes_defect():
    """releaseN with negative permits causes defect"""
    semaphore = yield from fx.TxSemaphore.make(5)
    ex = yield from semaphore.release_n(-1).exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_dies


@testing.effect
@in_tx
def test_release_does_not_exceed_capacity():
    """release does not exceed capacity"""
    semaphore = yield from fx.TxSemaphore.make(3)
    yield from semaphore.release()
    yield from semaphore.release()
    assert (yield from semaphore.available()) == 3


@testing.effect
@in_tx
def test_release_n_does_not_exceed_capacity():
    """releaseN does not exceed capacity"""
    semaphore = yield from fx.TxSemaphore.make(5)
    yield from semaphore.release_n(10)
    assert (yield from semaphore.available()) == 5


# --- type guards --------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_semaphore_correctly_identifies_tx_semaphore_instances():
    """isTxSemaphore correctly identifies TxSemaphore instances"""
    semaphore = yield from fx.TxSemaphore.make(5)
    assert isinstance(semaphore, fx.TxSemaphore)
    for other in ({"some": "object"}, None, [5]):
        assert not isinstance(other, fx.TxSemaphore)


# --- concurrency --------------------------------------------------------------

_ACQUISITIONS: list[tuple[str, Callable[[fx.TxSemaphore], fx.Effect[Any]]]] = [
    ("withPermits", lambda semaphore: semaphore.with_permits(fx.void, 2)),
    ("withPermitScoped", lambda semaphore: fx.scoped(semaphore.with_permit_scoped())),
]


@pytest.mark.parametrize(("name", "acquire"), _ACQUISITIONS, ids=[a[0] for a in _ACQUISITIONS])
@testing.effect
def test_can_be_interrupted_while_waiting_for_permits(
    name: str, acquire: Callable[[fx.TxSemaphore], fx.Effect[Any]]
):
    """{name} can be interrupted while waiting for permits"""
    semaphore = yield from fx.TxSemaphore.make(2)
    yield from semaphore.acquire_n(2)

    waiter = yield from acquire(semaphore).fork(start_immediately=True)
    interruptor = yield from waiter.interrupt().fork(start_immediately=True)
    yield from fx.yield_now()
    yield from fx.yield_now()

    interrupted = interruptor.unsafe_poll() is not None
    available = yield from semaphore.available()
    yield from semaphore.release_n(2)
    yield from interruptor.join()

    assert interrupted, "interruption must complete before the holder releases"
    assert available == 0
    ex = yield from waiter.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert (yield from semaphore.available()) == 2


@testing.effect
def test_with_permit_bounds_concurrent_work_and_releases_for_the_next_waiter():
    """withPermit bounds concurrent work and releases for the next waiter"""
    semaphore = yield from fx.tx(fx.TxSemaphore.make(3))
    fiber1 = yield from semaphore.with_permit(fx.succeed(1)).fork()
    fiber2 = yield from semaphore.with_permit(fx.succeed(2)).fork()
    fiber3 = yield from semaphore.with_permit(fx.succeed(3)).fork()
    assert (yield from fx.Fiber.join_all([fiber1, fiber2, fiber3])) == [1, 2, 3]
    assert (yield from fx.tx(semaphore.available())) == 3


# --- transactional behavior ---------------------------------------------------


@testing.effect
@in_tx
def test_operations_are_atomic_within_transactions():
    """operations are atomic within transactions"""
    semaphore = yield from fx.TxSemaphore.make(5)
    yield from semaphore.acquire()
    yield from semaphore.acquire()
    yield from semaphore.release()
    assert (yield from semaphore.available()) == 4
