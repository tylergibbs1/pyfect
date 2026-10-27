"""Ports of Effect's ``Queue.test.ts``.

Each test's docstring is the Effect test title. A resume in Effect runs the
woken fiber at once; in pyfect it goes through the scheduler, so a port
yields where Effect's fiber would already have run. Effect's
``Queue.await`` is ``await_done``; ``Stream.fromQueue`` is read with
``collect`` or a ``take_all`` loop. Effect's step budget counts differ from
pyfect's, so the ports that place a yield with ``MaxOpsBeforeYield`` sweep
every budget instead of using Effect's number.

Omitted, with the reason:

- "isEnqueue type guard", "isDequeue type guard": ``Enqueue`` and
  ``Dequeue`` are static protocols; ``isinstance(x, fx.Queue)`` is the
  guard. ``tests/type_checks.py`` pins the views' variance.
- "takeN and takeBetween normalize element counts before waiting": counts
  are ``int``, so there is no fraction or NaN to normalize; the
  zero-or-less half is ported.
- The six ``flush`` / ``flushUnsafe`` titles: pyfect wakes a waiting
  taker as an item arrives instead of in a coalesced scheduler task, so
  there is no pending release to flush ("flushUnsafe releases a waiting
  taker ...", "flush releases a waiting taker ...", "flushUnsafe coalesces
  scheduled releases ...", "flush is a no-op after shutdown", "flush keeps a
  buffered message ...", "flushUnsafe preserves later offers ...").
"""

from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cause import Die


def _settle() -> fx.Effect[object]:
    """Let forked fibers run until they park."""
    return fx.for_each(range(5), lambda _: fx.yield_now())


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _budget[A, E](eff: fx.Effect[A, E], ops: int) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))


@fx.fn
def _completes(fiber: fx.Fiber[Any, Any]):
    """Effect's ``assertCompletes``: yield until the fiber is done (at most
    200 times), interrupt it, and report whether it finished."""
    for _ in range(200):
        if fiber.unsafe_poll() is not None:
            break
        yield from fx.yield_now()
    done = fiber.unsafe_poll() is not None
    yield from fiber.interrupt()
    return done


# --- waiter registration after a yield ------------------------------------------------


@pytest.mark.parametrize("ops", range(1, 12))
@testing.effect
def test_offer_all_does_not_park_beside_available_capacity(ops: int):
    """offerAll does not park beside available capacity"""
    queue = yield from fx.Queue[int].bounded(1)
    yield from queue.offer(0)
    fiber = yield from _budget(queue.offer_all([1]), ops).fork(start_immediately=True)
    yield from queue.take()
    assert (yield from _completes(fiber)), "lost wake-up"


@pytest.mark.parametrize("ops", range(1, 12))
@testing.effect
def test_zero_capacity_offer_and_take_can_rendezvous(ops: int):
    """zero-capacity offer and take can rendezvous"""
    queue = yield from fx.Queue[int].bounded(0)
    offerer = yield from _budget(queue.offer(1), ops).fork(start_immediately=True)
    taker = yield from queue.take().fork(start_immediately=True)
    assert (yield from _completes(offerer)), "lost wake-up"
    assert (yield from _completes(taker)), "lost wake-up"


# --- views ---------------------------------------------------------------------------


@testing.effect
def test_as_enqueue_converts_to_write_only_interface():
    """asEnqueue converts to write-only interface"""
    queue = yield from fx.Queue[int].bounded(10)
    enqueue: fx.Enqueue[int, Never] = queue
    assert (yield from enqueue.offer(1)) is True
    assert isinstance(enqueue, fx.Queue)


@testing.effect
def test_as_dequeue_converts_to_read_only_interface():
    """asDequeue converts to read-only interface"""
    queue = yield from fx.Queue[int].bounded(10)
    yield from queue.offer(42)
    dequeue: fx.Dequeue[int, Never] = queue
    assert (yield from dequeue.take()) == 42
    assert isinstance(dequeue, fx.Queue)


# --- offers --------------------------------------------------------------------------


@testing.effect
def test_offer_all_does_not_retain_the_input_array():
    """offerAll does not retain the input array"""
    queue = yield from fx.Queue[int].unbounded()
    buffer = [1, 2, 3]
    yield from queue.offer_all(buffer)
    buffer[0] = 0
    assert (yield from queue.take_all()) == [1, 2, 3]


