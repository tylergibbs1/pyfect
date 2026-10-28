"""Ports of Effect's ``TxQueue.test.ts``, every title.

Each test's docstring is the Effect test title. Module functions are methods
(``TxQueue.offer(q, 1)`` is ``q.offer(1)``); ``awaitCompletion`` is
``await_completion``; ``Cause.Done()`` is ``fx.Done()``; ``isTxQueue`` /
``isTxEnqueue`` / ``isTxDequeue`` are ``isinstance(x, TxQueue)``, since the
views are protocols that every ``TxQueue`` satisfies. Counts are ``int``s,
so the fractional and ``NaN`` counts of "takeN and takeBetween normalize
element counts before waiting" become their normalized ``int`` (1 and 0).
"""

from collections.abc import Iterator
from typing import Never

import pyfect as fx
from pyfect import testing

from ._tx import in_tx


def _failure(ex: fx.Exit[object, object]) -> fx.Cause[object]:
    assert isinstance(ex, fx.Failure)
    return ex.cause


# --- interfaces ---------------------------------------------------------------


@testing.effect
@in_tx
def test_tx_enqueue_provides_write_only_interface():
    """TxEnqueue provides write-only interface"""
    queue = yield from fx.TxQueue[int].bounded(5)
    enqueue: fx.TxEnqueue[int, Never] = queue
    assert isinstance(enqueue, fx.TxQueue)
    assert (yield from enqueue.offer(42)) is True
    assert (yield from enqueue.offer_all([1, 2, 3])) == []


@testing.effect
@in_tx
def test_tx_dequeue_provides_read_only_interface():
    """TxDequeue provides read-only interface"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    dequeue: fx.TxDequeue[int, Never] = queue
    assert isinstance(dequeue, fx.TxQueue)
    assert (yield from dequeue.take()) == 1
    assert (yield from dequeue.poll()) == fx.Some(2)


@testing.effect
@in_tx
def test_tx_queue_provides_both_enqueue_and_dequeue_operations():
    """TxQueue provides both enqueue and dequeue operations"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert isinstance(queue, fx.TxQueue)
    yield from queue.offer(42)
    assert (yield from queue.take()) == 42


# --- interface segregation ----------------------------------------------------


@testing.effect
@in_tx
def test_tx_enqueue_interface_enforces_write_only_operations():
    """TxEnqueue interface enforces write-only operations"""
    queue = yield from fx.TxQueue[int, str | fx.Done].bounded(5)
    enqueue: fx.TxEnqueue[int, str | fx.Done] = queue
    assert (yield from enqueue.offer(42)) is True
    assert (yield from enqueue.offer_all([1, 2, 3])) == []
    assert (yield from enqueue.fail_cause(fx.cause.interrupt())) is True
    assert (yield from queue.end()) is False


@testing.effect
@in_tx
def test_tx_dequeue_interface_enforces_read_only_operations():
    """TxDequeue interface enforces read-only operations"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    dequeue: fx.TxDequeue[int, str] = queue
    assert (yield from dequeue.take()) == 1
    assert (yield from dequeue.poll()) == fx.Some(2)
    assert (yield from dequeue.peek()) == 3
    assert (yield from dequeue.size()) == 1
    assert (yield from dequeue.is_empty()) is False
    assert (yield from dequeue.is_open()) is True


@testing.effect
@in_tx
def test_interface_assignments_maintain_type_safety():
    """Interface assignments maintain type safety"""
    queue = yield from fx.TxQueue[int].bounded(5)
    enqueue: fx.TxEnqueue[int, Never] = queue
    dequeue: fx.TxDequeue[int, Never] = queue
    full_queue: fx.TxQueue[int] = queue
    yield from enqueue.offer(1)
    yield from full_queue.offer(2)
    assert (yield from dequeue.take()) == 1
    assert (yield from full_queue.take()) == 2
    assert (yield from dequeue.size()) == (yield from full_queue.size())


@testing.effect
@in_tx
def test_interface_type_guards_work_correctly():
    """Interface type guards work correctly"""
    queue = yield from fx.TxQueue[int].bounded(5)
    enqueue: fx.TxEnqueue[int, Never] = queue
    dequeue: fx.TxDequeue[int, Never] = queue
    assert isinstance(queue, fx.TxQueue)
    assert isinstance(enqueue, fx.TxQueue)
    assert isinstance(dequeue, fx.TxQueue)


# --- constructors -------------------------------------------------------------


@testing.effect
@in_tx
def test_bounded_creates_queue_with_specified_capacity():
    """bounded creates queue with specified capacity"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_unbounded_creates_queue_with_unlimited_capacity():
    """unbounded creates queue with unlimited capacity"""
    queue = yield from fx.TxQueue[str].unbounded()
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_dropping_creates_queue_with_dropping_strategy():
    """dropping creates queue with dropping strategy"""
    queue = yield from fx.TxQueue[int].dropping(2)
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_sliding_creates_queue_with_sliding_strategy():
    """sliding creates queue with sliding strategy"""
    queue = yield from fx.TxQueue[int].sliding(2)
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


