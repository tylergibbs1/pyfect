"""Transactions over ``TxRef`` values (Effect's ``Effect.tx``).

``tx(eff)`` runs ``eff`` all or nothing: the ``TxRef`` values it reads and
writes go through a journal, and only a successful run publishes its writes.
Transactions are optimistic. At the end of a run the journal is checked
against the refs: if another transaction committed to a ref this one read,
the run is discarded and the body runs again (a ``"conflict"``). ``tx_retry``
discards the run on purpose and parks the fiber until one of the refs it read
is written (a ``"retry"``).

The check and the commit happen in one fiber step, holding the process-wide
commit lock, so no other fiber, of this run or of a run on another thread,
sees a half-published transaction or commits in between. ``tx`` inside a running transaction
joins it: nested calls share one journal and commit together, and a failure
caught inside the transaction keeps the writes made before it.

Yield ``Transaction()`` inside a body to read its ``TransactionMeta``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, Never, final, overload

from pyfect._core import (
    Effect,
    Restore,
    _Callback,
    _FailCause,
    _FromExit,
    _Locally,
    _Succeed,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._js import same_value
from pyfect._waiters import wake_soon_from_here
from pyfect.cause import Cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.clock import Clock
from pyfect.context import Tag
from pyfect.exit import Exit, Success

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.tx_ref import TxRef

type TransactionRetryReason = Literal["retry", "conflict"]
"""Why a run of a transaction body started again: ``"retry"`` after
``tx_retry``, ``"conflict"`` after a ref it read changed before it could
commit."""

_NANOS_PER_MILLI = 1_000_000

_COMMIT = threading.Lock()
"""Held to read a ref's version and value together, to check a journal and
commit it, and to register a ``tx_retry`` waiter: runs on other threads share
``TxRef`` values, and a transaction spans many refs. Nothing else runs under
it, so it is never held long and never taken twice."""


@final
class JournalEntry:
    """What a transaction knows about one ``TxRef``: the version it saw, its
    value inside the transaction, and whether the transaction wrote it."""

    __slots__ = ("_value", "_version", "_written")

    def __init__(self, version: int, value: Any) -> None:
        self._version = version
        self._value = value
        self._written = False

    @property
    def version(self) -> int:
        return self._version

    @property
    def value(self) -> Any:
        return self._value

    @property
    def written(self) -> bool:
        return self._written

    def __repr__(self) -> str:
        return (
            f"JournalEntry(version={self._version}, value={self._value!r}, written={self._written})"
        )


@final
class TransactionMeta:
    """The journal and attempt metadata of a running transaction.

    ``attempt`` counts runs of the outermost body from 1; ``retry_reason`` is
    ``None`` on the first. ``start`` and ``now`` are wall-clock milliseconds
    since the epoch read from the ``Clock``, as in schedule metadata:
    ``start`` when the transaction began, ``now`` when this attempt began."""

    __slots__ = (
        "_attempt",
        "_completed",
        "_journal",
        "_now_ns",
        "_previous_ns",
        "_retry",
        "_retry_reason",
        "_start_ns",
    )

    def __init__(self, start_ns: int) -> None:
        self._journal: dict[TxRef[Any], JournalEntry] = {}
        self._retry = False
        self._completed = False
        self._attempt = 1
        self._retry_reason: TransactionRetryReason | None = None
        self._start_ns = start_ns
        self._now_ns = start_ns
        self._previous_ns = start_ns

    @property
    def journal(self) -> Mapping[TxRef[Any], JournalEntry]:
        return MappingProxyType(self._journal)

    @property
    def attempt(self) -> int:
        return self._attempt

    @property
    def retry_reason(self) -> TransactionRetryReason | None:
        return self._retry_reason

    @property
    def start(self) -> float:
        return self._start_ns / _NANOS_PER_MILLI

    @property
    def now(self) -> float:
        return self._now_ns / _NANOS_PER_MILLI

    @property
    def elapsed(self) -> float:
        """Milliseconds since the first attempt began: ``now - start``, as Effect's."""
        return self.now - self.start

    @property
    def elapsed_since_previous(self) -> float:
        """Milliseconds since the previous attempt began, as Effect's."""
        return self.now - self._previous_ns / _NANOS_PER_MILLI

    def _entry(self, ref: TxRef[Any]) -> JournalEntry:
        entry = self._journal.get(ref)
        if entry is None:
            with _COMMIT:
                entry = JournalEntry(ref._version, ref._value)
            self._journal[ref] = entry
        return entry

    def _consistent(self) -> bool:
        return all(ref._version == entry._version for ref, entry in self._journal.items())

    def _next_attempt(self, now_ns: int) -> None:
        self._attempt += 1
        self._retry_reason = "retry" if self._retry else "conflict"
        self._previous_ns = self._now_ns
        self._now_ns = now_ns
        self._clear()

    def _try_commit(self, publish: bool) -> bool:
        """Check the journal against the refs and, if no ref it read has
        changed and ``publish``, publish its writes and wake the waiters of
        the refs written, all at once. ``False``: a ref changed."""
        wakes: list[Callable[[], None]] = []
        with _COMMIT:
            if not self._consistent():
                return False
            if publish:
                for ref, entry in self._journal.items():
                    if not entry._written:
                        continue
                    if not same_value(entry._value, ref._value):
                        ref._version += 1
                        ref._value = entry._value
                    if ref._pending:
                        wakes.extend(ref._pending.values())
                        ref._pending.clear()
        for wake in wakes:
            wake()
        return True

    def _clear(self) -> None:
        self._retry = False
        self._journal.clear()