@testing.effect
def test_bounded_offer_all_waits_until_capacity_is_released():
    """bounded offerAll waits until capacity is released"""
    queue = yield from fx.Queue[int].bounded(2)
    fiber = yield from queue.offer_all([1, 2, 3, 4]).fork()
    yield from fx.yield_now()
    assert fiber.unsafe_poll() is None

    assert (yield from queue.take_all()) == [1, 2]
    yield from fx.yield_now()
    assert fiber.unsafe_poll() is not None

    assert (yield from queue.take_all()) == [3, 4]
    yield from fx.yield_now()
    assert fiber.unsafe_poll() == fx.Success([])


@testing.effect
def test_interrupting_a_suspended_offer_after_end_withdraws_its_message():
    """interrupting a suspended offer after end withdraws its message"""
    queue = yield from fx.Queue[int, fx.Done].bounded(1)
    yield from queue.offer(1)
    producer = yield from queue.offer(2).fork(start_immediately=True)
    assert producer.unsafe_poll() is None, "offer must be suspended before end"

    yield from queue.end()
    yield from producer.interrupt()

    assert (yield from queue.collect()) == [1]


@testing.effect
def test_interrupting_a_suspended_offer_all_after_end_completes_an_empty_queue():
    """interrupting a suspended offerAll after end completes an empty queue"""
    queue = yield from fx.Queue[int, fx.Done].bounded(0)
    producer = yield from queue.offer_all([1, 2]).fork(start_immediately=True)
    assert producer.unsafe_poll() is None, "offerAll must be suspended before end"

    yield from queue.end()
    awaiter = yield from queue.await_done().fork(start_immediately=True)
    assert awaiter.unsafe_poll() is None, "await must wait for the pending offer"

    yield from producer.interrupt()
    yield from awaiter.join()
    assert (yield from queue.take().exit()) == fx.exit.fail(fx.Done())


@testing.effect
def test_resuming_a_blocked_producer_does_not_enqueue_its_message_twice():
    """resuming a blocked producer does not enqueue its message twice"""
    queue = yield from fx.Queue[int].bounded(1)
    yield from queue.offer(0)

    @fx.gen
    def produce():
        yield from queue.offer(1)
        return (yield from queue.take())

    producer = yield from produce.fork(start_immediately=True)
    first = yield from queue.take()
    second = yield from producer.join()
    remaining = yield from queue.clear()
    yield from queue.shutdown()

    assert [first, second] == [0, 1]
    assert remaining == []


def _offer_one(queue: fx.Queue[int], method: str, item: int) -> fx.Effect[object]:
    return queue.offer(item) if method == "offer" else queue.offer_all([item])


@pytest.mark.parametrize("take", ["take", "takeAll", "clear"])
@pytest.mark.parametrize("method", ["offer", "offerAll"])
@testing.effect
def test_zero_capacity_take_reserves_the_message_before_resuming_method(method: str, take: str):
    """zero-capacity ${take} reserves the message before resuming ${method}"""
    queue = yield from fx.Queue[int].bounded(0)

    @fx.gen
    def produce():
        yield from _offer_one(queue, method, 1)
        return (yield from queue.take())

    producer = yield from produce.fork(start_immediately=True)
    match take:
        case "take":
            first = [(yield from queue.take())]
        case "takeAll":
            first = yield from queue.take_all()
        case _:
            first = yield from queue.clear()
    producer_exit = producer.unsafe_poll()
    yield from queue.shutdown()

    assert (first, producer_exit) == ([1], None)


@pytest.mark.parametrize("method", ["offer", "offerAll"])
@testing.effect
def test_resuming_method_can_shut_down_the_queue_with_another_blocked_producer(method: str):
    """resuming ${method} can shut down the queue with another blocked producer"""
    queue = yield from fx.Queue[int].bounded(1)
    yield from queue.offer(0)

    @fx.gen
    def produce():
        yield from _offer_one(queue, method, 1)
        yield from queue.shutdown()

    producer = yield from produce.fork(start_immediately=True)
    pending = yield from queue.offer(2).fork(start_immediately=True)
    assert producer.unsafe_poll() is None, "first producer must be suspended"
    assert pending.unsafe_poll() is None, "second producer must be suspended"

    ex = yield from queue.take().exit()
    yield from producer.join()
    offered = yield from pending.join()

    assert (ex, offered) == (fx.Success(0), False)


