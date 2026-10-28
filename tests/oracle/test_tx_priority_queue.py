"""Ports of Effect's ``TxPriorityQueue.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxPriorityQueue.offer(pq, 1)`` is ``pq.offer(1)``); an ``Order`` is a
``key`` function (none for ``Order.Number``), so the comparison-counting
titles count ``<`` calls on the keys; ``toArray`` is ``to_list``;
``fromIterable(order)(items)`` and ``make(order)(...items)`` take ``key=``
as a keyword instead of a first curried call; ``isTxPriorityQueue`` is
``isinstance``.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import total_ordering

import pyfect as fx
from pyfect import testing

from ._tx import in_tx


@total_ordering
class _Counted:
    """A key that counts how often it is compared."""

    comparisons = 0

    def __init__(self, value: int) -> None:
        self.value = value

    def __lt__(self, other: _Counted) -> bool:
        _Counted.comparisons += 1
        return self.value < other.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Counted) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_empty_creates_an_empty_queue():
    """empty creates an empty queue"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    assert (yield from pq.size()) == 0
    assert (yield from pq.is_empty()) is True


@testing.effect
@in_tx
def test_from_iterable_creates_a_sorted_queue():
    """fromIterable creates a sorted queue"""
    pq = yield from fx.TxPriorityQueue.from_iterable([3, 1, 2])
    assert (yield from pq.to_list()) == [1, 2, 3]


@testing.effect
@in_tx
def test_from_iterable_supports_the_curried_call():
    """fromIterable supports the curried call"""
    pq = yield from fx.TxPriorityQueue.from_iterable([3, 1, 2], key=lambda n: n)
    assert (yield from pq.to_list()) == [1, 2, 3]


@testing.effect
@in_tx
def test_make_creates_from_variadic_args():
    """make creates from variadic args"""
    pq = yield from fx.TxPriorityQueue.make(5, 3, 1, 4, 2)
    assert (yield from pq.to_list()) == [1, 2, 3, 4, 5]


# --- getters ------------------------------------------------------------------


@testing.effect
@in_tx
def test_size_returns_number_of_elements():
    """size returns number of elements"""
    pq = yield from fx.TxPriorityQueue.from_iterable([1, 2, 3])
    assert (yield from pq.size()) == 3


@testing.effect
@in_tx
def test_is_empty_is_non_empty():
    """isEmpty/isNonEmpty"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    assert (yield from pq.is_empty()) is True
    assert (yield from pq.is_non_empty()) is False
    yield from pq.offer(1)
    assert (yield from pq.is_empty()) is False
    assert (yield from pq.is_non_empty()) is True


@testing.effect
@in_tx
def test_peek_returns_smallest_without_removing():
    """peek returns smallest without removing"""
    pq = yield from fx.TxPriorityQueue.from_iterable([3, 1, 2])
    assert (yield from pq.peek()) == 1
    assert (yield from pq.size()) == 3


@testing.effect
@in_tx
def test_peek_option_returns_none_when_empty():
    """peekOption returns None when empty"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    assert (yield from pq.peek_option()) is None


@testing.effect
@in_tx
def test_peek_option_returns_some_when_non_empty():
    """peekOption returns Some when non-empty"""
    pq = yield from fx.TxPriorityQueue.from_iterable([3, 1])
    assert (yield from pq.peek_option()) == fx.Some(1)


# --- mutations ----------------------------------------------------------------


@testing.effect
def test_offer_all_preserves_a_one_shot_iterable_across_transaction_retries():
    """offerAll preserves a one-shot iterable across transaction retries"""
    queue = yield from fx.TxPriorityQueue[int].empty()
    gate = yield from fx.TxRef.make(False)

    def values() -> Iterator[int]:
        yield 2
        yield 1

    offer = queue.offer_all(values())

    @fx.fn
    def body():
        yield from offer
        if not (yield from gate.get()):
            return (yield from fx.tx_retry)

    fiber = yield from fx.tx(body()).fork(start_immediately=True)
    yield from gate.set(True)
    yield from fiber.join()
    assert (yield from queue.to_list()) == [1, 2]


