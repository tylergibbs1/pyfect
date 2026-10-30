"""Ports of Effect's ``Stream.test.ts``: the ``grouping``, ``share``,
``groupAdjacentBy``, ``partition`` (both sections), ``broadcast`` and
``broadcastN`` sections, and the ``toAsyncIterable`` titles of
``destructors``.

Each test's docstring is the Effect test title. Effect's inclusive
``Stream.range(a, b)`` is ``stream.range_inclusive(a, b)``,
``Result.succeed`` / ``Result.fail`` are ``Ok`` / ``Err``,
``Deferred.await`` is ``wait()``, ``Fiber.await`` is ``await_exit()``, an
iterator's ``return()`` is ``aclose()`` and its ``throw(error)`` is
``athrow(error)``.

Adapted, with the reason:

- "normalizes the number of downstream streams" passes ``-1``, ``0``,
  ``1`` and ``2`` where Effect passes ``NaN``, ``-1``, ``0.5``, ``1.9`` and
  ``2.9``: ``n`` is an ``int``, so pyright rejects ``NaN`` and fractions.
- "backpressure" and "partition - backpressure" expect ``[4, 2, 0]``
  where Effect expects ``[2, 0]`` when the latch opens at ``2``, and check
  that the evens reader is still waiting on the odds then: Effect resumes
  the waiting test fiber inline, inside ``Deferred.succeed``, while pyfect
  resumes it through the scheduler, after the reader has also taken the
  ``4`` already admitted to its queue.
- "toAsyncIterable - early for await exit interrupts the producer" leaves
  the loop inside ``contextlib.aclosing``: Python's ``async for`` does not
  close an iterator it leaves early, where JavaScript's ``for await``
  calls ``return()``.
- "toAsyncIterable - return does not reject an unawaited in-flight next"
  starts the ``__anext__`` as a task and checks it ends: a Python
  coroutine nobody awaits never starts, where a JavaScript ``next()`` runs
  up to its first ``await`` when called.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any

import pyfect as fx
from pyfect import schedule, sink, stream, testing
from pyfect.scope import CloseableScope
from pyfect.stream import Stream

# --- grouping --------------------------------------------------------------------


def _parity(n: int) -> str:
    return "even" if n % 2 == 0 else "odd"


@testing.effect
def test_group_by():
    """groupBy"""
    grouped = yield from (
        stream.make(1, 2, 3, 4, 5)
        .group_by_key(_parity)
        .map_effect(
            lambda group: group[1].run_collect().map(lambda values: (group[0], values)),
            concurrency="unbounded",
        )
        .run_collect()
    )
    assert grouped == [("odd", [1, 3, 5]), ("even", [2, 4])]


def _evens_and_first_odd(group: tuple[int, Stream[int]]) -> Stream[int]:
    key, values = group
    return values if key == 0 else values.take(1)


@testing.effect
def test_group_by_key_a_group_that_stops_early_does_not_block_the_others():
    """groupByKey - a group that stops early does not block the others"""
    result = yield from (
        stream.range_inclusive(1, 8)
        .rechunk(1)
        .group_by_key(lambda n: n % 2, buffer_size=1)
        .flat_map(_evens_and_first_odd, concurrency="unbounded")
        .run_collect()
    )
    assert sorted(result) == [1, 2, 4, 6, 8]


@testing.effect
def test_group_by_a_group_that_stops_early_does_not_block_the_others():
    """groupBy - a group that stops early does not block the others"""
    result = yield from (
        stream.range_inclusive(1, 8)
        .rechunk(1)
        .group_by(lambda n: fx.succeed((n % 2, n)), buffer_size=1)
        .flat_map(_evens_and_first_odd, concurrency="unbounded")
        .run_collect()
    )
    assert sorted(result) == [1, 2, 4, 6, 8]


# --- share -----------------------------------------------------------------------


@testing.effect
def test_share_sequenced():
    """sequenced"""
    shared = yield from stream.from_schedule(schedule.spaced(1)).share(capacity=16)

    first_fiber = yield from shared.take(1).run(sink.collect()).fork(start_immediately=True)
    yield from testing.adjust(1)
    assert (yield from first_fiber.join()) == [0]

    second_fiber = yield from shared.take(1).run(sink.collect()).fork(start_immediately=True)
    yield from testing.adjust(1)
    assert (yield from second_fiber.join()) == [0]


@testing.effect
def test_share_sequenced_with_idle_time_to_live():
    """sequenced with idleTimeToLive"""
    shared = yield from stream.from_schedule(schedule.spaced(1)).share(
        capacity=16, idle_time_to_live=1
    )

    first_fiber = yield from shared.take(1).run(sink.collect()).fork(start_immediately=True)
    yield from testing.adjust(1)
    assert (yield from first_fiber.join()) == [0]

    second_fiber = yield from shared.take(1).run(sink.collect()).fork(start_immediately=True)
    yield from testing.adjust(1)
    assert (yield from second_fiber.join()) == [1]


@testing.effect
def test_share_ends_a_consumer_that_starts_after_the_shared_upstream_has_ended():
    """ends a consumer that starts after the shared upstream has ended"""
    shared = yield from stream.make(1, 2, 3).share(capacity=16, idle_time_to_live=60)
    yield from shared.run_drain()

    assert (yield from shared.run_collect()) == []


@testing.effect
def test_share_parallel():
    """parallel"""
    shared = yield from stream.from_schedule(schedule.spaced(1)).share(capacity=16)

    fiber1 = yield from shared.take(1).run(sink.collect()).fork(start_immediately=True)
    fiber2 = yield from shared.take(2).run(sink.collect()).fork(start_immediately=True)
    yield from testing.adjust(2)

    assert (yield from fx.Fiber.join_all([fiber1, fiber2])) == [[0], [0, 1]]


# --- groupAdjacentBy -------------------------------------------------------------

_MESSAGES = [(1, "A"), (1, "B"), (1, "D"), (2, "C")]
_GROUPED = [[(1, "A"), (1, "B"), (1, "D")], [(2, "C")]]


def _code(message: tuple[int, str]) -> int:
    return message[0]


def _groups_of(source: Stream[tuple[int, str]]) -> fx.Effect[list[list[tuple[int, str]]]]:
    collected = source.group_adjacent_by(_code).run_collect()
    return collected.map(lambda groups: [list(chunk) for _, chunk in groups])


@testing.effect
def test_group_adjacent_by_one_big_chunk():
    """one big chunk"""
    assert (yield from _groups_of(stream.from_iterable(_MESSAGES))) == _GROUPED


@testing.effect
def test_group_adjacent_by_several_single_element_chunks():
    """several single element chunks"""
    source = stream.from_arrays(*([message] for message in _MESSAGES))
    assert (yield from _groups_of(source)) == _GROUPED


@testing.effect
def test_group_adjacent_by_group_across_chunks():
    """group across chunks"""
    source = stream.from_arrays(_MESSAGES[:2], _MESSAGES[2:])
    assert (yield from _groups_of(source)) == _GROUPED


# --- partition -------------------------------------------------------------------


def _even_odd(n: int) -> fx.Ok[int] | fx.Err[int]:
    return fx.Ok(n) if n % 2 == 0 else fx.Err(n)


@testing.effect
def test_partition_defaults_to_a_capacity_of_16():
    """defaults to a capacity of 16"""
    pulled = 0

    def count() -> None:
        nonlocal pulled
        pulled += 1

    yield from (
        stream.range_inclusive(0, 31).rechunk(1).tap(lambda _: fx.sync(count)).partition(fx.Ok)
    )
    yield from testing.adjust(0)
    # Sixteen elements are buffered; the next offer is blocked.
    assert pulled == 17


def _check_values():
    evens, odds = yield from stream.range_inclusive(0, 5).partition(_even_odd)
    assert (yield from evens.run_collect()) == [0, 2, 4]
    assert (yield from odds.run_collect()) == [1, 3, 5]


@testing.effect
def test_partition_values():
    """values"""
    yield from _check_values()


@testing.effect
def test_partition_partition_values():
    """partition - values"""
    yield from _check_values()


@testing.effect
def test_partition_one_side_stopping_early_does_not_block_the_other():
    """one side stopping early does not block the other"""
    evens, odds = yield from stream.range_inclusive(1, 8).partition(_even_odd, capacity=1)
    result = yield from fx.all(evens.run_collect(), odds.take(1).run_collect(), concurrency=2)
    assert result == ([2, 4, 6, 8], [1])


def _check_errors():
    failing = stream.make(0).concat(stream.fail("boom"))
    evens, odds = yield from failing.partition(_even_odd)
    assert (yield from evens.run_collect().flip()) == "boom"
    assert (yield from odds.run_collect().flip()) == "boom"


@testing.effect
def test_partition_errors():
    """errors"""
    yield from _check_errors()


@testing.effect
def test_partition_partition_errors():
    """partition - errors"""
    yield from _check_errors()


def _check_backpressure():
    evens, odds = yield from stream.range_inclusive(0, 5).partition(_even_odd, capacity=1)
    ref = yield from fx.Ref[list[int]].make([])
    latch = yield from fx.Deferred[None].make()

    def record(n: int) -> fx.Effect[object]:
        return ref.update(lambda seen: [n, *seen]).and_then(
            latch.succeed(None).when(fx.sync(lambda: n == 2))
        )

    fiber = yield from evens.tap(record).run_drain().fork()
    yield from latch.wait()
    result1 = yield from ref.get()
    blocked = fiber.poll_unsafe() is None
    result2 = yield from odds.run_collect()
    yield from fiber.await_exit()
    result3 = yield from ref.get()
    assert result1 == [4, 2, 0]
    assert blocked
    assert result2 == [1, 3, 5]
    assert result3 == [4, 2, 0]


@testing.effect
def test_partition_backpressure():
    """backpressure"""
    yield from _check_backpressure()


@testing.effect
def test_partition_partition_backpressure():
    """partition - backpressure"""
    yield from _check_backpressure()


@testing.effect
def test_partition_effect_allows_repeated_runs_without_hanging():
    """partitionEffect - allows repeated runs without hanging"""

    def run_once() -> fx.Effect[list[fx.Result[int, int]]]:
        def body():
            passes, fails = yield from stream.from_iterable(list[int]()).partition_effect(
                lambda n: fx.succeed(_even_odd(n))
            )
            return (yield from fails.merge_result(passes).run_collect())

        return fx.scoped(fx.gen(body))

    result = yield from fx.for_each(range(100), lambda _: run_once()).as_(0)
    assert result == 0


@testing.effect
def test_partition_effect_values():
    """partitionEffect - values"""

    def classify(n: int) -> fx.Effect[fx.Ok[int] | fx.Err[str]]:
        return fx.succeed(fx.Ok(n + 10) if n % 2 == 0 else fx.Err(f"odd:{n}"))

    passes, fails = yield from stream.range_inclusive(0, 5).partition_effect(classify)
    assert (yield from passes.run_collect()) == [10, 12, 14]
    assert (yield from fails.run_collect()) == ["odd:1", "odd:3", "odd:5"]


@testing.effect
def test_partition_effect_one_side_stopping_early_does_not_block_the_other():
    """partitionEffect - one side stopping early does not block the other"""
    evens, odds = yield from stream.range_inclusive(1, 8).partition_effect(
        lambda n: fx.succeed(_even_odd(n)), capacity=1
    )
    result = yield from fx.all(evens.run_collect(), odds.take(1).run_collect(), concurrency=2)
    assert result == ([2, 4, 6, 8], [1])


@testing.effect
def test_partition_queue_values():
    """partitionQueue - values"""

    def classify(n: int) -> fx.Ok[int] | fx.Err[str]:
        return fx.Ok(n + 1) if n % 2 == 0 else fx.Err(f"odd:{n}")

    passes, fails = yield from stream.range_inclusive(0, 5).partition_queue(classify)
    assert (yield from stream.from_queue(passes).run_collect()) == [1, 3, 5]
    assert (yield from stream.from_queue(fails).run_collect()) == ["odd:1", "odd:3", "odd:5"]


@testing.effect
def test_partition_with_filter():
    """partition with Filter"""
    passed, failed = yield from stream.range_inclusive(0, 5).partition(_even_odd)
    assert (yield from passed.run_collect()) == [0, 2, 4]
    assert (yield from failed.run_collect()) == [1, 3, 5]


# --- broadcast -------------------------------------------------------------------


@testing.effect
def test_broadcast_ends_a_subscriber_that_subscribes_after_the_upstream_has_ended():
    """ends a subscriber that subscribes after the upstream has ended"""
    broadcasted = yield from stream.from_arrays([1], [2], [3]).broadcast(capacity=8, replay=2)
    yield from broadcasted.run_drain()

    assert (yield from broadcasted.run_collect()) == [2, 3]


@testing.effect
def test_broadcast_fails_a_subscriber_that_subscribes_after_the_upstream_has_failed():
    """fails a subscriber that subscribes after the upstream has failed"""
    broadcasted = yield from stream.fail("boom").broadcast(capacity=8)
    yield from broadcasted.run_drain().exit()

    assert (yield from broadcasted.run_collect().exit()) == fx.exit.fail("boom")


@testing.effect
def test_broadcast_n_normalizes_the_number_of_downstream_streams():
    """normalizes the number of downstream streams"""
    results = yield from fx.for_each(
        [-1, 0, 1, 2], lambda n: stream.empty.broadcast_n(n, capacity=1).map(len)
    )
    assert results == [0, 0, 1, 2]


@testing.effect
def test_broadcast_n_fans_out_to_a_fixed_number_of_streams():
    """fans out to a fixed number of streams"""
    left, right = yield from stream.make(1, 2, 3).broadcast_n(2, capacity=4)
    result = yield from fx.all(left.run_collect(), right.run_collect(), concurrency="unbounded")
    assert result == ([1, 2, 3], [1, 2, 3])


@testing.effect
def test_broadcast_n_ends_a_subscriber_whose_end_a_full_dropping_buffer_would_have_dropped():
    """ends a subscriber whose end a full dropping buffer would have dropped"""
    (only,) = yield from stream.make(1, 2, 3).broadcast_n(1, capacity=1, strategy="dropping")
    # Let the upstream fill the single slot and end before the subscriber pulls.
    yield from fx.yield_now()

    assert (yield from only.run_collect()) == [1, 2, 3]


@testing.effect
def test_broadcast_n_delivers_every_element_to_a_subscriber_that_keeps_up_while_another_lags():
    """delivers every element to a subscriber that keeps up while another lags beyond capacity"""
    slow, fast = (
        yield from stream.range_inclusive(1, 5).map_effect(fx.succeed).broadcast_n(2, capacity=1)
    )
    result = yield from fx.all(
        slow.tap(lambda _: fx.yield_now()).run_collect(),
        fast.run_collect(),
        concurrency="unbounded",
    )
    assert result == ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])


@testing.effect
def test_broadcast_n_propagates_failures_to_all_downstream_streams():
    """propagates failures to all downstream streams"""
    left, right = yield from stream.fail("boom").broadcast_n(2, capacity=4)
    result = yield from fx.all(
        left.run_collect().exit(), right.run_collect().exit(), concurrency="unbounded"
    )
    assert result == (fx.exit.fail("boom"), fx.exit.fail("boom"))


# --- toAsyncIterable ---------------------------------------------------------------

_ENDED = object()
"""What ``_outcome`` gives for an iterator that ended."""


async def _outcome(step: Awaitable[object]) -> object:
    try:
        return await step
    except StopAsyncIteration:
        return _ENDED


async def _caught(step: Awaitable[object]) -> object:
    try:
        return await step
    except Exception as error:
        return error


def _with_scope_finalizer[A, E](
    source: Stream[A, E], finalizer: Callable[[fx.Exit[Any, Any]], fx.Effect[object]]
) -> Stream[A, E]:
    def add(
        pull: fx.Effect[tuple[A, ...], E | fx.Done], scope: CloseableScope
    ) -> fx.Effect[fx.Effect[tuple[A, ...], E | fx.Done]]:
        return scope.add_finalizer(finalizer).as_(pull)

    return stream.transform_pull(source, add)


def _waiting_forever(
    started: fx.Deferred[None] | None, on_interrupt: Callable[[], None]
) -> Stream[None]:
    wait: fx.Effect[None] = (
        fx.never if started is None else started.succeed(None).and_then(fx.never)
    )
    return stream.from_effect(wait.on_interrupt(fx.sync(on_interrupt)))


class _Flag:
    def __init__(self) -> None:
        self.raised = False

    def raise_(self) -> None:
        self.raised = True


@testing.effect(asyncio=True)
def test_to_async_iterable_return_interrupts_an_in_flight_pull():
    """toAsyncIterable - return interrupts an in-flight pull"""
    started = yield from fx.Deferred[None].make()
    interrupted = _Flag()
    iterator = aiter(_waiting_forever(started, interrupted.raise_).to_async_iterable())

    pending = asyncio.ensure_future(_outcome(anext(iterator)))
    yield from started.wait()
    result = yield from fx.from_async(iterator.aclose)
    pending_result = yield from fx.from_async(lambda: pending)

    assert result is None
    assert pending_result is _ENDED
    assert interrupted.raised


@testing.effect(asyncio=True)
def test_to_async_iterable_return_does_not_reject_an_unawaited_in_flight_next():
    """toAsyncIterable - return does not reject an unawaited in-flight next"""
    interrupted = _Flag()
    iterator = aiter(_waiting_forever(None, interrupted.raise_).to_async_iterable())

    pending = asyncio.ensure_future(_outcome(anext(iterator)))
    yield from fx.from_async(lambda: asyncio.sleep(0))
    result = yield from fx.from_async(iterator.aclose)
    yield from fx.from_async(lambda: asyncio.sleep(0))

    assert result is None
    assert (yield from fx.from_async(lambda: pending)) is _ENDED
    assert interrupted.raised


@testing.effect(asyncio=True)
def test_to_async_iterable_early_for_await_exit_interrupts_the_producer():
    """toAsyncIterable - early for await exit interrupts the producer"""
    interrupted = _Flag()

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        return queue.offer(1).and_then(fx.never).on_interrupt(fx.sync(interrupted.raise_))

    iterable = stream.callback(register).to_async_iterable()

    async def leave_early() -> None:
        async with contextlib.aclosing(aiter(iterable)) as iterator:
            async for _ in iterator:
                break

    yield from fx.from_async(leave_early)

    assert interrupted.raised


@testing.effect(asyncio=True)
def test_to_async_iterable_return_is_idempotent_without_an_in_flight_pull():
    """toAsyncIterable - return is idempotent without an in-flight pull"""
    iterator = aiter(stream.make(1).to_async_iterable())

    first = yield from fx.from_async(iterator.aclose)
    second = yield from fx.from_async(iterator.aclose)
    after = yield from fx.from_async(lambda: _outcome(anext(iterator)))

    assert first is None
    assert second is None
    assert after is _ENDED


@testing.effect(asyncio=True)
def test_to_async_iterable_natural_completion_closes_the_scope_with_a_successful_exit():
    """toAsyncIterable - natural completion closes the scope with a successful exit"""
    exits: list[fx.Exit[Any, Any]] = []
    source = _with_scope_finalizer(stream.make(1, 2), lambda ex: fx.sync(lambda: exits.append(ex)))

    async def collect() -> list[int]:
        return [value async for value in source.to_async_iterable()]

    values = yield from fx.from_async(collect)

    assert values == [1, 2]
    assert exits == [fx.exit.succeed(None)]


def _logging_finalizer(
    exits: list[fx.Exit[Any, Any]], error: Exception
) -> Callable[[fx.Exit[Any, Any]], fx.Effect[object]]:
    return lambda ex: fx.sync(lambda: exits.append(ex)).and_then(fx.die(error))


@testing.effect(asyncio=True)
def test_to_async_iterable_stream_failure_is_forwarded_to_the_scope():
    """toAsyncIterable - stream failure is forwarded to the scope"""
    stream_error = ValueError("stream failure")
    exits: list[fx.Exit[Any, Any]] = []
    logs: list[object] = []
    source = _with_scope_finalizer(
        stream.fail(stream_error), _logging_finalizer(exits, RuntimeError("finalizer failure"))
    )

    def body():
        iterable = yield from source.to_async_iterable_effect()
        return (yield from fx.from_async(lambda: _caught(anext(aiter(iterable)))))

    thrown = yield from fx.gen(body).with_logger(fx.Logger.make(lambda o: logs.append(o.message)))

    assert thrown is stream_error
    assert exits == [fx.exit.fail(stream_error)]
    assert len(logs) == 1


@testing.effect(asyncio=True)
def test_to_async_iterable_throw_forwards_a_failure_exit_and_preserves_its_error():
    """toAsyncIterable - throw forwards a failure exit and preserves its error"""
    thrown_error = ValueError("thrown failure")
    exits: list[fx.Exit[Any, Any]] = []
    logs: list[object] = []
    source = _with_scope_finalizer(
        stream.make(1), _logging_finalizer(exits, RuntimeError("finalizer failure"))
    )

    def body():
        iterator = aiter((yield from source.to_async_iterable_effect()))
        yield from fx.from_async(lambda: anext(iterator))
        return (yield from fx.from_async(lambda: _caught(iterator.athrow(thrown_error))))

    thrown = yield from fx.gen(body).with_logger(fx.Logger.make(lambda o: logs.append(o.message)))

    assert thrown is thrown_error
    assert exits == [fx.exit.die(thrown_error)]
    assert len(logs) == 1


@testing.effect(asyncio=True)
def test_to_async_iterable_throw_interrupts_an_in_flight_pull():
    """toAsyncIterable - throw interrupts an in-flight pull"""
    started = yield from fx.Deferred[None].make()
    interrupted = _Flag()
    iterator = aiter(_waiting_forever(started, interrupted.raise_).to_async_iterable())
    error = ValueError("boom")

    pending = asyncio.ensure_future(_outcome(anext(iterator)))
    yield from started.wait()
    thrown = yield from fx.from_async(lambda: _caught(iterator.athrow(error)))
    pending_result = yield from fx.from_async(lambda: pending)

    assert thrown is error
    assert pending_result is _ENDED
    assert interrupted.raised