# --- basic operations ---------------------------------------------------------


@testing.effect
@in_tx
def test_offer_and_take_work_correctly():
    """offer and take work correctly"""
    queue = yield from fx.TxQueue[str].bounded(10)
    assert (yield from queue.offer("hello")) is True
    assert (yield from queue.take()) == "hello"


@testing.effect
@in_tx
def test_poll_returns_option_none_for_empty_queue():
    """poll returns Option.none for empty queue"""
    queue = yield from fx.TxQueue[int].bounded(10)
    assert (yield from queue.poll()) is None


@testing.effect
@in_tx
def test_poll_returns_option_some_for_non_empty_queue():
    """poll returns Option.some for non-empty queue"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer(42)
    assert (yield from queue.poll()) == fx.Some(42)


@testing.effect
@in_tx
def test_poll_completes_a_closing_queue_after_removing_the_last_item():
    """poll completes a closing queue after removing the last item"""
    queue = yield from fx.TxQueue[int].bounded(1)
    yield from queue.offer(42)
    yield from queue.interrupt()
    assert (yield from queue.poll()) == fx.Some(42)
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_clear_completes_a_closing_queue_after_removing_all_items():
    """clear completes a closing queue after removing all items"""
    queue = yield from fx.TxQueue[int].bounded(1)
    yield from queue.offer(42)
    yield from queue.interrupt()
    assert (yield from queue.clear()) == [42]
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_offer_all_works_correctly():
    """offerAll works correctly"""
    queue = yield from fx.TxQueue[int].bounded(10)
    assert (yield from queue.offer_all([1, 2, 3, 4, 5])) == []
    assert (yield from queue.size()) == 5


@testing.effect
def test_offer_all_preserves_a_one_shot_iterable_across_retries_and_runs():
    """offerAll preserves a one-shot iterable across retries and runs"""
    queue = yield from fx.TxQueue[int].bounded(1)
    yield from queue.offer(1)

    def values() -> Iterator[int]:
        yield 2

    offer = queue.offer_all(values())
    fiber = yield from offer.fork(start_immediately=True)

    assert (yield from queue.take()) == 1
    assert (yield from fiber.join()) == []
    assert (yield from queue.poll()) == fx.Some(2)

    assert (yield from offer) == []
    assert (yield from queue.poll()) == fx.Some(2)


@testing.effect
@in_tx
def test_take_all_works_correctly_with_new_signature():
    """takeAll works correctly with new signature"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5])
    assert (yield from queue.take_all()) == [1, 2, 3, 4, 5]
    assert (yield from queue.size()) == 0


