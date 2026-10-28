"""``TxSemaphore``: a transactional counting semaphore (Effect's
``TxSemaphore``).

The free permits live in a ``TxRef``. ``acquire`` waits (``tx_retry``)
until enough permits are free; ``release`` never raises the count above the
capacity it was made with. Inside a transaction, acquiring and releasing
take effect only when it commits.
"""

from __future__ import annotations

from typing import Never

from pyfect import _tx_ops
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect.effect import die, void
from pyfect.scope import Scope, add_finalizer
from pyfect.transaction import Transaction, TransactionMeta, tx_restoring, tx_retry
from pyfect.tx_ref import TxRef


def _positive(n: int) -> Effect[None]:
    """Effect dies, rather than raising, on a count that is not positive."""
    return void if n > 0 else die(ValueError("Number of permits must be positive"))


class TxSemaphore:
    """``TxSemaphore(ref, capacity)`` wraps an existing ``TxRef`` (Effect's
    ``makeUnsafe``); ``make`` is the effect."""

    __slots__ = ("_capacity", "_permits")

    def __init__(self, permits: TxRef[int], capacity: int) -> None:
        self._permits = permits
        self._capacity = capacity

    @staticmethod
    def make(permits: int) -> Effect[TxSemaphore]:
        """A semaphore with ``permits`` free permits, also its capacity. Dies
        if ``permits`` is negative."""
        if permits < 0:
            return die(ValueError("Permits must be non-negative"))
        return TxRef.make(permits).map(lambda ref: TxSemaphore(ref, permits))

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def ref(self) -> TxRef[int]:
        """The free permits."""
        return self._permits

    def available(self) -> Effect[int]:
        return self._permits.get()

    def acquire(self) -> Effect[None]:
        """Take one permit, waiting until one is free."""
        return self._acquire(1)

    def acquire_n(self, n: int) -> Effect[None]:
        """Take ``n`` permits at once, waiting until that many are free.
        Dies if ``n`` is not positive."""
        return _positive(n).and_then(self._acquire(n))

    def try_acquire(self) -> Effect[bool]:
        """Take one permit if one is free now."""
        return self._try_acquire(1)

    def try_acquire_n(self, n: int) -> Effect[bool]:
        """Take ``n`` permits if that many are free now. Dies if ``n`` is not
        positive."""
        return _positive(n).and_then(self._try_acquire(n))

    def release(self) -> Effect[None]:
        """Give back one permit, up to the capacity."""
        return self._release(1)

    def release_n(self, n: int) -> Effect[None]:
        """Give back ``n`` permits, up to the capacity. Dies if ``n`` is not
        positive."""
        return _positive(n).and_then(self._release(n))

    def with_permit[A, E, R](self, eff: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``eff`` holding one permit, giving it back however it ends.
        Only the wait for the permit is interruptible."""
        require_effect(eff, "eff")
        return self._with_acquired(self.acquire(), eff, self.release())

    def with_permits[A, E, R](self, eff: Effect[A, E, R], n: int) -> Effect[A, E, R]:
        """``with_permit`` for ``n`` permits."""
        require_effect(eff, "eff")
        return self._with_acquired(self.acquire_n(n), eff, self.release_n(n))

    def with_permit_scoped(self) -> Effect[None, Never, Scope]:
        """Take one permit until the current scope closes. Only the wait for
        the permit is interruptible."""
        release = self.release()
        return uninterruptible_mask(
            lambda restore: tx_restoring(restore, self.acquire()).and_then(
                add_finalizer(lambda _: release)
            )
        )

    def _acquire(self, n: int) -> Effect[None]:
        def take(state: TransactionMeta) -> Effect[None, Never, Transaction]:
            permits = _tx_ops.value(state, self._permits)
            if permits < n:
                return tx_retry
            _tx_ops.write(state, self._permits, permits - n)
            return void

        return _tx_ops.decide(take)

    def _try_acquire(self, n: int) -> Effect[bool]:
        return self._permits.modify(
            lambda permits: (True, permits - n) if permits >= n else (False, permits)
        )

    def _release(self, n: int) -> Effect[None]:
        return self._permits.update(lambda permits: min(permits + n, self._capacity))

    def _with_acquired[A, E, R](
        self, acquire: Effect[None], eff: Effect[A, E, R], release: Effect[None]
    ) -> Effect[A, E, R]:
        def body(restore: Restore) -> Effect[A, E, R]:
            return tx_restoring(restore, acquire).and_then(restore(eff).ensuring(release))

        return uninterruptible_mask(body)

    def __repr__(self) -> str:
        return f"TxSemaphore(capacity={self._capacity})"


__all__ = ["TxSemaphore"]
