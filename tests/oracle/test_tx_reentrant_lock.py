"""Ports of Effect's ``TxReentrantLock.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxReentrantLock.acquireRead(lock)`` is ``lock.acquire_read()``), so the
two data-last ``pipe`` titles call the method; ``isTxReentrantLock`` is
``isinstance``.
"""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing

from ._tx import in_tx

# --- interruption while waiting -----------------------------------------------

_ACQUISITIONS: list[tuple[str, Callable[[fx.TxReentrantLock], fx.Effect[Any]]]] = [
    ("withWriteLock", lambda lock: lock.with_write_lock(fx.void)),
    ("writeLock", lambda lock: fx.scoped(lock.write_lock())),
]


@pytest.mark.parametrize(("name", "acquire"), _ACQUISITIONS, ids=[a[0] for a in _ACQUISITIONS])
@testing.effect
def test_can_be_interrupted_while_another_fiber_holds_the_write_lock(
    name: str, acquire: Callable[[fx.TxReentrantLock], fx.Effect[Any]]
):
    """{name} can be interrupted while another fiber holds the write lock"""
    lock = yield from fx.TxReentrantLock.make()
    yield from lock.acquire_write()

    waiter = yield from acquire(lock).fork(start_immediately=True)
    interruptor = yield from waiter.interrupt().fork(start_immediately=True)
    yield from fx.yield_now()
    yield from fx.yield_now()

    interrupted = interruptor.unsafe_poll() is not None
    write_locks = yield from lock.write_locks()
    yield from lock.release_write()
    yield from interruptor.join()

    assert interrupted, "interruption must complete before the holder releases"
    assert write_locks == 1
    ex = yield from waiter.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert (yield from lock.read_locks()) == 0
    assert (yield from lock.write_locks()) == 0


# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_make_creates_an_unlocked_lock():
    """make creates an unlocked lock"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.locked()) is False
    assert (yield from lock.read_locked()) is False
    assert (yield from lock.write_locked()) is False
    assert (yield from lock.read_locks()) == 0
    assert (yield from lock.write_locks()) == 0


# --- read lock ----------------------------------------------------------------


@testing.effect
@in_tx
def test_acquire_read_and_release_read_work_correctly():
    """acquireRead and releaseRead work correctly"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.acquire_read()) == 1
    assert (yield from lock.read_locked()) is True
    assert (yield from lock.read_locks()) == 1
    assert (yield from lock.release_read()) == 0
    assert (yield from lock.read_locked()) is False


@testing.effect
@in_tx
def test_multiple_read_acquires_from_same_fiber_are_reentrant():
    """multiple read acquires from same fiber are reentrant"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.acquire_read()) == 1
    assert (yield from lock.acquire_read()) == 2
    assert (yield from lock.read_locks()) == 2
    yield from lock.release_read()
    assert (yield from lock.read_locks()) == 1
    yield from lock.release_read()
    assert (yield from lock.read_locks()) == 0


# --- write lock ---------------------------------------------------------------


@testing.effect
@in_tx
def test_acquire_write_and_release_write_work_correctly():
    """acquireWrite and releaseWrite work correctly"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.acquire_write()) == 1
    assert (yield from lock.write_locked()) is True
    assert (yield from lock.write_locks()) == 1
    assert (yield from lock.release_write()) == 0
    assert (yield from lock.write_locked()) is False


@testing.effect
@in_tx
def test_multiple_write_acquires_from_same_fiber_are_reentrant():
    """multiple write acquires from same fiber are reentrant"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.acquire_write()) == 1
    assert (yield from lock.acquire_write()) == 2
    assert (yield from lock.write_locks()) == 2
    yield from lock.release_write()
    assert (yield from lock.write_locks()) == 1
    yield from lock.release_write()
    assert (yield from lock.write_locks()) == 0


@testing.effect
@in_tx
def test_write_lock_holder_can_acquire_read_lock_reentrancy():
    """write lock holder can acquire read lock (reentrancy)"""
    lock = yield from fx.TxReentrantLock.make()
    yield from lock.acquire_write()
    assert (yield from lock.acquire_read()) == 1
    assert (yield from lock.locked()) is True
    yield from lock.release_read()
    yield from lock.release_write()
    assert (yield from lock.locked()) is False


# --- scoped operations --------------------------------------------------------


@testing.effect
def test_read_lock_scoped_acquires_and_releases():
    """readLock scoped acquires and releases"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        yield from lock.read_lock()
        assert (yield from fx.tx(lock.read_locked())) is True

    yield from fx.scoped(body())
    assert (yield from fx.tx(lock.read_locked())) is False