@testing.effect
@in_tx
def test_take_all_with_interrupted_queue_returns_done_flag():
    """takeAll with interrupted queue returns done flag"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2])
    yield from queue.interrupt()
    assert (yield from queue.take_all()) == [1, 2]


@testing.effect
@in_tx
def test_take_all_with_failed_queue_propagates_error():
    """takeAll with failed queue propagates error"""
    queue = yield from fx.TxQueue[int, str].bounded(10)
    yield from queue.offer_all([1, 2])
    yield from queue.fail("queue failed")
    assert (yield from queue.take_all().flip()) == "queue failed"


@testing.effect
@in_tx
def test_take_n_works_correctly_with_new_signature():
    """takeN works correctly with new signature"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5])
    assert (yield from queue.take_n(3)) == [1, 2, 3]
    assert (yield from queue.size()) == 2


@testing.effect
@in_tx
def test_take_n_and_take_between_normalize_element_counts_before_waiting():
    """takeN and takeBetween normalize element counts before waiting"""
    take_n_queue = yield from fx.TxQueue[int].unbounded()
    yield from take_n_queue.offer(1)
    assert (yield from take_n_queue.take_n(1)) == [1]

    take_between_queue = yield from fx.TxQueue[int].unbounded()
    yield from take_between_queue.offer(1)
    assert (yield from take_between_queue.take_between(1, 2)) == [1]

    invalid_queue = yield from fx.TxQueue[int].unbounded()
    yield from invalid_queue.offer(1)
    assert (yield from invalid_queue.take_n(0)) == []
    assert (yield from invalid_queue.take_all()) == [1]


@testing.effect
@in_tx
def test_take_n_with_queue_completion_gets_available_items():
    """takeN with queue completion gets available items"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2])
    yield from queue.interrupt()
    assert (yield from queue.take_n(5)) == [1, 2]


@testing.effect
@in_tx
def test_take_n_with_failed_queue_propagates_error():
    """takeN with failed queue propagates error"""
    queue = yield from fx.TxQueue[int, str].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    yield from queue.fail("queue failed")
    assert (yield from queue.take_n(2).flip()) == "queue failed"


@testing.effect
@in_tx
def test_take_n_with_capacity_constraint_takes_available_items():
    """takeN with capacity constraint takes available items"""
    queue = yield from fx.TxQueue[int].bounded(3)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.take_n(10)) == [1, 2, 3]
    assert (yield from queue.size()) == 0


@testing.effect
@in_tx
def test_take_all_on_empty_closed_queue_gets_interrupted():
    """takeAll() on empty closed queue gets interrupted"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    ex = yield from queue.take_all().exit()
    assert _failure(ex).has_interrupts_only


@testing.effect
@in_tx
def test_take_all_waits_when_empty_then_returns_items_when_available():
    """takeAll() waits when empty then returns items when available"""
    queue = yield from fx.TxQueue[int].bounded(5)
    fiber = yield from queue.take_all().fork()
    yield from queue.offer_all([1, 2, 3])
    assert (yield from fiber.join()) == [1, 2, 3]


@testing.effect
@in_tx
def test_take_all_during_state_transition_handles_race_condition():
    """takeAll() during state transition handles race condition"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2])
    yield from queue.interrupt()
    assert (yield from queue.take_all()) == [1, 2]
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_take_n_0_returns_empty_array():
    """takeN(0) returns empty array"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.take_n(0)) == []
    assert (yield from queue.size()) == 3


@testing.effect
@in_tx
def test_take_n_with_closing_queue_returns_available_items():
    """takeN() with closing queue returns available items"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2])
    yield from queue.interrupt()
    assert (yield from queue.take_n(5)) == [1, 2]
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_take_n_signature_validation_returns_array_a_not_array_a_boolean():
    """takeN() signature validation - returns Array<A> not [Array<A>, boolean]"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    items = yield from queue.take_n(2)
    assert isinstance(items, list)
    assert items == [1, 2]


@testing.effect
@in_tx
def test_take_between_basic_functionality():
    """takeBetween() basic functionality"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5, 6, 7, 8])
    assert (yield from queue.take_between(2, 5)) == [1, 2, 3, 4, 5]
    assert (yield from queue.take_between(1, 10)) == [6, 7, 8]
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_take_between_takes_up_to_maximum_when_available():
    """takeBetween() takes up to maximum when available"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5, 6, 7])
    assert (yield from queue.take_between(3, 5)) == [1, 2, 3, 4, 5]
    assert (yield from queue.take_all()) == [6, 7]