@pytest.mark.parametrize("method", ["offer", "offerAll"])
@testing.effect
def test_resuming_method_does_not_overfill_the_queue_with_reentrant_offers(method: str):
    """resuming ${method} does not overfill the queue with reentrant offers"""
    queue = yield from fx.Queue[int].bounded(2)
    yield from queue.offer_all([0, 1])

    @fx.gen
    def produce():
        yield from _offer_one(queue, method, 2)
        yield from queue.offer(3)

    yield from produce.fork(start_immediately=True)
    yield from queue.offer(4).fork(start_immediately=True)

    first = yield from queue.take_all()
    size = queue.unsafe_size()
    yield from queue.shutdown()

    assert first == [0, 1]
    assert size <= 2


# --- batch takes ---------------------------------------------------------------------


@testing.effect
def test_take_n():
    """takeN"""
    queue = yield from fx.Queue[int].unbounded()
    yield from queue.offer_all([1, 2, 3, 4]).fork()
    a = yield from queue.take_n(2)
    b = yield from queue.take_n(2)
    assert a == [1, 2]
    assert b == [3, 4]


@testing.effect
def test_take_n_on_a_partial_batch_does_not_wake_its_taker():
    """takeN on a partial batch does not wake its taker"""
    # Effect watches its taker set; pyfect's observable form: the partial
    # batch leaves the taker waiting, and the wake-up goes to a plain take
    # parked behind it instead of being spent on the batch.
    queue = yield from fx.Queue[int].unbounded()
    batch = yield from queue.take_n(2).fork(start_immediately=True)
    single = yield from queue.take().fork(start_immediately=True)

    assert queue.unsafe_offer(1)
    yield from _settle()

    assert batch.unsafe_poll() is None
    assert single.unsafe_poll() == fx.Success(1)
    yield from queue.offer_all([2, 3])
    assert (yield from batch.join()) == [2, 3]


_RECEIVES: list[tuple[str, Callable[[fx.Queue[int]], fx.Effect[object]]]] = [
    ("take", lambda q: q.take()),
    ("takeN", lambda q: q.take_n(1)),
    ("takeAll", lambda q: q.take_all()),
    ("takeBetween", lambda q: q.take_between(1, 5)),
    ("peek", lambda q: q.peek()),
]


@pytest.mark.parametrize(("name", "receive"), _RECEIVES, ids=[n for n, _ in _RECEIVES])
@testing.effect
def test_name_does_not_miss_an_offer_during_the_check_to_registration_yield(
    name: str, receive: Callable[[fx.Queue[int]], fx.Effect[object]]
):
    """${name} does not miss an offer during the check-to-registration yield"""
    for ops in range(1, 16):
        queue = yield from fx.Queue[int].unbounded()
        pad: fx.Effect[None] = fx.void
        for _ in range(5):
            pad = pad.and_then(fx.void)
        taker = yield from _budget(pad.and_then(receive(queue)), ops).fork()
        offerer = yield from _budget(queue.offer(1), ops).fork()
        for _ in range(20):
            yield from fx.yield_now()

        ex = taker.unsafe_poll()
        size = yield from queue.size()
        yield from queue.shutdown()
        assert offerer.unsafe_poll() == fx.Success(True), ops
        assert ex == fx.Success(1 if name in ("take", "peek") else [1]), ops
        assert size == (1 if name == "peek" else 0), ops


@testing.effect
def test_take_n_and_take_between_keep_waiting_on_a_partial_batch():
    """takeN and takeBetween keep waiting on a partial batch"""
    take_n_queue = yield from fx.Queue[int].unbounded()
    yield from take_n_queue.offer(1)
    take_n = yield from take_n_queue.take_n(3).fork()

    take_between_queue = yield from fx.Queue[int].unbounded()
    yield from take_between_queue.offer(1)
    take_between = yield from take_between_queue.take_between(2, 5).fork()

    for _ in range(20):
        yield from fx.yield_now()
    assert take_n.unsafe_poll() is None
    assert take_between.unsafe_poll() is None

    yield from take_n_queue.offer_all([2, 3])
    yield from take_between_queue.offer_all([2, 3])
    assert (yield from take_n.await_exit()) == fx.Success([1, 2, 3])
    assert (yield from take_between.await_exit()) == fx.Success([1, 2, 3])


