"""Queue lifecycle: Open -> Closing(cause) -> Done(cause), rendezvous, batch offers."""

from typing import Never

import pytest

import pyfect as fx
from pyfect.testing import run_test as run
from pyfect.testing import run_test_exit as run_exit


def _settle():
    """Let forked fibers run until they park."""
    return fx.for_each(range(5), lambda _: fx.yield_now())


def test_end_keeps_an_offer_parked_on_a_full_queue():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].bounded(1)
        yield from q.offer(1)
        pending = yield from q.offer(2).fork()
        yield from _settle()
        yield from q.end()
        a = yield from q.take()
        accepted = yield from pending.join()
        b = yield from q.take()
        c = yield from q.take().exit()
        return a, accepted, b, c

    a, accepted, b, c = run(program.pipe(fx.catch_tag(fx.Done, fx.die)))
    assert (a, accepted, b) == (1, True, 2)
    assert isinstance(c, fx.Failure) and isinstance(c.cause.failures[0], fx.Done)


def test_fail_drains_buffered_values_before_failing_takers():
    """Effect: Queue.test.ts 'fail drains buffered values before failing takers'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int, str].bounded(2)
        yield from q.offer_all([1, 2, 3, 4]).fork()
        yield from q.offer(5).fork()
        yield from q.fail("boom").fork()
        yield from _settle()
        batches: list[list[int]] = []
        for _ in range(3):
            batches.append((yield from q.take_all()))  # noqa: PERF401
        error = yield from q.take_all().exit()
        late = yield from q.offer(6)
        return batches, error, late

    ex = run_exit(program)
    assert isinstance(ex, fx.Success)
    batches, error, late = ex.value
    assert batches == [[1, 2], [3, 4], [5]]
    assert isinstance(error, fx.Failure) and error.cause.failures == ("boom",)
    assert late is False


def test_end_delivers_every_pending_offer():
    """Effect: Queue.test.ts 'end' and 'fail doesnt drop items'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].bounded(2)
        yield from q.offer_all([1, 2, 3, 4]).fork()
        yield from q.offer_all([5, 6, 7, 8]).fork()
        yield from q.offer(9).fork()
        yield from q.end().fork()
        yield from _settle()
        out: list[int] = []
        while True:
            batch = yield from q.take_all().exit()
            if isinstance(batch, fx.Failure):
                return out, (yield from q.offer(10))
            out.extend(batch.value)

    assert run(program) == ([1, 2, 3, 4, 5, 6, 7, 8, 9], False)


def test_end_on_an_empty_queue_is_done_at_once():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].unbounded()
        first = yield from q.end()
        second = yield from q.end()
        return first, second, (yield from q.take().exit())

    first, second, taken = run(program)
    assert (first, second) == (True, False)
    assert isinstance(taken, fx.Failure)


def test_interrupting_the_last_parked_offer_of_a_closing_queue_finishes_it():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].bounded(0)
        offer = yield from q.offer(1).fork()
        yield from _settle()
        yield from q.end()
        yield from offer.interrupt()
        return (yield from q.take().exit())

    taken = run(program)
    assert isinstance(taken, fx.Failure) and isinstance(taken.cause.failures[0], fx.Done)


def test_interrupting_a_suspended_offer_after_end_withdraws_its_message():
    """Effect: Queue.test.ts 'interrupting a suspended offer after end withdraws its
    message'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].bounded(1)
        yield from q.offer(1)
        producer = yield from q.offer(2).fork()
        yield from _settle()
        yield from q.end()
        yield from producer.interrupt()
        first = yield from q.take()
        return first, (yield from q.take().exit())

    first, rest = run(program.pipe(fx.catch_tag(fx.Done, fx.die)))
    assert first == 1
    assert isinstance(rest, fx.Failure) and isinstance(rest.cause.failures[0], fx.Done)


def test_offer_all_can_be_interrupted():
    """Effect: Queue.test.ts 'offerAll can be interrupted'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(2)
        producer = yield from q.offer_all([1, 2, 3, 4]).fork()
        yield from _settle()
        yield from producer.interrupt()
        first = yield from q.take_all()
        yield from q.offer(5)
        return first, (yield from q.take_all())

    assert run(program) == ([1, 2], [5])


# --- rendezvous ---------------------------------------------------------------------


