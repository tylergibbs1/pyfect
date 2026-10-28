"""``TxQueue[A, E]`` itself. See the package docstring for its behavior.

Every operation is one transactional step: it reads the state and items
from the transaction's journal, writes what changes, and returns its
outcome (a value, the queue's failure, or ``tx_retry`` to wait).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Never, overload

from pyfect import _tx_ops
from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.cause import interrupt as interrupt_cause
from pyfect.effect import fail_cause as fail_with
from pyfect.effect import fiber_id, succeed, sync
from pyfect.errors import Done
from pyfect.option import Option, Some
from pyfect.pull import is_done_cause
from pyfect.transaction import Transaction, TransactionMeta, tx, tx_retry
from pyfect.tx_queue._views import TxDequeue, TxEnqueue
from pyfect.tx_ref import TxRef

type Strategy = Literal["bounded", "unbounded", "dropping", "sliding"]


@dataclass(frozen=True, slots=True)
class _Open:
    pass


@dataclass(frozen=True, slots=True)
class _Closing[E]:
    """Failed or ended with items left: takers drain them first."""

    cause: Cause[E]


@dataclass(frozen=True, slots=True)
class _Done[E]:
    cause: Cause[E]


type _State[E] = _Open | _Closing[E] | _Done[E]

_OPEN = _Open()

type _Step[T, E] = Effect[T, E, Transaction]


class TxQueue[A, E = Never](TxEnqueue[A, E], TxDequeue[A, E]):
    """Build one with ``TxQueue[int].bounded(8)`` (or ``unbounded``,
    ``dropping``, ``sliding``); ``TxQueue[int, Done]`` can be ended."""

    __slots__ = ("_capacity", "_items", "_state", "_strategy")

    def __init__(self, strategy: Strategy, capacity: int | None) -> None:
        self._strategy: Strategy = strategy
        self._capacity = capacity
        self._items: TxRef[tuple[A, ...]] = TxRef(())
        self._state: TxRef[_State[E]] = TxRef(_OPEN)

    @classmethod
    def bounded(cls, capacity: int) -> Effect[TxQueue[A, E]]:
        """``offer`` waits while the queue holds ``capacity`` items."""
        return cls._make("bounded", capacity)

    @classmethod
    def unbounded(cls) -> Effect[TxQueue[A, E]]:
        return cls._make("unbounded", None)

    @classmethod
    def dropping(cls, capacity: int) -> Effect[TxQueue[A, E]]:
        """``offer`` on a full queue drops the new item."""
        return cls._make("dropping", capacity)

    @classmethod
    def sliding(cls, capacity: int) -> Effect[TxQueue[A, E]]:
        """``offer`` on a full queue drops the oldest item."""
        return cls._make("sliding", capacity)

    @classmethod
    def _make(cls, strategy: Strategy, capacity: int | None) -> Effect[TxQueue[A, E]]:
        if capacity is not None and capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        return sync(lambda: cls(strategy, capacity))

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    @property
    def capacity(self) -> int | None:
        """How many items the queue holds; ``None`` if unbounded."""
        return self._capacity

    # --- producing --------------------------------------------------------

    def offer(self, item: A) -> Effect[bool]:
        """Add an item. ``False`` if the queue is closing or done, or full and
        dropping. A full bounded queue waits; a full sliding one drops its
        oldest item."""

        def decide(meta: TransactionMeta) -> _Step[bool, Never]:
            accepted = self._offer(meta, item)
            return tx_retry if accepted is None else succeed(accepted)

        return _tx_ops.decide(decide)

    def offer_all[T](self: TxQueue[T, Any], items: Iterable[T]) -> Effect[list[T]]:
        """Offer each item in one transaction; succeeds with those not added.
        On a bounded queue, waits until all of them fit. ``items`` is read
        once, here, so a one-shot iterator survives transaction retries."""
        batch = list(items)

        def decide(meta: TransactionMeta) -> _Step[list[T], Never]:
            rejected: list[T] = []
            for item in batch:
                accepted = self._offer(meta, item)
                if accepted is None:
                    return tx_retry
                if not accepted:
                    rejected.append(item)
            return succeed(rejected)

        return _tx_ops.decide(decide)

    def fail(self, error: E) -> Effect[bool]:
        """Drop the items and finish the queue with ``error`` at once: takers
        fail with it. ``False`` if the queue was already closing or done."""

        def decide(meta: TransactionMeta) -> _Step[bool, Never]:
            if not isinstance(_tx_ops.value(meta, self._state), _Open):
                return succeed(False)
            _tx_ops.write(meta, self._items, ())
            _tx_ops.write(meta, self._state, _Done(fail_cause(error)))
            return succeed(True)

        return _tx_ops.decide(decide)

    def fail_cause(self, cause: Cause[E]) -> Effect[bool]:
        """Finish the queue with ``cause`` once its items are taken. ``False``
        if the queue was already closing or done."""

        def decide(meta: TransactionMeta) -> _Step[bool, Never]:
            if not isinstance(_tx_ops.value(meta, self._state), _Open):
                return succeed(False)
            items = _tx_ops.value(meta, self._items)
            _tx_ops.write(meta, self._state, _Closing(cause) if items else _Done(cause))
            return succeed(True)

        return _tx_ops.decide(decide)

    def end(self: TxEnqueue[Any, Done]) -> Effect[bool]:
        """No more items: takers fail with ``Done()`` once the queue drains.
        Only on queues whose error type is ``Done``."""
        return self.fail_cause(fail_cause(Done()))

    def interrupt(self) -> Effect[bool]:
        """Takers are interrupted (by the calling fiber) once the queue
        drains."""
        return fiber_id().flat_map(lambda fid: self.fail_cause(interrupt_cause(fid)))

    def shutdown(self) -> Effect[bool]:
        """Drop the items and interrupt the queue; ``False`` if it was
        already closing or done."""
        return tx(self.clear().ignore_cause().and_then(self.interrupt()))

    # --- consuming --------------------------------------------------------

    def take(self) -> Effect[A, E]:
        """Wait for an item. Once the queue is done, fails with its cause."""

        def decide(meta: TransactionMeta) -> _Step[A, E]:
            state = _tx_ops.value(meta, self._state)
            if isinstance(state, _Done):
                return fail_with(state.cause)
            items = _tx_ops.value(meta, self._items)
            if not items:
                return tx_retry
            self._remove(meta, state, items, 1)
            return succeed(items[0])

        return _tx_ops.decide(decide)

    def poll(self) -> Effect[Option[A]]:
        """An item if one is there now; ``None`` if not, or if the queue is
        done."""

        def decide(meta: TransactionMeta) -> _Step[Option[A], Never]:
            state = _tx_ops.value(meta, self._state)
            items = _tx_ops.value(meta, self._items)
            if isinstance(state, _Done) or not items:
                return succeed(None)
            self._remove(meta, state, items, 1)
            return succeed(Some(items[0]))

        return _tx_ops.decide(decide)

    def peek(self) -> Effect[A, E]:
        """Wait for an item and succeed with it, leaving it in the queue."""

        def decide(meta: TransactionMeta) -> _Step[A, E]:
            state = _tx_ops.value(meta, self._state)
            if isinstance(state, _Done):
                return fail_with(state.cause)
            items = _tx_ops.value(meta, self._items)
            return succeed(items[0]) if items else tx_retry

        return _tx_ops.decide(decide)

    def take_all(self) -> Effect[list[A], E]:
        """Wait for at least one item, then take them all."""

        def decide(meta: TransactionMeta) -> _Step[list[A], E]:
            state = _tx_ops.value(meta, self._state)
            if isinstance(state, _Done):
                return fail_with(state.cause)
            items = _tx_ops.value(meta, self._items)
            if not items:
                return tx_retry
            self._remove(meta, state, items, len(items))
            return succeed(list(items))

        return _tx_ops.decide(decide)

    def take_n(self, n: int) -> Effect[list[A], E]:
        """Wait for ``n`` items and take them. A bounded queue never holds
        more than its capacity, so asking for more takes that many; a closing
        queue gives what is left. A count of 0 or less takes nothing."""
        wanted = max(n, 0)
        minimum = wanted if self._capacity is None else min(wanted, self._capacity)
        return self._take_at_least(minimum, minimum)

    def take_between(self, minimum: int, maximum: int) -> Effect[list[A], E]:
        """Wait for ``minimum`` items, then take up to ``maximum``; a closing
        queue gives what is left. Takes nothing if either count is 0 or less,
        or ``minimum > maximum``."""
        if minimum <= 0 or maximum <= 0 or minimum > maximum:
            return self._take_at_least(0, 0)
        return self._take_at_least(minimum, maximum)

    @overload
    def clear[AA](self: TxQueue[AA, Done[Any]]) -> Effect[list[AA], Never]: ...
    @overload
    def clear[AA, EE](self: TxQueue[AA, EE | Done[Any]]) -> Effect[list[AA], EE]: ...
    @overload
    def clear(self) -> Effect[list[A], E]: ...
    def clear(self: TxQueue[Any, Any]) -> Effect[list[Any], Any]:
        """Take every item there is now, without waiting. On a queue that is
        done: ``[]`` if it was ended, otherwise fails with its cause."""

        def decide(meta: TransactionMeta) -> _Step[list[Any], Any]:
            state = _tx_ops.value(meta, self._state)
            if isinstance(state, _Done):
                return succeed([]) if is_done_cause(state.cause) else fail_with(state.cause)
            items = _tx_ops.value(meta, self._items)
            _tx_ops.write(meta, self._items, ())
            if isinstance(state, _Closing):
                _tx_ops.write(meta, self._state, _Done(state.cause))
            return succeed(list(items))

        return _tx_ops.decide(decide)

    # --- state ------------------------------------------------------------

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._items, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._items, lambda items: not items)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._items, bool)

    def is_full(self) -> Effect[bool]:
        capacity = self._capacity
        if capacity is None:
            return succeed(False)
        return _tx_ops.read(self._items, lambda items: len(items) >= capacity)

    def is_open(self) -> Effect[bool]:
        return self._state_is(_Open)

    def is_closing(self) -> Effect[bool]:
        return self._state_is(_Closing)

    def is_done(self) -> Effect[bool]:
        return self._state_is(_Done)

    def is_shutdown(self) -> Effect[bool]:
        """``is_done``."""
        return self.is_done()

    def await_completion(self) -> Effect[None]:
        """Wait until the queue is done, however it finished."""

        def decide(meta: TransactionMeta) -> _Step[None, Never]:
            done = isinstance(_tx_ops.value(meta, self._state), _Done)
            return succeed(None) if done else tx_retry

        return _tx_ops.decide(decide)

    # --- helpers ----------------------------------------------------------

    def _state_is(self, kind: type[_State[Any]]) -> Effect[bool]:
        return _tx_ops.read(self._state, lambda state: isinstance(state, kind))

    def _offer(self, meta: TransactionMeta, item: A) -> bool | None:
        """Whether ``item`` was added; ``None`` if the offer has to wait."""
        if not isinstance(_tx_ops.value(meta, self._state), _Open):
            return False
        items = _tx_ops.value(meta, self._items)
        if self._capacity is None or len(items) < self._capacity:
            _tx_ops.write(meta, self._items, (*items, item))
            return True
        match self._strategy:
            case "dropping":
                return False
            case "sliding":
                _tx_ops.write(meta, self._items, (*items[1:], item))
                return True
            case "bounded" | "unbounded":
                return None

    def _remove(
        self, meta: TransactionMeta, state: _State[E], items: tuple[A, ...], n: int
    ) -> None:
        """Drop the first ``n`` items, finishing a closing queue they empty."""
        rest = items[n:]
        _tx_ops.write(meta, self._items, rest)
        if isinstance(state, _Closing) and not rest:
            _tx_ops.write(meta, self._state, _Done(state.cause))

    def _take_at_least(self, minimum: int, maximum: int) -> Effect[list[A], E]:
        def decide(meta: TransactionMeta) -> _Step[list[A], E]:
            state = _tx_ops.value(meta, self._state)
            if isinstance(state, _Done):
                return fail_with(state.cause)
            items = _tx_ops.value(meta, self._items)
            if len(items) < minimum:
                if isinstance(state, _Open):
                    return tx_retry
                self._remove(meta, state, items, len(items))
                _tx_ops.write(meta, self._state, _Done(state.cause))
                return succeed(list(items))
            count = min(len(items), maximum)
            self._remove(meta, state, items, count)
            return succeed(list(items[:count]))

        return _tx_ops.decide(decide)

    def __repr__(self) -> str:
        return f"TxQueue({self._strategy}, {self._capacity})"


__all__ = ["Strategy", "TxQueue"]