@testing.effect
def test_take_n_drains_an_insufficient_batch_after_end():
    """takeN drains an insufficient batch after end"""
    queue = yield from fx.Queue[int, fx.Done].unbounded()
    yield from queue.offer_all([1, 2])
    yield from queue.end()

    assert (yield from queue.take_n(5)) == [1, 2]
    assert (yield from queue.offer(3)) is False
    assert (yield from queue.take_n(5).exit()) == fx.exit.fail(fx.Done())


@testing.effect
def test_take_between_drains_a_waiting_batch_on_failure():
    """takeBetween drains a waiting batch on failure"""
    queue = yield from fx.Queue[int, str].unbounded()
    yield from queue.offer_all([1, 2])
    taker = yield from queue.take_between(5, 8).fork(start_immediately=True)
    assert taker.unsafe_poll() is None

    yield from queue.fail("boom")
    assert (yield from taker.join()) == [1, 2]
    assert (yield from queue.take_between(5, 8).exit()) == fx.exit.fail("boom")


@testing.effect
def test_take_n_drains_on_failure_between_the_batch_check_and_waiter_registration():
    """takeN drains on failure between the batch check and waiter registration"""
    for ops in range(1, 16):
        queue = yield from fx.Queue[int, str].unbounded()
        yield from queue.offer_all([1, 2])
        pad = fx.void.and_then(fx.void)
        taker = yield from _budget(pad.and_then(queue.take_n(5).exit()), ops).fork()
        yield from _budget(queue.fail("boom"), ops).fork()

        assert (yield from taker.join()) == fx.Success([1, 2]), ops
        assert (yield from queue.take_n(5).exit()) == fx.exit.fail("boom"), ops


@testing.effect
def test_take_n_ending_at_an_offer_all_boundary_keeps_the_next_message():
    """takeN ending at an offerAll boundary keeps the next message"""
    queue = yield from fx.Queue[int].unbounded()
    yield from queue.offer_all([1, 2])
    yield from queue.offer_all([3])
    assert (yield from queue.take_n(2)) == [1, 2]
    assert (yield from queue.size()) == 1
    assert (yield from queue.peek()) == 3
    assert (yield from queue.take()) == 3
    yield from queue.offer(99)
    assert (yield from queue.take()) == 99
    assert (yield from queue.size()) == 0


@testing.effect
def test_take_n_and_take_between_take_nothing_for_counts_of_zero_or_less():
    """takeN and takeBetween normalize element counts before waiting"""
    queue = yield from fx.Queue[int].unbounded()
    yield from queue.offer(1)
    assert (yield from queue.take_n(0)) == []
    assert (yield from queue.take_n(-3)) == []
    assert (yield from queue.take_between(0, 2)) == []
    assert (yield from queue.take_between(1, 0)) == []
    assert (yield from queue.take_all()) == [1]


@testing.effect
def test_collect_does_not_duplicate_messages():
    """collect does not duplicate messages"""
    queue = yield from fx.Queue[dict[str, int], fx.Done].bounded(10)
    yield from queue.offer({"id": 0})
    yield from queue.end()
    assert (yield from queue.collect()) == [{"id": 0}]


# --- strategies ----------------------------------------------------------------------


@testing.effect
def test_offer_dropping():
    """offer dropping"""
    queue = yield from fx.Queue[int].make(2, strategy="dropping")
    assert (yield from queue.offer_all([1, 2, 3, 4])) == [3, 4]
    assert (yield from queue.offer(5)) is False
    assert (yield from queue.take_all()) == [1, 2]


@testing.effect
def test_offer_sliding():
    """offer sliding"""
    queue = yield from fx.Queue[int].make(2, strategy="sliding")
    assert (yield from queue.offer_all([1, 2, 3, 4])) == []
    assert (yield from queue.offer(5)) is True
    assert (yield from queue.take_all()) == [4, 5]


# --- interruption --------------------------------------------------------------------


@testing.effect
def test_offer_all_can_be_interrupted():
    """offerAll can be interrupted"""
    queue = yield from fx.Queue[int].bounded(2)
    fiber = yield from queue.offer_all([1, 2, 3, 4]).fork()

    yield from fx.yield_now()
    yield from fiber.interrupt()
    yield from fx.yield_now()

    assert (yield from queue.take_all()) == [1, 2]
    yield from queue.offer(5)
    yield from fx.yield_now()
    assert (yield from queue.take_all()) == [5]