@testing.effect
@in_tx
def test_offer_take_returns_elements_in_priority_order():
    """offer + take returns elements in priority order"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    yield from pq.offer(3)
    yield from pq.offer(1)
    yield from pq.offer(2)
    assert (yield from pq.take()) == 1
    assert (yield from pq.take()) == 2
    assert (yield from pq.take()) == 3


@testing.effect
@in_tx
def test_duplicate_priorities_are_all_returned():
    """duplicate priorities are all returned"""
    pq = yield from fx.TxPriorityQueue.from_iterable([2, 1, 2, 1, 3])
    assert (yield from pq.take_all()) == [1, 1, 2, 2, 3]


@testing.effect
@in_tx
def test_take_on_empty_retries_until_offer():
    """take on empty retries until offer"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    fiber = yield from pq.take().fork()
    yield from pq.offer(42)
    assert (yield from fiber.join()) == 42


@testing.effect
@in_tx
def test_take_option_returns_none_when_empty():
    """takeOption returns None when empty"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    assert (yield from pq.take_option()) is None


@testing.effect
@in_tx
def test_take_up_to_returns_min_n_size_elements_in_order():
    """takeUpTo returns min(n, size) elements in order"""
    pq = yield from fx.TxPriorityQueue.from_iterable([5, 3, 1, 4, 2])
    assert (yield from pq.take_up_to(3)) == [1, 2, 3]
    assert (yield from pq.size()) == 2


@testing.effect
@in_tx
def test_take_up_to_with_n_size_returns_all():
    """takeUpTo with n > size returns all"""
    pq = yield from fx.TxPriorityQueue.from_iterable([2, 1])
    assert (yield from pq.take_up_to(10)) == [1, 2]
    assert (yield from pq.size()) == 0


@testing.effect
@in_tx
def test_offer_all_inserts_multiple_elements():
    """offerAll inserts multiple elements"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    yield from pq.offer_all([3, 1, 2])
    assert (yield from pq.to_list()) == [1, 2, 3]


@testing.effect
@in_tx
def test_offer_all_does_not_compare_every_queued_element_for_one_new_value():
    """offerAll does not compare every queued element for one new value"""
    pq = yield from fx.TxPriorityQueue.from_iterable([i * 2 for i in range(128)], key=_Counted)
    _Counted.comparisons = 0
    yield from pq.offer_all([127])
    assert _Counted.comparisons < 32
    expected = [i * 2 for i in range(64)] + [127] + [(i + 64) * 2 for i in range(64)]
    assert (yield from pq.to_list()) == expected


@testing.effect
@in_tx
def test_offer_all_avoids_repeated_full_range_searches_for_an_interleaved_batch():
    """offerAll avoids repeated full-range searches for an interleaved batch"""
    queued = [i * 2 for i in range(256)]
    incoming = [i * 2 + 1 for i in range(256)]
    pq = yield from fx.TxPriorityQueue.from_iterable(queued, key=_Counted)
    _Counted.comparisons = 0
    yield from pq.offer_all(incoming)
    assert _Counted.comparisons < 900
    assert (yield from pq.to_list()) == list(range(512))


# --- filtering ----------------------------------------------------------------


@testing.effect
@in_tx
def test_remove_if_removes_matching_elements():
    """removeIf removes matching elements"""
    pq = yield from fx.TxPriorityQueue.from_iterable([1, 2, 3, 4, 5])
    yield from pq.remove_if(lambda n: n % 2 == 0)
    assert (yield from pq.take_all()) == [1, 3, 5]


@testing.effect
@in_tx
def test_retain_if_keeps_only_matching_elements():
    """retainIf keeps only matching elements"""
    pq = yield from fx.TxPriorityQueue.from_iterable([1, 2, 3, 4, 5])
    yield from pq.retain_if(lambda n: n % 2 == 0)
    assert (yield from pq.take_all()) == [2, 4]


# --- guards -------------------------------------------------------------------


@testing.effect
@in_tx
def test_is_tx_priority_queue():
    """isTxPriorityQueue"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    assert isinstance(pq, fx.TxPriorityQueue)
    for other in (None, {"some": "object"}, [1, 2, 3]):
        assert not isinstance(other, fx.TxPriorityQueue)


# --- concurrency --------------------------------------------------------------


@testing.effect
@in_tx
def test_concurrent_offer_and_take():
    """concurrent offer and take"""
    pq = yield from fx.TxPriorityQueue[int].empty()
    fiber = yield from fx.all(pq.take(), pq.take(), pq.take()).fork()
    yield from pq.offer_all([3, 1, 2])
    assert (yield from fiber.join()) == (1, 2, 3)


# --- custom ordering ----------------------------------------------------------


@testing.effect
@in_tx
def test_reverse_order_max_first():
    """reverse order (max-first)"""
    pq = yield from fx.TxPriorityQueue.from_iterable([1, 3, 2], key=lambda n: -n)
    assert (yield from pq.take()) == 3