@testing.effect
def test_write_lock_scoped_acquires_and_releases():
    """writeLock scoped acquires and releases"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        yield from lock.write_lock()
        assert (yield from fx.tx(lock.write_locked())) is True

    yield from fx.scoped(body())
    assert (yield from fx.tx(lock.write_locked())) is False


@testing.effect
def test_write_lock_can_be_acquired_reentrantly_in_the_same_scope():
    """writeLock can be acquired reentrantly in the same scope"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        yield from lock.write_lock()
        assert (yield from fx.tx(lock.write_locked())) is True

    yield from fx.scoped(body())
    assert (yield from fx.tx(lock.write_locked())) is False


# --- withLock operations ------------------------------------------------------


@testing.effect
def test_with_read_lock_runs_effect_and_releases():
    """withReadLock runs effect and releases"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        assert (yield from fx.tx(lock.read_locked())) is True
        return "read-result"

    assert (yield from lock.with_read_lock(body())) == "read-result"
    assert (yield from fx.tx(lock.read_locked())) is False


@testing.effect
def test_with_write_lock_runs_effect_and_releases():
    """withWriteLock runs effect and releases"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        assert (yield from fx.tx(lock.write_locked())) is True
        return "write-result"

    assert (yield from lock.with_write_lock(body())) == "write-result"
    assert (yield from fx.tx(lock.write_locked())) is False


@testing.effect
def test_with_lock_is_alias_for_with_write_lock():
    """withLock is alias for withWriteLock"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())

    @fx.fn
    def body():
        assert (yield from fx.tx(lock.write_locked())) is True
        return "exclusive"

    assert (yield from lock.with_lock(body())) == "exclusive"
    assert (yield from fx.tx(lock.locked())) is False


@testing.effect
def test_with_read_lock_releases_on_failure():
    """withReadLock releases on failure"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    ex = yield from lock.with_read_lock(fx.fail("boom")).exit()
    assert isinstance(ex, fx.Failure)
    assert (yield from fx.tx(lock.read_locked())) is False


@testing.effect
def test_with_write_lock_releases_on_failure():
    """withWriteLock releases on failure"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    ex = yield from lock.with_write_lock(fx.fail("boom")).exit()
    assert isinstance(ex, fx.Failure)
    assert (yield from fx.tx(lock.write_locked())) is False


@testing.effect
def test_with_read_lock_data_last_pipe_style():
    """withReadLock data-last (pipe) style"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    assert (yield from lock.with_read_lock(fx.succeed("piped"))) == "piped"
    assert (yield from fx.tx(lock.read_locked())) is False