def test_bounded_zero_capacity():
    """Effect: Queue.test.ts 'bounded 0 capacity'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(0)
        yield from q.offer(1).fork()
        first = yield from q.take()
        taker = yield from q.take().fork()
        yield from _settle()
        yield from q.offer(2)
        return first, (yield from taker.join())

    assert run(program) == (1, 2)


def test_zero_capacity_offer_waits_for_a_taker():
    """Effect: Queue.test.ts 'zero-capacity offer and take can rendezvous'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(0)
        finished: list[bool] = []
        offerer = yield from q.offer(1).tap(lambda ok: fx.sync(lambda: finished.append(ok))).fork()
        yield from _settle()
        before = list(finished)
        taken = yield from q.take()
        return before, taken, (yield from offerer.join())

    assert run(program) == ([], 1, True)


def test_zero_capacity_take_all_consumes_buffered_messages_before_pending_offers():
    """Effect: Queue.test.ts 'zero-capacity takeAll consumes buffered messages before
    pending offers'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(0)
        waiting = yield from q.take().fork()
        yield from _settle()
        producer = yield from q.offer_all([1, 2]).fork()
        yield from fx.yield_now()
        batch = yield from q.take_all()
        nxt = yield from waiting.join()
        rest = yield from producer.join()
        return batch, nxt, rest

    assert run(program) == ([1], 2, [])


def test_negative_capacity_is_rejected():
    ex = run_exit(fx.Queue[int].bounded(-1))
    assert isinstance(ex, fx.Failure) and isinstance(ex.cause.defects[0], ValueError)


# --- offer_all, shutdown, take_up_to ------------------------------------------------


def test_offer_all_returns_what_a_dropping_queue_rejected():
    """Effect: Queue.test.ts 'offer dropping'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].dropping(2)
        remaining = yield from q.offer_all([1, 2, 3, 4])
        return remaining, (yield from q.offer(5)), (yield from q.take_all())

    assert run(program) == ([3, 4], False, [1, 2])


def test_offer_all_on_a_sliding_queue_keeps_the_newest():
    """Effect: Queue.test.ts 'offer sliding'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].sliding(2)
        remaining = yield from q.offer_all([1, 2, 3, 4])
        return remaining, (yield from q.offer(5)), (yield from q.take_all())

    assert run(program) == ([], True, [4, 5])


def test_offer_all_on_a_finished_queue_returns_every_item():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].unbounded()
        yield from q.end()
        return (yield from q.offer_all([1, 2]))

    assert run(program) == [1, 2]


def test_offer_all_admits_what_fits_in_one_step():
    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(3)
        yield from q.offer(0)
        producer = yield from q.offer_all([1, 2, 3, 4]).fork()
        yield from _settle()
        size_while_parked = yield from q.size
        yield from q.take_all()
        rest = yield from producer.join()
        return size_while_parked, rest, (yield from q.take_all())

    assert run(program) == (3, [], [3, 4])


def test_shutdown_returns_whether_it_finished_the_queue():
    """Effect: Queue.test.ts 'shutdownUnsafe returns false when already shut down'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].unbounded()
        return (yield from q.shutdown()), (yield from q.shutdown())

    assert run(program) == (True, False)


def test_shutdown_preserves_a_closing_queues_failure():
    """Effect: Queue.test.ts 'shutdownUnsafe returns true and preserves an existing
    failure'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int, str].unbounded()
        yield from q.offer(1)
        yield from q.fail("boom")
        shut = yield from q.shutdown()
        return shut, (yield from q.take().exit())

    shut, taken = run(program)
    assert shut is True
    assert isinstance(taken, fx.Failure) and taken.cause.failures == ("boom",)


def test_shutdown_settles_parked_offers_with_what_was_not_accepted():
    """Effect: Queue.test.ts 'shutdownUnsafe resumes batch offers with their unaccepted
    suffix' and 'shutdownUnsafe clears buffered messages and settles pending offers'."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].bounded(1)
        batch = yield from q.offer_all([1, 2, 3]).fork()
        yield from _settle()
        first = yield from q.take()
        single = yield from q.offer(4).fork()
        yield from _settle()
        yield from q.shutdown()
        return first, (yield from batch.join()), (yield from single.join()), (yield from q.size)

    assert run(program) == (1, [3], False, 0)


def test_take_up_to_zero_returns_empty_without_waiting():
    @fx.gen
    def program():
        q = yield from fx.Queue[int].unbounded()
        return (yield from q.take_up_to(0)), (yield from q.take_up_to(-1))

    assert run(program) == ([], [])