@testing.effect
@in_tx
def test_take_between_with_invalid_parameters():
    """takeBetween() with invalid parameters"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.take_between(0, 5)) == []
    assert (yield from queue.take_between(-1, 5)) == []
    assert (yield from queue.take_between(5, 2)) == []
    assert (yield from queue.size()) == 3


@testing.effect
@in_tx
def test_take_between_with_failed_queue_propagates_error():
    """takeBetween() with failed queue propagates error"""
    queue = yield from fx.TxQueue[int, str].bounded(10)
    yield from queue.fail("test error")
    ex = yield from queue.take_between(1, 5).exit()
    assert _failure(ex).find_error() == fx.Ok("test error")


@testing.effect
@in_tx
def test_take_between_with_closing_queue_returns_available_items():
    """takeBetween() with closing queue returns available items"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2])
    yield from queue.interrupt()
    assert (yield from queue.take_between(3, 5)) == [1, 2]
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_take_between_exact_minimum_and_maximum():
    """takeBetween() exact minimum and maximum"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.take_between(3, 3)) == [1, 2, 3]
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_take_between_returns_array_a_not_tuple():
    """takeBetween() returns Array<A> not tuple"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3, 4])
    items = yield from queue.take_between(2, 3)
    assert isinstance(items, list)
    assert items == [1, 2, 3]


@testing.effect
@in_tx
def test_peek_works_correctly():
    """peek works correctly"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer(42)
    assert (yield from queue.peek()) == 42
    assert (yield from queue.size()) == 1


# --- queue state --------------------------------------------------------------


@testing.effect
@in_tx
def test_size_returns_correct_count():
    """size returns correct count"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.size()) == 3


@testing.effect
@in_tx
def test_is_empty_and_is_non_empty_reflect_queue_contents():
    """isEmpty and isNonEmpty reflect queue contents"""
    queue = yield from fx.TxQueue[int].bounded(10)
    assert (yield from queue.is_empty()) is True
    assert (yield from queue.is_non_empty()) is False
    yield from queue.offer(1)
    assert (yield from queue.is_empty()) is False
    assert (yield from queue.is_non_empty()) is True


@testing.effect
@in_tx
def test_is_full_works_correctly_for_bounded_queue():
    """isFull works correctly for bounded queue"""
    queue = yield from fx.TxQueue[int].bounded(2)
    assert (yield from queue.is_full()) is False
    yield from queue.offer_all([1, 2])
    assert (yield from queue.is_full()) is True


@testing.effect
@in_tx
def test_is_full_returns_false_for_unbounded_queue():
    """isFull returns false for unbounded queue"""
    queue = yield from fx.TxQueue[int].unbounded()
    yield from queue.offer_all([1, 2, 3, 4, 5])
    assert (yield from queue.is_full()) is False


# --- clear --------------------------------------------------------------------


@testing.effect
@in_tx
def test_clear_removes_all_items_from_queue_and_returns_them():
    """clear removes all items from queue and returns them"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5])
    assert (yield from queue.size()) == 5
    assert (yield from queue.clear()) == [1, 2, 3, 4, 5]
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_clear_does_not_affect_queue_state():
    """clear does not affect queue state"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.clear()) == [1, 2, 3]
    assert (yield from queue.is_open()) is True
    assert (yield from queue.offer(42)) is True
    assert (yield from queue.size()) == 1


@testing.effect
@in_tx
def test_clear_works_on_empty_queue():
    """clear works on empty queue"""
    queue = yield from fx.TxQueue[int].bounded(10)
    assert (yield from queue.clear()) == []
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_empty()) is True


