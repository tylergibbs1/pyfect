"""Ports of Effect's ``Channel.test.ts``: the core cases (constructors,
destructors, ``map``).

Each test's docstring is the Effect test title. Arrays are tuples here
(``fromIterableArray`` writes ``(1, 2)``), ``Cause.die("x")`` holds an
exception, and a resume goes through the scheduler, so a port may yield
where Effect's fiber would already have run.

Not ported:

- ``fromArray`` and ``fromChunk`` are ``from_iterable`` over a list or a
  tuple; their titles are ported with it.
- The ``fromIteratorArray`` / ``fromIterableArray`` chunk-size cases with
  ``NaN`` or fractions: ``chunk_size`` is an ``int``, so only ``0`` and
  negatives are normalized.
- ``fromReadableStream``, ``fromTransformStream`` (four titles): Web
  Streams have no Python counterpart (PARITY.md).
- ``mkUint8Array``: arrives with the bytes channels.
- ``repetition`` (four titles), ``fromAsyncIterable``, ``callback`` /
  ``callbackArray``, ``mapEffect`` (two), ``filtering`` (two), ``encoding``
  (three), ``merging`` (ten), ``switchMap``, ``interruptWhen`` (two),
  ``conditional catch`` (nine), ``typed recovery with mixed causes``
  (three) and ``unwrapReason`` (three): the combinators they test arrive
  with the later Channel clusters of M6, which port them.
"""

from collections.abc import Generator, Iterator
from typing import Any, Never

import pyfect as fx
from pyfect import channel, testing


@testing.effect
def test_empty():
    """empty"""
    result = yield from channel.empty.run_collect()
    assert result == []


@testing.effect
def test_succeed():
    """succeed"""
    result = yield from channel.succeed(1).run_collect()
    assert result == [1]


@testing.effect
def test_sync():
    """sync"""
    result = yield from channel.sync(lambda: 1).run_collect()
    assert result == [1]


@testing.effect
def test_end():
    """end"""
    seen: list[int] = []
    yield from channel.end(42).map_done(seen.append).run_drain()
    assert seen == [42]


@testing.effect
def test_end_sync():
    """endSync"""
    seen: list[int] = []
    yield from channel.end_sync(lambda: 42).map_done(seen.append).run_drain()
    assert seen == [42]


@testing.effect
def test_from_array():
    """fromArray"""
    array = [0, 1, 2, 3, 4]
    result = yield from channel.from_iterable(array).run_collect()
    assert result == array


@testing.effect
def test_from_chunk():
    """fromChunk"""
    chunk = (0, 1, 2, 3, 4)
    result = yield from channel.from_iterable(chunk).run_collect()
    assert result == list(chunk)


class _Counter(Iterator[int]):
    def __init__(self) -> None:
        self.n = 0

    def __next__(self) -> int:
        if self.n == 5:
            raise StopIteration(self.n)
        self.n += 1
        return self.n - 1


@testing.effect
def test_from_iterator():
    """fromIterator"""
    result = yield from channel.from_iterator(_Counter).run_collect()
    assert result == [0, 1, 2, 3, 4]


def _fibonacci() -> Generator[int]:
    a, b = 0, 1
    for _ in range(5):
        yield a
        a, b = b, a + b


@testing.effect
def test_from_iterator_array():
    """fromIteratorArray"""
    result = yield from channel.from_iterator_array(_fibonacci, 3).run_collect()
    assert result == [(0, 1, 1), (2, 3)]


@testing.effect
def test_from_iterator_array_normalizes_the_chunk_size():
    """fromIteratorArray - normalizes the chunk size"""
    results = yield from fx.for_each(
        [-1, 0],
        lambda size: channel.from_iterator_array(lambda: iter([1, 2, 3]), size).run_collect(),
    )
    assert results == [[(1,), (2,), (3,)], [(1,), (2,), (3,)]]


@testing.effect
def test_from_iterable():
    """fromIterable"""
    result = yield from channel.from_iterable(dict.fromkeys([1, 1, 2, 3])).run_collect()
    assert result == [1, 2, 3]


@testing.effect
def test_from_iterable_array():
    """fromIterableArray"""
    numbers = [1, 2, 3, 4, 5]
    result = yield from channel.from_iterable_array(numbers).run_collect()
    chunked = yield from channel.from_iterable_array(numbers, 4).run_collect()
    assert result == [(1, 2, 3, 4, 5)]
    assert chunked == [(1, 2, 3, 4), (5,)]


@testing.effect
def test_from_iterable_array_normalizes_the_chunk_size():
    """fromIterableArray - normalizes the chunk size"""
    results = yield from fx.for_each(
        [0, 2], lambda size: channel.from_iterable_array([1, 2, 3], size).run_collect()
    )
    assert results == [[(1,), (2,), (3,)], [(1, 2), (3,)]]


@testing.effect
def test_acquire_release():
    """acquireRelease"""
    acquired = yield from fx.Ref.make(False)
    released = yield from fx.Ref.make(False)
    yield from channel.acquire_release(
        acquired.set(True), lambda _, __: released.set(True)
    ).run_drain()
    assert (yield from acquired.get())
    assert (yield from released.get())


@testing.effect
def test_acquire_use_release_releases_resource_when_interrupted_during_acquisition():
    """acquireUseRelease releases resource when interrupted during acquisition"""
    started = yield from fx.Deferred[None, Never].make()
    gate = yield from fx.Deferred[None, Never].make()
    released: list[int] = []

    @fx.gen
    def acquire():
        yield from started.succeed(None)
        yield from gate.wait()
        return 1

    def release(resource: int, _: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: released.append(resource))

    running = channel.acquire_use_release(acquire, lambda _: channel.never, release)
    fiber = yield from running.run_drain().fork()
    yield from started.wait()
    yield from fiber.interrupt().fork(start_immediately=True)
    yield from gate.succeed(None)
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert released == [1]


@testing.effect
def test_acquire_use_release_combines_usage_and_release_failures():
    """acquireUseRelease combines usage and release failures"""
    release_failure = RuntimeError("release failure")
    ex = (
        yield from channel.acquire_use_release(
            fx.void, lambda _: channel.fail("usage failure"), lambda _, __: fx.die(release_failure)
        )
        .run_drain()
        .exit()
    )
    # The release's defect makes the usage's typed error a defect too.
    assert isinstance(ex, fx.Failure)
    assert ex.cause.failures == ()
    [usage, release] = ex.cause.defects
    assert isinstance(usage, fx.UnhandledError) and usage.error == "usage failure"
    assert release is release_failure


@testing.effect
def test_acquire_use_release_surfaces_release_failure_after_successful_usage():
    """acquireUseRelease surfaces release failure after successful usage"""
    release_failure = RuntimeError("release failure")
    ex = (
        yield from channel.acquire_use_release(
            fx.void, lambda _: channel.succeed(1), lambda _, __: fx.die(release_failure)
        )
        .run_drain()
        .exit()
    )
    assert ex == fx.exit.die(release_failure)


@testing.effect
def test_run_drain_returns_the_done_value_after_emitted_elements():
    """runDrain returns the done value after emitted elements"""
    result = yield from channel.from_iterable([1]).concat(channel.end("done")).run_drain()
    assert result == "done"


@testing.effect
def test_map():
    """map"""
    result = yield from channel.from_iterable([1, 2, 3]).map(lambda n: n + 1).run_collect()
    assert result == [2, 3, 4]
