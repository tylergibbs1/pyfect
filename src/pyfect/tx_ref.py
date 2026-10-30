"""``TxRef[A]``: a mutable cell read and written in transactions.

Every operation joins the running transaction (``fx.tx``), or runs as a
transaction of its own when there is none. Inside a transaction, reads and
writes go to its journal; other fibers see the writes only once the
outermost transaction commits.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect, _Sync
from pyfect.transaction import TransactionMeta, transactional


class TxRef[A]:
    """``TxRef(value)`` is Effect's ``makeUnsafe``; ``TxRef.make`` is the
    effect. A committed write that changes the value (by JavaScript's
    ``Object.is``: ``-0.0`` replaces ``0.0``) bumps ``version``; every
    committed write, changed or not, wakes the transactions waiting in
    ``tx_retry`` on this ref."""

    __slots__ = ("_pending", "_value", "_version")

    def __init__(self, value: A) -> None:
        self._value = value
        self._version = 0
        # Wake callbacks of transactions parked in ``tx_retry`` after reading
        # this ref, keyed by waiter.
        self._pending: dict[object, Callable[[], None]] = {}

    @staticmethod
    def make[T](value: T) -> Effect[TxRef[T]]:
        return _Sync(lambda: TxRef(value))

    @property
    def version(self) -> int:
        """How many committed writes changed the value."""
        return self._version

    def get(self) -> Effect[A]:
        return transactional(self._get)

    def set(self, value: A) -> Effect[None]:
        return self.modify(lambda _: (None, value))

    def update(self, f: Callable[[A], A]) -> Effect[None]:
        return self.modify(lambda current: (None, f(current)))

    def modify[B](self, f: Callable[[A], tuple[B, A]]) -> Effect[B]:
        """Replace the value with the second item of ``f(value)``; succeed
        with the first."""

        def run(state: TransactionMeta) -> B:
            entry = state._entry(self)
            result, entry._value = f(entry._value)
            entry._written = True
            return result

        return transactional(run)

    def _get(self, state: TransactionMeta) -> A:
        return state._entry(self)._value

    def __repr__(self) -> str:
        return f"TxRef({self._value!r})"


__all__ = ["TxRef"]