@testing.effect
def test_take_can_be_interrupted_without_losing_offers():
    """take can be interrupted without losing offers"""
    queue = yield from fx.Queue[int].unbounded()
    interrupted = yield from queue.take().fork()

    yield from fx.yield_now()
    yield from interrupted.interrupt()
    assert _interrupted((yield from interrupted.await_exit()))

    live = yield from queue.take().fork()
    yield from fx.yield_now()
    yield from queue.offer(1)
    assert (yield from live.join()) == 1


_DEQUEUES: list[tuple[str, Callable[[fx.Queue[int]], fx.Effect[list[int]]], bool]] = [
    ("take", lambda q: q.take().map(lambda v: [v]), True),
    ("takeAll", lambda q: q.take_all(), True),
    ("takeN", lambda q: q.take_n(1), True),
    ("takeBetween", lambda q: q.take_between(1, 2), True),
    ("poll", lambda q: q.poll().map(lambda o: [] if o is None else [o.value]), False),
    ("clear", lambda q: q.clear(), False),
]

_DEQUEUE_CASES = [
    (name, dequeue, capacity, offer_first)
    for name, dequeue, waits in _DEQUEUES
    for capacity in (None, 0)
    for offer_first in (True, False)
    if waits or offer_first
]


@pytest.mark.parametrize(
    ("name", "dequeue", "capacity", "offer_first"),
    _DEQUEUE_CASES,
    ids=[f"{n}-capacity={c}-offer_first={o}" for n, _, c, o in _DEQUEUE_CASES],
)
@testing.effect
def test_name_interrupted_at_a_yield_keeps_its_message(
    name: str,
    dequeue: Callable[[fx.Queue[int]], fx.Effect[list[int]]],
    capacity: int | None,
    offer_first: bool,
):
    """${name} interrupted at a yield keeps its message, capacity=$capacity
    offerFirst=$offerFirst"""
    # Effect interrupts the taker at its n-th yield check; pyfect places a
    # yield at every step with the op budget and interrupts after ``delay``
    # turns.
    for ops in range(1, 16):
        for delay in range(4):
            queue = yield from fx.Queue[int].make(capacity)
            offer = queue.offer(1).fork(start_immediately=True)
            if offer_first:
                yield from offer
            taker = yield from _budget(dequeue(queue), ops).fork(start_immediately=True)
            if not offer_first:
                yield from offer
            for _ in range(delay):
                yield from fx.yield_now()
            yield from taker.interrupt()
            ex = yield from taker.await_exit()
            taken = ex.value if isinstance(ex, fx.Success) else []
            yield from _settle()
            rest = yield from queue.clear()
            assert [*taken, *rest] == [1], (name, ops, delay)


# --- finishing -----------------------------------------------------------------------


@testing.effect
def test_done_completes_takes():
    """done completes takes"""
    queue = yield from fx.Queue[int, fx.Done].bounded(2)
    fiber = yield from queue.take_all().fork()
    yield from fx.yield_now()
    yield from queue.end()
    assert (yield from fiber.await_exit()) == fx.exit.fail(fx.Done())


@testing.effect
def test_end():
    """end"""
    queue = yield from fx.Queue[int, fx.Done].bounded(2)
    yield from queue.offer_all([1, 2, 3, 4]).fork()
    yield from queue.offer_all([5, 6, 7, 8]).fork()
    yield from queue.offer(9).fork()
    yield from queue.end().fork()
    assert (yield from queue.collect()) == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert (yield from queue.await_done()) is None
    assert (yield from queue.offer(10)) is False


@testing.effect
def test_end_with_take():
    """end with take"""
    queue = yield from fx.Queue[int, fx.Done].bounded(2)
    yield from queue.offer_all([1, 2]).fork()
    yield from queue.offer(3).fork()
    yield from queue.end().fork()
    assert (yield from queue.take()) == 1
    assert (yield from queue.take()) == 2
    assert (yield from queue.take()) == 3
    assert isinstance((yield from queue.take().flip()), fx.Done)
    assert (yield from queue.await_done()) is None
    assert (yield from queue.offer(10)) is False


@testing.effect
def test_interrupt_allows_draining():
    """interrupt allows draining"""
    queue = yield from fx.Queue[int].bounded(10)
    yield from queue.offer_all([1, 2, 3, 4, 5])

    assert (yield from queue.interrupt()) is True
    assert (yield from queue.offer(6)) is False
    for expected in [1, 2, 3, 4, 5]:
        assert (yield from queue.take()) == expected

    assert _interrupted((yield from queue.take().exit()))