@testing.effect
def test_with_write_lock_data_last_pipe_style():
    """withWriteLock data-last (pipe) style"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    assert (yield from lock.with_write_lock(fx.succeed("piped-write"))) == "piped-write"
    assert (yield from fx.tx(lock.write_locked())) is False


# --- concurrency --------------------------------------------------------------


@testing.effect
def test_multiple_readers_can_proceed_concurrently():
    """multiple readers can proceed concurrently"""
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    fiber1 = yield from lock.with_read_lock(fx.succeed(1)).fork()
    fiber2 = yield from lock.with_read_lock(fx.succeed(2)).fork()
    fiber3 = yield from lock.with_read_lock(fx.succeed(3)).fork()
    assert (yield from fx.Fiber.join_all([fiber1, fiber2, fiber3])) == [1, 2, 3]
    assert (yield from fx.tx(lock.locked())) is False


def _blocked_by_parent(
    acquire_parent: Callable[[fx.TxReentrantLock], fx.Effect[int]],
    release_parent: Callable[[fx.TxReentrantLock], fx.Effect[int]],
    child: Callable[[fx.TxReentrantLock, fx.Effect[None]], fx.Effect[None]],
    label: str,
):
    lock = yield from fx.tx(fx.TxReentrantLock.make())
    order: list[str] = []
    yield from fx.tx(acquire_parent(lock))
    fiber = yield from child(lock, fx.sync(lambda: order.append(label))).fork()
    order.append("parent-releasing")
    yield from fx.tx(release_parent(lock))
    yield from fiber.join()
    assert order == ["parent-releasing", label]
    assert (yield from fx.tx(lock.locked())) is False


@testing.effect
def test_writer_blocks_other_writers():
    """writer blocks other writers"""
    yield from _blocked_by_parent(
        fx.TxReentrantLock.acquire_write,
        fx.TxReentrantLock.release_write,
        fx.TxReentrantLock.with_write_lock,
        "child-wrote",
    )


@testing.effect
def test_writer_blocks_readers_from_other_fibers():
    """writer blocks readers from other fibers"""
    yield from _blocked_by_parent(
        fx.TxReentrantLock.acquire_write,
        fx.TxReentrantLock.release_write,
        fx.TxReentrantLock.with_read_lock,
        "child-read",
    )


@testing.effect
def test_reader_blocks_writer_from_another_fiber():
    """reader blocks writer from another fiber"""
    yield from _blocked_by_parent(
        fx.TxReentrantLock.acquire_read,
        fx.TxReentrantLock.release_read,
        fx.TxReentrantLock.with_write_lock,
        "child-wrote",
    )


# --- getters ------------------------------------------------------------------


@testing.effect
@in_tx
def test_read_locks_counts_total_read_locks():
    """readLocks counts total read locks"""
    lock = yield from fx.TxReentrantLock.make()
    yield from lock.acquire_read()
    yield from lock.acquire_read()
    assert (yield from lock.read_locks()) == 2
    yield from lock.release_read()
    assert (yield from lock.read_locks()) == 1
    yield from lock.release_read()
    assert (yield from lock.read_locks()) == 0


@testing.effect
@in_tx
def test_write_locks_counts_write_lock_depth():
    """writeLocks counts write lock depth"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.write_locks()) == 0
    yield from lock.acquire_write()
    assert (yield from lock.write_locks()) == 1
    yield from lock.acquire_write()
    assert (yield from lock.write_locks()) == 2
    yield from lock.release_write()
    yield from lock.release_write()
    assert (yield from lock.write_locks()) == 0


@testing.effect
@in_tx
def test_locked_returns_true_when_any_lock_is_held():
    """locked returns true when any lock is held"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.locked()) is False
    yield from lock.acquire_read()
    assert (yield from lock.locked()) is True
    yield from lock.release_read()
    assert (yield from lock.locked()) is False
    yield from lock.acquire_write()
    assert (yield from lock.locked()) is True
    yield from lock.release_write()
    assert (yield from lock.locked()) is False


# --- type guards --------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_reentrant_lock_identifies_tx_reentrant_lock_instances():
    """isTxReentrantLock identifies TxReentrantLock instances"""
    lock = yield from fx.TxReentrantLock.make()
    assert isinstance(lock, fx.TxReentrantLock)
    others: list[object] = [{}, None]
    for other in others:
        assert not isinstance(other, fx.TxReentrantLock)


# --- release without acquire --------------------------------------------------


@testing.effect
@in_tx
def test_release_read_without_acquire_returns_0():
    """releaseRead without acquire returns 0"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.release_read()) == 0


@testing.effect
@in_tx
def test_release_write_without_acquire_returns_0():
    """releaseWrite without acquire returns 0"""
    lock = yield from fx.TxReentrantLock.make()
    assert (yield from lock.release_write()) == 0


# --- scopes closed by another fiber -------------------------------------------


@testing.effect
def test_releases_a_scoped_read_lock_when_another_fiber_closes_the_scope():
    """releases a scoped read lock when another fiber closes the scope"""
    lock = yield from fx.TxReentrantLock.make()
    scope = fx.CloseableScope()
    fiber = yield from lock.read_lock().pipe(fx.provide_service(fx.Scope, scope)).fork()
    yield from fiber.join()
    yield from scope.close(fx.Success(None))
    assert (yield from lock.read_locked()) is False


@testing.effect
def test_releases_a_scoped_write_lock_when_another_fiber_closes_the_scope():
    """releases a scoped write lock when another fiber closes the scope"""
    lock = yield from fx.TxReentrantLock.make()
    scope = fx.CloseableScope()
    fiber = yield from lock.write_lock().pipe(fx.provide_service(fx.Scope, scope)).fork()
    yield from fiber.join()
    yield from scope.close(fx.Success(None))
    assert (yield from lock.write_locked()) is False
