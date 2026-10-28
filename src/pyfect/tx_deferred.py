"""``TxDeferred[A, E]``: a transactional one-shot value (Effect's
``TxDeferred``).

It holds ``None`` until it is completed with a ``Result``, after which every
``wait`` succeeds with the value or fails with the error. Completing it
inside a transaction is visible to that transaction at once, and to other
fibers when the transaction commits.
"""

from __future__ import annotations

from typing import Never

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect.effect import fail, succeed, sync
from pyfect.option import Option, Some
from pyfect.result import Err, Ok, Result
from pyfect.transaction import Transaction, TransactionMeta, tx_retry
from pyfect.tx_ref import TxRef


class TxDeferred[A, E = Never]:
    """``TxDeferred(ref)`` is Effect's ``makeUnsafe``; ``make`` is the effect,
    spelled ``TxDeferred[int, str].make()``."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[Option[Result[A, E]]]) -> None:
        self._ref = ref

    @classmethod
    def make(cls) -> Effect[TxDeferred[A, E]]:
        return sync(lambda: cls(TxRef(None)))

    @property
    def ref(self) -> TxRef[Option[Result[A, E]]]:
        return self._ref

    def wait(self) -> Effect[A, E]:
        """Wait until completed (Effect's ``await``), then succeed with the
        value or fail with the error."""

        def decide(state: TransactionMeta) -> Effect[A, E, Transaction]:
            current = _tx_ops.value(state, self._ref)
            if current is None:
                return tx_retry
            result = current.value
            return succeed(result.value) if isinstance(result, Ok) else fail(result.error)

        return _tx_ops.decide(decide)

    def poll(self) -> Effect[Option[Result[A, E]]]:
        """``Some`` of the result once completed; ``None`` before."""
        return self._ref.get()

    def done(self, result: Result[A, E]) -> Effect[bool]:
        """Complete with ``result``; ``False`` if already completed."""

        def complete(current: Option[Result[A, E]]) -> tuple[bool, Option[Result[A, E]]]:
            return (False, current) if current is not None else (True, Some(result))

        return self._ref.modify(complete)

    def succeed(self, value: A) -> Effect[bool]:
        return self.done(Ok(value))

    def fail(self, error: E) -> Effect[bool]:
        return self.done(Err(error))

    def __repr__(self) -> str:
        return "TxDeferred()"


__all__ = ["TxDeferred"]