class Transaction(Tag[TransactionMeta]):
    """The running transaction's state. Nested ``tx`` calls see the same
    ``TransactionMeta``."""


def active_transaction(fiber: Fiber[Any, Any]) -> TransactionMeta | None:
    """The transaction ``fiber`` is running in, if any. A child fiber
    inherits its parent's; once that transaction has ended it no longer
    counts, and the child's next ``tx`` starts its own."""
    found, state = fiber._context.lookup(Transaction)
    if not found or state._completed:
        return None
    return state


@overload
def tx[A, E](eff: Effect[A, E, Transaction]) -> Effect[A, E]: ...
@overload
def tx[A, E, R](eff: Effect[A, E, Transaction | R]) -> Effect[A, E, R]: ...
def tx(eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    """Run ``eff`` as one transaction, or as part of the running one."""
    require_effect(eff, "eff")
    return _WithFiber(
        lambda fiber: eff if active_transaction(fiber) is not None else _boundary(fiber, eff)
    )


def tx_restoring[A, E](restore: Restore, eff: Effect[A, E, Transaction]) -> Effect[A, E]:
    """``tx(eff)`` called from an uninterruptible region: the body and its
    ``tx_retry`` wait run under ``restore``, while the commit and what the
    caller does next stay uninterruptible, so an interrupt cannot land
    between committing a claim (a permit, a lock) and guarding it."""
    require_effect(eff, "eff")
    return _tx_restoring(restore, eff)


def _tx_restoring(restore: Restore, eff: Effect[Any, Any, Any]) -> Effect[Any, Any]:
    return _WithFiber(
        lambda fiber: (
            restore(eff)
            if active_transaction(fiber) is not None
            else _boundary(fiber, eff, restore)
        )
    )


def transactional[A](f: Callable[[TransactionMeta], A]) -> Effect[A]:
    """``f`` applied to the running transaction, in a transaction of its
    own when none is running. The building block of ``TxRef``."""

    def body(fiber: Fiber[Any, Any]) -> Effect[A]:
        state = active_transaction(fiber)
        if state is not None:
            return _Sync(lambda: f(state))
        return _boundary(fiber, Transaction().map(f))

    return _WithFiber(body)


def _retry(state: TransactionMeta) -> Effect[Never]:
    state._retry = True
    return _WithFiber(lambda fiber: _FailCause(interrupt_cause(fiber.id)))


tx_retry: Effect[Never, Never, Transaction] = Transaction().flat_map(_retry)
"""Abandon this run of the transaction and run it again once a ``TxRef``
it read has been written."""


def _boundary[A, E](
    fiber: Fiber[Any, Any], eff: Effect[A, E, Any], restore: Restore | None = None
) -> Effect[A, E]:
    """Run ``eff`` as the outermost transaction. With ``restore``, the
    caller is already uninterruptible and ``restore`` makes the body
    interruptible again; without it, the boundary masks itself."""
    clock = fiber.get_ref(Clock)
    state = TransactionMeta(clock.now_nanos_unsafe())

    def run(restore: Restore) -> Effect[A, E]:
        attempt = (
            _Locally[A, E, Never](restore(eff), lambda ctx: ctx.add(Transaction, state))
            .tap_cause(lambda cause: _after_failure(state, cause, restore))
            .exit()
        )

        def step(ex: Exit[A, E]) -> Effect[A, E]:
            if state._retry or not state._try_commit(isinstance(ex, Success)):
                state._next_attempt(clock.now_nanos_unsafe())
                return attempt.flat_map(step)
            state._clear()
            state._completed = True
            return _FromExit(ex)

        return attempt.flat_map(step)

    return uninterruptible_mask(run) if restore is None else run(restore)


_VOID: Effect[None] = _Succeed(None)


def _after_failure(state: TransactionMeta, cause: Cause[Any], restore: Restore) -> Effect[None]:
    if not state._retry:
        return _VOID
    if not cause.has_interrupts_only:
        # ``tx_retry`` interrupted the body, but something else failed too
        # (a finalizer): that failure is the transaction's outcome.
        state._clear()
        return _VOID
    return restore(_await_change(state))


def _await_change(state: TransactionMeta) -> Effect[None]:
    """Park until a ref in the journal is written. The read set is checked
    and the waiter registered in one step: a commit that landed after the
    reads has already woken its waiters, so a stale read set reruns at
    once. A commit wakes the waiter in a task on the committing fiber's
    dispatcher, not in the committing step (Effect's
    ``fiber.currentDispatcher.scheduleTask``), so an interrupt sent later in
    that step still finds it parked; a commit in another run wakes it through
    the waiter's own run."""

    def park(fiber: Fiber[Any, Any]) -> Effect[None]:
        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            key = object()
            refs = list(state._journal)

            def clear() -> None:
                with _COMMIT:
                    for ref in refs:
                        ref._pending.pop(key, None)

            def wake() -> None:
                clear()
                resume(_VOID)

            with _COMMIT:
                if not state._consistent():
                    stale = True
                else:
                    stale = False
                    for ref in refs:
                        ref._pending[key] = lambda: wake_soon_from_here(fiber, wake)
            if stale:
                resume(_VOID)
                return None
            return _Sync(clear)

        return _Callback(register)

    return _WithFiber(park)


__all__ = [
    "JournalEntry",
    "Transaction",
    "TransactionMeta",
    "TransactionRetryReason",
    "active_transaction",
    "transactional",
    "tx",
    "tx_restoring",
    "tx_retry",
]