@testing.effect
@in_tx
def test_clear_works_on_queue_ended_with_done():
    """clear works on queue ended with Done"""
    queue = yield from fx.TxQueue[int, fx.Done].bounded(10)
    yield from queue.offer_all([1, 2, 3])
    yield from queue.end()
    yield from queue.take_all()
    assert (yield from queue.is_done()) is True
    assert (yield from queue.clear()) == []
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_done()) is True


# --- shutdown -----------------------------------------------------------------


@testing.effect
@in_tx
def test_shutdown_and_is_shutdown_work_correctly():
    """shutdown and isShutdown work correctly"""
    queue = yield from fx.TxQueue[int].bounded(10)
    assert (yield from queue.is_shutdown()) is False
    yield from queue.shutdown()
    assert (yield from queue.is_shutdown()) is True


@testing.effect
@in_tx
def test_offer_fails_after_shutdown():
    """offer fails after shutdown"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.shutdown()
    assert (yield from queue.offer(42)) is False


@testing.effect
@in_tx
def test_poll_returns_none_after_shutdown():
    """poll returns none after shutdown"""
    queue = yield from fx.TxQueue[int].bounded(10)
    yield from queue.offer(42)
    yield from queue.shutdown()
    assert (yield from queue.poll()) is None


# --- dropping and sliding strategies ------------------------------------------


@testing.effect
@in_tx
def test_dropping_queue_rejects_items_when_full():
    """dropping queue rejects items when full"""
    queue = yield from fx.TxQueue[int].dropping(2)
    assert (yield from queue.offer(1)) is True
    assert (yield from queue.offer(2)) is True
    assert (yield from queue.offer(3)) is False
    assert (yield from queue.size()) == 2


@testing.effect
@in_tx
def test_sliding_queue_evicts_old_items_when_full():
    """sliding queue evicts old items when full"""
    queue = yield from fx.TxQueue[int].sliding(2)
    yield from queue.offer(1)
    yield from queue.offer(2)
    assert (yield from queue.offer(3)) is True
    assert (yield from queue.size()) == 2
    assert (yield from queue.take()) == 2


# --- E-channel and exit signaling: type ergonomics ----------------------------


@testing.effect
@in_tx
def test_default_e_parameter_provides_clean_typing():
    """default E parameter provides clean typing"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer(42)
    assert (yield from queue.take()) == 42


@testing.effect
@in_tx
def test_explicit_e_parameter_works_correctly():
    """explicit E parameter works correctly"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.offer(42)
    assert (yield from queue.take()) == 42


# --- state transitions --------------------------------------------------------


def _states(queue: fx.TxDequeue[int, object]):
    open_ = yield from queue.is_open()
    closing = yield from queue.is_closing()
    done = yield from queue.is_done()
    return (open_, closing, done)


@testing.effect
@in_tx
def test_queue_starts_in_open_state():
    """queue starts in Open state"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from _states(queue)) == (True, False, False)


@testing.effect
@in_tx
def test_interrupt_transitions_open_done_when_empty():
    """interrupt() transitions Open → Done when empty"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.interrupt()) is True
    assert (yield from _states(queue)) == (False, False, True)


@testing.effect
@in_tx
def test_interrupt_transitions_open_closing_done_when_not_empty():
    """interrupt() transitions Open → Closing → Done when not empty"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    assert (yield from queue.interrupt()) is True
    assert (yield from _states(queue)) == (False, True, False)
    yield from queue.take_all()
    assert (yield from _states(queue)) == (False, False, True)


@testing.effect
@in_tx
def test_fail_transitions_directly_to_done():
    """fail() transitions directly to Done"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.offer(42)
    assert (yield from queue.fail("test error")) is True
    assert (yield from _states(queue)) == (False, False, True)


@testing.effect
@in_tx
def test_done_with_custom_cause_works_correctly():
    """done() with custom cause works correctly"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.fail_cause(fx.cause.interrupt())) is True
    assert (yield from queue.is_done()) is True


# --- completion operations ----------------------------------------------------


