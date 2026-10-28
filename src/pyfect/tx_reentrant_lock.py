"""``TxReentrantLock``: a transactional reentrant read/write lock (Effect's
``TxReentrantLock``).

Locks are held per fiber. Any number of fibers can hold read locks while no
other fiber holds the write lock; one fiber can hold the write lock while
no other fiber holds a read lock. A fiber can take either lock again while
it holds it (each take counts and needs its own release), and the write
lock's holder can also take read locks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Never

from pyfect import _tx_ops
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect.effect import fiber_id, succeed
from pyfect.option import Option, Some
from pyfect.scope import Scope, add_finalizer
from pyfect.transaction import Transaction, TransactionMeta, tx_restoring, tx_retry
from pyfect.tx_ref import TxRef

_NO_READERS: Mapping[int, int] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class LockState:
    """Read-lock counts by fiber id, and the write lock's holder and count."""

    readers: Mapping[int, int] = field(default=_NO_READERS)
    writer: tuple[int, int] | None = None


class TxReentrantLock:
    """``TxReentrantLock(ref)`` wraps an existing ``TxRef`` (Effect's
    ``makeUnsafe``); ``make`` is the effect."""

    __slots__ = ("_state",)

    def __init__(self, state: TxRef[LockState]) -> None:
        self._state = state

    @staticmethod
    def make() -> Effect[TxReentrantLock]:
        return TxRef.make(LockState()).map(TxReentrantLock)

    @property
    def ref(self) -> TxRef[LockState]:
        return self._state

    def acquire_read(self) -> Effect[int]:
        """Take a read lock, waiting while another fiber holds the write
        lock; succeeds with this fiber's read-lock count."""
        return self._as_fiber(self._acquire_read)

    def acquire_write(self) -> Effect[int]:
        """Take the write lock, waiting while another fiber holds any lock;
        succeeds with this fiber's write-lock count."""
        return self._as_fiber(self._acquire_write)

    def release_read(self) -> Effect[int]:
        """Give back one of this fiber's read locks; succeeds with how many it
        still holds (0 if it held none)."""
        return self._as_fiber(self._release_read)

    def release_write(self) -> Effect[int]:
        """Give back one take of the write lock if this fiber holds it;
        succeeds with how many it still holds (0 if it held none)."""
        return self._as_fiber(self._release_write)

    def read_lock(self) -> Effect[int, Never, Scope]:
        """Take a read lock until the current scope closes. Only the wait is
        interruptible; whoever closes the scope releases this fiber's lock."""
        return self._scoped(self._acquire_read, self._release_read)

    def write_lock(self) -> Effect[int, Never, Scope]:
        """Take the write lock until the current scope closes."""
        return self._scoped(self._acquire_write, self._release_write)

    def with_read_lock[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``eff`` holding a read lock, releasing it however it ends.
        Only the wait for the lock is interruptible."""
        require_effect(eff, "eff")
        return self._with_acquired(self._acquire_read, eff, self._release_read)

    def with_write_lock[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``eff`` holding the write lock, releasing it however it ends."""
        require_effect(eff, "eff")
        return self._with_acquired(self._acquire_write, eff, self._release_write)

    def with_lock[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """``with_write_lock``."""
        require_effect(eff, "eff")
        return self.with_write_lock(eff)

    def read_locks(self) -> Effect[int]:
        """Read locks held, summed over fibers."""
        return _tx_ops.read(self._state, lambda state: sum(state.readers.values()))

    def write_locks(self) -> Effect[int]:
        """How many times the write lock is held."""
        return _tx_ops.read(self._state, lambda state: state.writer[1] if state.writer else 0)

    def locked(self) -> Effect[bool]:
        return _tx_ops.read(self._state, lambda state: bool(state.readers) or bool(state.writer))

    def read_locked(self) -> Effect[bool]:
        return _tx_ops.read(self._state, lambda state: bool(state.readers))

    def write_locked(self) -> Effect[bool]:
        return _tx_ops.read(self._state, lambda state: state.writer is not None)

    # --- one-step transactions for a given fiber ------------------------------

    def _acquire_read(self, owner: int) -> Effect[int]:
        def take(meta: TransactionMeta) -> Effect[int, Never, Transaction]:
            state = _tx_ops.value(meta, self._state)
            if state.writer is not None and state.writer[0] != owner:
                return tx_retry
            count = state.readers.get(owner, 0) + 1
            readers = MappingProxyType({**state.readers, owner: count})
            _tx_ops.write(meta, self._state, replace(state, readers=readers))
            return succeed(count)

        return _tx_ops.decide(take)

    def _acquire_write(self, owner: int) -> Effect[int]:
        def take(meta: TransactionMeta) -> Effect[int, Never, Transaction]:
            state = _tx_ops.value(meta, self._state)
            if state.writer is not None and state.writer[0] != owner:
                return tx_retry
            if any(reader != owner for reader in state.readers):
                return tx_retry
            count = state.writer[1] + 1 if state.writer is not None else 1
            _tx_ops.write(meta, self._state, replace(state, writer=(owner, count)))
            return succeed(count)

        return _tx_ops.decide(take)

    def _release_read(self, owner: int) -> Effect[int]:
        def give_back(state: LockState) -> tuple[int, Option[LockState]]:
            count = state.readers.get(owner, 0)
            if count <= 0:
                return 0, None
            readers = {**state.readers, owner: count - 1}
            if count == 1:
                del readers[owner]
            return count - 1, Some(replace(state, readers=MappingProxyType(readers)))

        return _tx_ops.modify_or_skip(self._state, give_back)

    def _release_write(self, owner: int) -> Effect[int]:
        def give_back(state: LockState) -> tuple[int, Option[LockState]]:
            if state.writer is None or state.writer[0] != owner:
                return 0, None
            count = state.writer[1] - 1
            return count, Some(replace(state, writer=(owner, count) if count > 0 else None))

        return _tx_ops.modify_or_skip(self._state, give_back)

    # --- combinators ----------------------------------------------------------

    @staticmethod
    def _as_fiber[A](f: Callable[[int], Effect[A]]) -> Effect[A]:
        return fiber_id().flat_map(f)

    @staticmethod
    def _scoped(
        acquire: Callable[[int], Effect[int]], release: Callable[[int], Effect[int]]
    ) -> Effect[int, Never, Scope]:
        def body(fid: int, restore: Restore) -> Effect[int, Never, Scope]:
            return tx_restoring(restore, acquire(fid)).tap(
                lambda _: add_finalizer(lambda _: release(fid))
            )

        return fiber_id().flat_map(
            lambda fid: uninterruptible_mask(lambda restore: body(fid, restore))
        )

    @staticmethod
    def _with_acquired[A, E, R](
        acquire: Callable[[int], Effect[int]],
        eff: Effect[A, E, R],
        release: Callable[[int], Effect[int]],
    ) -> Effect[A, E, R]:
        def body(fid: int, restore: Restore) -> Effect[A, E, R]:
            return tx_restoring(restore, acquire(fid)).and_then(restore(eff).ensuring(release(fid)))

        return fiber_id().flat_map(
            lambda fid: uninterruptible_mask(lambda restore: body(fid, restore))
        )

    def __repr__(self) -> str:
        return "TxReentrantLock()"


__all__ = ["LockState", "TxReentrantLock"]