def test_take_up_to_zero_still_reports_a_finished_queue():
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].unbounded()
        yield from q.end()
        return (yield from q.take_up_to(0).exit())

    ex = run(program)
    assert isinstance(ex, fx.Failure)


@pytest.mark.parametrize("capacity", [0, 1, 3])
def test_many_producers_and_consumers_lose_nothing(capacity: int):
    @fx.gen
    def program():
        q = yield from fx.Queue[int, fx.Done].bounded(capacity)
        producers = yield from fx.for_each(
            range(4),
            lambda p: fx.for_each(range(10), lambda i: q.offer(p * 10 + i)).fork(),
        )
        out: list[int] = []

        @fx.gen
        def consume():
            while True:
                out.append((yield from q.take()))

        consumers = yield from fx.for_each(range(3), lambda _: consume.exit().fork())
        yield from fx.for_each(producers, lambda f: f.join())
        yield from q.end()
        yield from fx.for_each(consumers, lambda f: f.join())
        return sorted(out)

    assert run(program) == list(range(40))


def _dequeue(name: str, q: fx.Queue[int, fx.Done]) -> fx.Effect[list[int], fx.Done]:
    match name:
        case "take":
            return q.take().map(lambda v: [v])
        case "take_all":
            return q.take_all()
        case _:
            return q.take_up_to(2)


@pytest.mark.parametrize("dequeue", ["take", "take_all", "take_up_to"])
@pytest.mark.parametrize("capacity", [None, 0])
@pytest.mark.parametrize("offer_first", [True, False])
def test_a_take_interrupted_at_a_yield_keeps_its_message(
    dequeue: str, capacity: int | None, offer_first: bool
):
    """Effect: Queue.test.ts '${name} interrupted at a yield keeps its message'."""

    def program(delay: int) -> fx.Effect[tuple[list[int], fx.Exit[bool, Never]]]:
        @fx.gen
        def go():
            q = yield from (
                fx.Queue[int, fx.Done].unbounded()
                if capacity is None
                else fx.Queue[int, fx.Done].bounded(capacity)
            )
            offerer = None
            if offer_first:
                offerer = yield from q.offer(1).fork()
            taker = yield from _dequeue(dequeue, q).fork()
            if offerer is None:
                offerer = yield from q.offer(1).fork()
            yield from fx.for_each(range(delay), lambda _: fx.yield_now())
            yield from taker.interrupt()
            ex = yield from taker.await_exit()
            out = list(ex.value) if isinstance(ex, fx.Success) else []
            yield from _settle()
            yield from q.end()
            while isinstance(item := (yield from q.take().exit()), fx.Success):
                out.append(item.value)
            return out, (yield from offerer.await_exit())

        return go

    for budget in range(1, 16):
        for delay in range(4):
            out, offered = run(
                program(delay).pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            )
            assert out == ([1] if offered == fx.Success(True) else []), (budget, delay)


def test_offer_to_a_sliding_queue_of_capacity_zero_keeps_the_newest_item():
    """Effect Queue.ts ``offerUnsafe``: a full sliding queue drops its oldest
    item and appends the new one, so capacity 0 holds one item. (Checked
    against Effect 4.0.6; no Effect test covers it.)"""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].sliding(0)
        offered = ((yield from q.offer(1)), (yield from q.offer(2)))
        size = yield from q.size
        return offered, size, (yield from q.take()), (yield from q.size)

    assert run(program) == ((True, True), 1, 2, 0)


def test_offer_all_to_a_sliding_queue_of_capacity_zero_keeps_nothing():
    """Effect Queue.ts ``offerAllUnsafe`` trims a sliding queue to its
    capacity after appending, so nothing stays and nothing is returned."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].sliding(0)
        return (yield from q.offer_all([1, 2, 3])), (yield from q.size)

    assert run(program) == ([], 0)


def test_offer_to_a_sliding_queue_of_capacity_zero_wakes_a_waiting_taker():
    """Effect leaves the taker parked next to the item (its sliding branch
    skips ``releaseTakers``), which hangs it until another take; pyfect wakes
    it, as every other offer that adds an item does."""

    @fx.gen
    def program():
        q = yield from fx.Queue[int].sliding(0)
        taker = yield from q.take().fork()
        yield from _settle()
        yield from q.offer(7)
        return (yield from taker.join()), (yield from q.size)

    assert run(program) == (7, 0)