@testing.effect
def test_poll_returns_option_for_non_blocking_take():
    """poll returns Option for non-blocking take"""
    queue = yield from fx.Queue[int].bounded(10)
    assert (yield from queue.poll()) is None
    yield from queue.offer(42)
    assert (yield from queue.poll()) == fx.Some(42)
    assert (yield from queue.poll()) is None


@testing.effect
def test_peek_views_item_without_removing_it():
    """peek views item without removing it"""
    queue = yield from fx.Queue[int].bounded(10)
    yield from queue.offer(42)
    assert (yield from queue.peek()) == 42
    assert (yield from queue.size()) == 1
    assert (yield from queue.peek()) == 42
    assert (yield from queue.take()) == 42
    assert (yield from queue.size()) == 0


@testing.effect
def test_fail_drains_buffered_values_before_failing_takers():
    """fail drains buffered values before failing takers"""
    queue = yield from fx.Queue[int, str].bounded(2)
    yield from queue.offer_all([1, 2, 3, 4]).fork()
    yield from queue.offer(5).fork()
    yield from queue.fail("boom").fork()
    take_all = queue.take_all()
    assert (yield from take_all) == [1, 2]
    assert (yield from take_all) == [3, 4]
    assert (yield from queue.take_all()) == [5]
    assert (yield from queue.take_all().flip()) == "boom"
    assert (yield from queue.await_done().flip()) == "boom"
    assert (yield from queue.offer(6)) is False


@testing.effect
def test_shutdown():
    """shutdown"""
    queue = yield from fx.Queue[int].bounded(2)
    yield from queue.offer_all([1, 2, 3, 4]).fork()
    yield from queue.offer_all([5, 6, 7, 8]).fork()
    yield from queue.shutdown().fork()

    @fx.gen
    def drain():
        while True:
            yield from queue.take_all()

    assert _interrupted((yield from drain.exit()))
    assert _interrupted((yield from queue.await_done().exit()))
    assert (yield from queue.offer(10)) is False


@testing.effect
def test_shutdown_unsafe_interrupts_waiting_takers_synchronously():
    """shutdownUnsafe interrupts waiting takers synchronously"""
    queue = yield from fx.Queue[int].unbounded()
    taker = yield from queue.take().fork(start_immediately=True)

    queue.unsafe_shutdown()
    # The taker resumes through the scheduler, so it finishes on its next turn.
    yield from fx.yield_now()

    assert _interrupted(taker.unsafe_poll())


@testing.effect
def test_shutdown_unsafe_clears_buffered_messages_and_settles_pending_offers_synchronously():
    """shutdownUnsafe clears buffered messages and settles pending offers synchronously"""
    queue = yield from fx.Queue[int].bounded(1)
    queue.unsafe_offer(1)
    offerer = yield from queue.offer(2).fork(start_immediately=True)

    queue.unsafe_shutdown()
    yield from fx.yield_now()

    assert queue.unsafe_size() == 0
    assert offerer.unsafe_poll() == fx.Success(False)


@testing.effect
def test_shutdown_unsafe_resumes_batch_offers_with_their_unaccepted_suffix():
    """shutdownUnsafe resumes batch offers with their unaccepted suffix"""
    queue = yield from fx.Queue[int].bounded(1)
    producer = yield from queue.offer_all([1, 2, 3]).fork(start_immediately=True)
    assert (yield from queue.take()) == 1

    queue.unsafe_shutdown()
    yield from fx.yield_now()

    assert producer.unsafe_poll() == fx.Success([3])


@testing.effect
def test_shutdown_unsafe_returns_true_and_preserves_an_existing_failure():
    """shutdownUnsafe returns true and preserves an existing failure"""
    queue = yield from fx.Queue[int, str].unbounded()
    queue.unsafe_offer(1)
    queue.unsafe_fail_cause(fx.cause.fail("boom"))

    assert queue.unsafe_shutdown()
    assert (yield from queue.take().flip()) == "boom"


@testing.effect
def test_shutdown_unsafe_returns_false_when_already_shut_down():
    """shutdownUnsafe returns false when already shut down"""
    queue = yield from fx.Queue[int].unbounded()
    assert queue.unsafe_shutdown()
    assert not queue.unsafe_shutdown()
    assert _interrupted((yield from queue.await_done().exit()))


