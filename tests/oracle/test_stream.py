"""Ports of Effect's ``Stream.test.ts``: the ``callback``, ``destructors``,
``constructors``, ``pagination`` and ``fromEventListener`` sections (the
Stream core, constructors, sources and run functions of M6).

Each test's docstring is the Effect test title. Chunks are tuples here,
``Uint8Array`` is ``bytes``, Effect's inclusive ``Stream.range(a, b)`` is
``stream.range_inclusive(a, b)`` (``stream.range`` follows Python's), and
``fromArray`` / ``fromIteratorSucceed`` are ``from_iterable``.
``provideService`` comes from ``tests/oracle/_stream_ops.py`` until the
Stream context functions are added; the operator sections are ported in
``test_stream_*.py``.

Adapted, with the reason:

- "backpressure" yields once after the pull before counting the offers:
  the offers the pull makes room for resume through the scheduler.
- The chunk-size normalization titles pass ``0``, ``-1`` and ``2`` where
  Effect passes ``0``, ``NaN`` and ``2.9`` (or ``1.9``): ``chunk_size`` is
  an ``int``, so pyright rejects ``NaN`` and fractions.

Not ported:

- ``toReadableStream`` (two cases), ``fromReadableStream``,
  ``fromEventListener`` (two titles): Web Streams and DOM events have no
  Python counterpart (PARITY.md); ``callback`` is how a listener feeds a
  stream.
- The eight ``toAsyncIterable`` titles: ``to_async_iterator`` is the last
  step of M6.
- The operator sections are in ``test_stream_filtering.py``,
  ``test_stream_errors.py``, ``test_stream_combining.py`` and
  ``test_stream_timing.py``; the others (encoding, grouping, sinks,
  sharing, partitioning) port with their M6 clusters.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import pyfect as fx
from pyfect import stream, testing

from . import _stream_ops as ops

# --- callback --------------------------------------------------------------------


@testing.effect
def test_with_take():
    """with take"""
    array = [1, 2, 3, 4, 5]

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        def offer_all() -> None:
            for n in array:
                queue.unsafe_offer(n)

        return fx.sync(offer_all)

    result = yield from stream.callback(register).take(len(array)).run_collect()
    assert result == array


@testing.effect
def test_with_cleanup():
    """with cleanup"""
    cleanup = False
    latch = yield from fx.Latch.make()

    def mark(_: object) -> fx.Effect[None]:
        def run() -> None:
            nonlocal cleanup
            cleanup = True

        return fx.sync(run)

    @fx.fn
    def register(queue: fx.Queue[None, fx.Done]):
        yield from fx.add_finalizer(mark)
        yield from queue.offer(None)

    fiber = yield from stream.callback(register).tap(lambda _: latch.open()).run_drain().fork()
    yield from latch.wait()
    yield from fiber.interrupt()
    assert cleanup


@testing.effect
def test_signals_the_end_of_the_stream():
    """signals the end of the stream"""

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        queue.unsafe_end()
        return fx.void

    result = yield from stream.callback(register).run_collect()
    assert result == []


@testing.effect
def test_handles_errors():
    """handles errors"""
    error = ValueError("boom")

    def register(queue: fx.Queue[int, ValueError | fx.Done]) -> fx.Effect[None]:
        queue.unsafe_fail_cause(fx.cause.fail(error))
        return fx.void

    result = yield from stream.callback(register).run_collect().exit()
    assert result == fx.exit.fail(error)


@testing.effect
def test_handles_defects():
    """handles defects"""
    error = ValueError("boom")

    def register(_queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        raise error

    result = yield from stream.callback(register).run_collect().exit()
    assert result == fx.exit.die(error)


@testing.effect
def test_backpressure():
    """backpressure"""
    count = 0
    offered = 0
    done = False

    @fx.fn
    def offer(queue: fx.Queue[int, fx.Done], n: int):
        nonlocal count, offered
        count += 1
        yield from queue.offer(n)
        offered += 1

    def finish() -> None:
        nonlocal done
        done = True

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        offers = fx.for_each(range(1, 8), lambda n: offer(queue, n), concurrency="unbounded")
        return offers.and_then(fx.sync(finish))

    pull = yield from stream.callback(register, buffer_size=2).to_pull()
    yield from fx.yield_now()
    assert (count, offered, done) == (7, 2, False)
    assert (yield from pull) == (1, 2)
    yield from fx.yield_now()
    assert (offered, done) == (4, False)


@testing.effect
def test_register_effect_has_run_when_the_stream_starts_pulling():
    """register effect has run when the stream starts pulling"""
    emit: list[fx.Queue[int, fx.Done]] = []

    def register(queue: fx.Queue[int, fx.Done]) -> fx.Effect[None]:
        return fx.sync(lambda: emit.append(queue))

    fiber = yield from (
        stream.callback(register).take(1).run_collect().fork(start_immediately=True)
    )
    assert fiber.unsafe_poll() is None
    assert emit, "register effect has not run"
    emit[0].unsafe_offer(1)
    assert (yield from fiber.join()) == [1]


# --- destructors -----------------------------------------------------------------


@testing.effect
def test_mk_array_buffer_concatenates_uint8array_chunks():
    """mkArrayBuffer - concatenates Uint8Array chunks"""
    buffer = yield from stream.make(bytes([1, 2]), bytes([3, 4])).run_bytes()
    assert list(buffer) == [1, 2, 3, 4]


@testing.effect
def test_run_for_each_while_continues_across_chunk_boundaries():
    """runForEachWhile continues across chunk boundaries"""
    seen: list[int] = []

    def keep(n: int) -> fx.Effect[bool]:
        return fx.sync(lambda: seen.append(n) or True)

    yield from stream.from_arrays([1, 2], [3, 4]).run_for_each_while(keep)
    assert seen == [1, 2, 3, 4]


@testing.effect
def test_run_for_each_while_stops_when_predicate_returns_false():
    """runForEachWhile stops when predicate returns false"""
    seen: list[int] = []

    def keep(n: int) -> fx.Effect[bool]:
        return fx.sync(lambda: seen.append(n) or n < 3)

    yield from stream.from_arrays([1, 2, 3], [4, 5]).run_for_each_while(keep)
    assert seen == [1, 2, 3]


# --- constructors ----------------------------------------------------------------


class GreeterShape(Protocol):
    def greet(self, name: str) -> str: ...


class Greeter(fx.Tag[GreeterShape]): ...


@dataclass
class _Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


@testing.effect
def test_range_min_less_than_max():
    """range - min less than max"""
    assert (yield from stream.range_inclusive(1, 3).run_collect()) == [1, 2, 3]


@testing.effect
def test_range_zero_chunk_size_does_not_change_the_emitted_range():
    """range - zero chunk size does not change the emitted range"""
    result = yield from stream.range_inclusive(1, 3, chunk_size=0).take(4).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_range_normalizes_the_chunk_size_without_changing_emitted_values():
    """range - normalizes the chunk size without changing emitted values"""
    results = yield from fx.for_each(
        [-1, 0, 2],
        lambda size: stream.range_inclusive(1, 5, chunk_size=size).chunks().run_collect(),
    )
    assert results == [
        [(1,), (2,), (3,), (4,), (5,)],
        [(1,), (2,), (3,), (4,), (5,)],
        [(1, 2), (3, 4), (5,)],
    ]


@testing.effect
def test_service():
    """service"""
    result = yield from (
        stream.service(Greeter)
        .map(lambda greeter: greeter.greet("World"))
        .pipe(ops.provide_service(Greeter, _Greeter()))
        .run_collect()
    )
    assert result == ["Hello, World!"]


@testing.effect
def test_service_option_some():
    """serviceOption - some"""
    result = yield from (
        stream.service_option(Greeter)
        .map(lambda found: fx.option.map(found, lambda g: g.greet("World")))
        .pipe(ops.provide_service(Greeter, _Greeter()))
        .run_collect()
    )
    assert result == [fx.Some("Hello, World!")]


@testing.effect
def test_service_option_none():
    """serviceOption - none"""
    assert (yield from stream.service_option(Greeter).run_collect()) == [None]


@testing.effect
def test_range_min_greater_than_max():
    """range - min greater than max"""
    assert (yield from stream.range_inclusive(4, 3).run_collect()) == []


@testing.effect
def test_range_min_equal_to_max():
    """range - min equal to max"""
    assert (yield from stream.range_inclusive(3, 3).run_collect()) == [3]


@testing.effect
def test_from_iterator_succeed_normalizes_the_chunk_size():
    """fromIteratorSucceed - normalizes the chunk size"""
    results = yield from fx.for_each(
        [-1, 0, 1],
        lambda size: stream.from_iterable(iter([1, 2, 3]), chunk_size=size).chunks().run_collect(),
    )
    assert results == [[(1,), (2,), (3,)]] * 3


@testing.effect
def test_from_iterable_emits_array_as_one_chunk_by_default():
    """fromIterable - emits array as one chunk by default"""
    result = yield from stream.from_iterable([1, 2, 3, 4]).chunks().run_collect()
    assert result == [(1, 2, 3, 4)]


@testing.effect
def test_from_iterable_supports_chunk_size_option():
    """fromIterable - supports chunkSize option"""
    result = yield from stream.from_iterable([1, 2, 3, 4, 5], chunk_size=2).chunks().run_collect()
    assert result == [(1, 2), (3, 4), (5,)]


@testing.effect
def test_from_iterable_normalizes_the_chunk_size():
    """fromIterable - normalizes the chunk size"""
    results = yield from fx.for_each(
        [-1, 0, 2],
        lambda size: stream.from_iterable([1, 2, 3], chunk_size=size).chunks().run_collect(),
    )
    assert results == [[(1,), (2,), (3,)], [(1,), (2,), (3,)], [(1, 2), (3,)]]


@testing.effect
def test_scoped_provides_scope_to_from_effect_pull_effects():
    """scoped - provides scope to fromEffect pull effects"""
    releases = yield from fx.Ref.make(0)
    resource = fx.acquire_release(
        fx.succeed("resource"), lambda _r, _ex: releases.update(lambda n: n + 1)
    )
    result = yield from stream.from_effect(resource).pipe(stream.scoped).run_collect()
    assert result == ["resource"]
    assert (yield from releases.get()) == 1


@testing.effect
def test_scoped_provides_scope_to_sequential_map_effect_pull_effects():
    """scoped - provides scope to sequential mapEffect pull effects"""
    releases = yield from fx.Ref.make(0)

    def acquire(n: int) -> fx.Effect[int, Any, Any]:
        return fx.acquire_release(
            fx.succeed(n * 2), lambda _r, _ex: releases.update(lambda c: c + 1)
        )

    result = (
        yield from stream.from_iterable([1, 2])
        .map_effect(acquire)
        .pipe(stream.scoped)
        .run_collect()
    )
    assert result == [2, 4]
    assert (yield from releases.get()) == 2


# --- pagination ------------------------------------------------------------------


@testing.effect
def test_paginate():
    """paginate"""
    page_size = 2

    def page(
        state: tuple[list[int], list[int]],
    ) -> fx.Effect[tuple[list[int], fx.Option[tuple[list[int], list[int]]]]]:
        chunk, nums = state
        if not nums:
            return fx.succeed((chunk, None))
        return fx.succeed((chunk, fx.Some((nums[:page_size], nums[page_size:]))))

    result = yield from stream.paginate(([0], [1, 2, 3, 4, 5]), page).run_collect()
    assert result == [0, 1, 2, 3, 4, 5]