@testing.effect
@in_tx
def test_interrupt_completes_queue_successfully():
    """interrupt() completes queue successfully"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.interrupt()) is True
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_fail_completes_queue_with_error():
    """fail() completes queue with error"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    assert (yield from queue.fail("test error")) is True
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_multiple_interrupt_calls_return_false_after_first():
    """multiple interrupt() calls return false after first"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.interrupt()) is True
    assert (yield from queue.interrupt()) is False


@testing.effect
@in_tx
def test_operations_on_closed_queue_fail_appropriately():
    """operations on closed queue fail appropriately"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    assert (yield from queue.offer(42)) is False
    assert (yield from queue.poll()) is None


# --- awaitCompletion ----------------------------------------------------------


@testing.effect
@in_tx
def test_await_completion_succeeds_when_queue_is_interrupted():
    """awaitCompletion succeeds when queue is interrupted"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_succeeds_when_queue_fails():
    """awaitCompletion succeeds when queue fails"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail("connection lost")
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_on_already_completed_queue():
    """awaitCompletion on already completed queue"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_on_already_failed_queue():
    """awaitCompletion on already failed queue"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail("already failed")
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_with_custom_cause_die_succeeds():
    """awaitCompletion with custom Cause.die() succeeds"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail_cause(fx.cause.die(RuntimeError("system failure")))
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_with_custom_interrupt_cause_succeeds():
    """awaitCompletion with custom interrupt cause succeeds"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.fail_cause(fx.cause.interrupt(12345))
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_with_fail_cause_succeeds():
    """awaitCompletion with fail cause succeeds"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail("priority error")
    yield from queue.await_completion()


@testing.effect
@in_tx
def test_await_completion_concurrent_behavior_works():
    """awaitCompletion concurrent behavior works"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    yield from queue.await_completion()


# --- legacy compatibility -----------------------------------------------------