@testing.effect
def test_shutdown_returns_false_and_preserves_a_completed_queues_failure():
    """shutdown returns false and preserves a completed queue's failure"""
    queue = yield from fx.Queue[int, str].unbounded()
    queue.unsafe_fail_cause(fx.cause.fail("boom"))

    assert (yield from queue.shutdown()) is False
    assert (yield from queue.take().flip()) == "boom"


@testing.effect
def test_fail_doesnt_drop_items():
    """fail doesnt drop items"""
    queue = yield from fx.Queue[int, str].bounded(2)
    yield from queue.offer_all([1, 2, 3, 4]).fork()
    yield from queue.offer(5).fork()
    yield from queue.fail("boom").fork()
    items: list[int] = []

    @fx.gen
    def drain():
        while True:
            items.extend((yield from queue.take_all()))

    error = yield from drain.flip()
    assert items == [1, 2, 3, 4, 5]
    assert error == "boom"


@testing.effect
def test_await_waits_for_no_items():
    """await waits for no items"""
    queue = yield from fx.Queue[int, fx.Done].unbounded()
    fiber = yield from queue.await_done().fork()
    yield from fx.yield_now()
    yield from queue.offer(1)
    yield from queue.end()

    yield from fx.yield_now()
    assert fiber.unsafe_poll() is None
    assert (yield from queue.take_all()) == [1]
    yield from queue.take_all().flip()
    yield from fx.yield_now()
    assert fiber.unsafe_poll() is not None


@testing.effect
def test_end_preserves_done_for_take_and_excludes_it_from_await():
    """end preserves Done for take and excludes it from await"""
    queue = yield from fx.Queue[Never, fx.Done].unbounded()
    take_fiber = yield from queue.take().fork()
    await_fiber = yield from queue.await_done().fork()
    yield from fx.yield_now()
    yield from queue.end()

    assert (yield from take_fiber.await_exit()) == fx.exit.fail(fx.Done())
    assert (yield from await_fiber.join()) is None


@testing.effect
def test_await_preserves_non_done_failures():
    """await preserves non-Done failures"""
    queue = yield from fx.Queue[int, str].unbounded()
    fiber = yield from queue.await_done().exit().fork()
    yield from fx.yield_now()
    yield from queue.fail("boom")

    assert (yield from fiber.join()) == fx.exit.fail("boom")


# --- rendezvous ----------------------------------------------------------------------


@testing.effect
def test_bounded_0_capacity():
    """bounded 0 capacity"""
    queue = yield from fx.Queue[int].bounded(0)
    yield from queue.offer(1).fork()
    assert (yield from queue.take()) == 1
    fiber = yield from queue.take().fork()
    yield from queue.offer(2)
    assert (yield from fiber.join()) == 2


@testing.effect
def test_zero_capacity_take_all_consumes_buffered_messages_before_pending_offers():
    """zero-capacity takeAll consumes buffered messages before pending offers"""
    queue = yield from fx.Queue[int].bounded(0)
    waiting = yield from queue.take().fork(start_immediately=True)
    producer = yield from queue.offer_all([1, 2]).fork(start_immediately=True)

    batch = yield from queue.take_all()
    nxt = yield from waiting.join()
    yield from producer.join()

    assert batch == [1]
    assert nxt == 2


@testing.effect
def test_clear_preserves_a_defect_merged_with_done():
    """clear preserves a defect merged with Done"""
    queue = yield from fx.Queue[int, fx.Done].unbounded()
    boom = RuntimeError("finalizer boom")
    yield from queue.fail_cause(fx.cause.fail(fx.Done()) + fx.cause.die(boom))

    ex = yield from queue.clear().exit()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Die(boom),)


@testing.effect
def test_zero_capacity_offer_all_drains_in_order_and_completes_a_closing_queue():
    """zero-capacity offerAll drains in order and completes a closing queue"""
    queue = yield from fx.Queue[int, fx.Done].bounded(0)
    producer = yield from queue.offer_all([1, 2, 3]).fork(start_immediately=True)

    first = yield from queue.take_all()
    yield from queue.end()
    second = yield from queue.clear()
    third = yield from queue.poll()
    yield from fx.yield_now()
    producer_exit = producer.unsafe_poll()
    done = yield from queue.await_done().exit()

    assert first == [1]
    assert second == [2]
    assert third == fx.Some(3)
    assert producer_exit == fx.Success([])
    assert done == fx.Success(None)