@testing.effect
@in_tx
def test_is_shutdown_works_as_alias_for_is_done():
    """isShutdown works as alias for isDone"""
    queue = yield from fx.TxQueue[int].bounded(5)
    assert (yield from queue.is_shutdown()) is (yield from queue.is_done()) is False
    yield from queue.shutdown()
    assert (yield from queue.is_shutdown()) is (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_shutdown_clears_queue_and_marks_as_done():
    """shutdown() clears queue and marks as done"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    yield from queue.shutdown()
    assert (yield from queue.size()) == 0
    assert (yield from queue.is_done()) is True


# --- error channel behavior ---------------------------------------------------


@testing.effect
@in_tx
def test_take_on_successfully_interrupted_queue_interrupts():
    """take() on successfully interrupted queue interrupts"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    assert isinstance((yield from queue.take().exit()), fx.Failure)


@testing.effect
@in_tx
def test_take_on_failed_queue_fails_with_error_directly():
    """take() on failed queue fails with error directly"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail("test error")
    assert (yield from queue.take().flip()) == "test error"


@testing.effect
@in_tx
def test_take_on_shutdown_queue_interrupts_success_exit():
    """take() on shutdown queue interrupts (success exit)"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.shutdown()
    assert isinstance((yield from queue.take().exit()), fx.Failure)


@testing.effect
@in_tx
def test_take_with_explicit_interrupt_cause_propagates_interruption():
    """take() with explicit interrupt cause propagates interruption"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail_cause(fx.cause.interrupt(123))
    ex = yield from queue.take().exit()
    assert _failure(ex).has_interrupts


@testing.effect
@in_tx
def test_take_with_custom_cause_fail_extracts_error_correctly():
    """take() with custom Cause.fail extracts error correctly"""
    queue = yield from fx.TxQueue[int, Exception].bounded(5)
    custom_error = Exception("custom failure")
    yield from queue.fail_cause(fx.cause.fail(custom_error))
    assert (yield from queue.take().flip()) is custom_error


@testing.effect
@in_tx
def test_take_with_cause_die_defect_propagates_defect():
    """take() with Cause.die (defect) propagates defect"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail_cause(fx.cause.die(RuntimeError("unexpected defect")))
    ex = yield from queue.take().exit()
    assert _failure(ex).has_dies


@testing.effect
@in_tx
def test_take_with_typed_error_cause_extracts_error_directly():
    """take() with typed error cause extracts error directly"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail_cause(fx.cause.fail("typed error"))
    assert (yield from queue.take().flip()) == "typed error"


@testing.effect
@in_tx
def test_peek_on_successfully_interrupted_queue_interrupts():
    """peek() on successfully interrupted queue interrupts"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.interrupt()
    assert isinstance((yield from queue.peek().exit()), fx.Failure)


@testing.effect
@in_tx
def test_peek_on_failed_queue_fails_with_error_directly():
    """peek() on failed queue fails with error directly"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.fail("peek error")
    assert (yield from queue.peek().flip()) == "peek error"


@testing.effect
@in_tx
def test_poll_on_failed_queue_returns_none():
    """poll() on failed queue returns none"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.offer(42)
    yield from queue.fail("poll error")
    assert (yield from queue.poll()) is None


@testing.effect
@in_tx
def test_take_n_with_partial_items_available_before_failure():
    """takeN() with partial items available before failure"""
    queue = yield from fx.TxQueue[int, str].bounded(5)
    yield from queue.offer_all([1, 2])
    yield from queue.fail("partial error")
    assert (yield from queue.take_n(3).flip()) == "partial error"


@testing.effect
@in_tx
def test_error_propagation_with_different_error_types():
    """error propagation with different error types"""
    queue1 = yield from fx.TxQueue[int, Exception].bounded(5)
    queue2 = yield from fx.TxQueue[int, dict[str, object]].bounded(5)
    custom_error = Exception("custom error")
    custom_object: dict[str, object] = {"code": 404, "message": "not found"}
    yield from queue1.fail(custom_error)
    yield from queue2.fail(custom_object)
    assert (yield from queue1.take().flip()) is custom_error
    assert (yield from queue2.take().flip()) == custom_object


@testing.effect
@in_tx
def test_closing_queue_allows_remaining_items_to_be_consumed():
    """closing queue allows remaining items to be consumed"""
    queue = yield from fx.TxQueue[int].bounded(5)
    yield from queue.offer_all([1, 2, 3])
    yield from queue.interrupt()
    assert (yield from queue.take()) == 1
    assert (yield from queue.take()) == 2
    assert (yield from queue.is_closing()) is True
    assert (yield from queue.take()) == 3
    assert (yield from queue.is_done()) is True


# --- Done and end -------------------------------------------------------------


@testing.effect
@in_tx
def test_end_signals_completion_with_done():
    """end() signals completion with Done"""
    queue = yield from fx.TxQueue[int, fx.Done].bounded(5)
    yield from queue.offer(1)
    yield from queue.offer(2)
    assert (yield from queue.end()) is True
    assert (yield from queue.is_closing()) is True
    yield from queue.take_all()
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_take_on_ended_queue_fails_with_done():
    """take() on ended queue fails with Done"""
    queue = yield from fx.TxQueue[int, fx.Done].bounded(5)
    yield from queue.offer(42)
    yield from queue.end()
    assert (yield from queue.take()) == 42
    error = yield from queue.take().flip()
    assert isinstance(error, fx.Done)
    assert error == fx.Done()


@testing.effect
@in_tx
def test_end_works_with_tx_enqueue_interface():
    """end() works with TxEnqueue interface"""
    queue = yield from fx.TxQueue[int, fx.Done].bounded(5)
    enqueue: fx.TxEnqueue[int, fx.Done] = queue
    yield from enqueue.offer(1)
    assert (yield from enqueue.end()) is True
    assert (yield from queue.is_closing()) is True
    yield from queue.take()
    assert (yield from queue.is_done()) is True


@testing.effect
@in_tx
def test_end_returns_false_if_queue_is_already_done():
    """end() returns false if queue is already done"""
    queue = yield from fx.TxQueue[int, fx.Done].bounded(5)
    assert (yield from queue.end()) is True
    assert (yield from queue.end()) is False
