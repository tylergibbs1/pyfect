"""Stream constructors: single values, failures, effects, iterables,
ranges, unfolding, and deferred and scoped streams."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable, Iterable
from typing import Any, Never, overload

from pyfect import channel
from pyfect._context_effects import service_option as _service_option
from pyfect._core import Effect, _Locally, _Succeed, _Suspend, _Sync
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.channel._base import end_with
from pyfect.context import TagLike
from pyfect.errors import Done
from pyfect.option import Option
from pyfect.schedule import Schedule
from pyfect.schedule._model import CurrentMetadata, Metadata, Stop, to_step_with_metadata
from pyfect.scope import Scope
from pyfect.stream._base import AnyStream, StreamBase, require_stream
from pyfect.stream._concat import SuspendedStream
from pyfect.stream._stream import Stream, from_channel, from_pull

DEFAULT_CHUNK_SIZE = channel.DEFAULT_CHUNK_SIZE
"""How many items a stream built from an iterator puts in a chunk."""

type AnyPull = Effect[Any, Any, Any]

_ENDED: Effect[Never, Done] = end_with(None)


def _one[A](value: A) -> tuple[A]:
    return (value,)


def _with_metadata(eff: AnyPull, meta: Metadata[Any, Any]) -> AnyPull:
    return _Locally(eff, lambda ctx: ctx.add(CurrentMetadata, meta))


# --- values and failures -------------------------------------------------------

empty: Stream[Never] = Stream(channel.empty)
"""A stream that ends at once."""

never: Stream[Never] = Stream(channel.never)
"""A stream that never writes and never ends."""


def succeed[A](value: A) -> Stream[A]:
    """A stream of the one item ``value``."""
    return Stream(channel.succeed((value,)))


@overload
def make() -> Stream[Never]: ...
@overload
def make[A](*values: A) -> Stream[A]: ...
def make(*values: Any) -> Stream[Any]:
    """A stream of ``values``, in one chunk."""
    return from_iterable(values)


def sync[A](thunk: Callable[[], A]) -> Stream[A]:
    """A stream of the one item ``thunk()``, called each time it runs."""
    return Stream(channel.sync(lambda: (thunk(),)))


def suspend[A, E, R](thunk: Callable[[], StreamBase[A, E, R]]) -> Stream[A, E, R]:
    """The stream ``thunk()`` returns, built each time it runs."""
    return SuspendedStream(thunk)


def fail[E](error: E) -> Stream[Never, E]:
    """A stream failing with ``error``."""
    return Stream(channel.fail(error))


def fail_sync[E](thunk: Callable[[], E]) -> Stream[Never, E]:
    """A stream failing with ``thunk()``, called each time it runs."""
    return Stream(channel.fail_sync(thunk))


def fail_cause[E](cause: Cause[E]) -> Stream[Never, E]:
    """A stream failing with ``cause``."""
    return Stream(channel.fail_cause(cause))


def fail_cause_sync[E](thunk: Callable[[], Cause[E]]) -> Stream[Never, E]:
    """A stream failing with ``thunk()``, called each time it runs."""
    return Stream(channel.fail_cause_sync(thunk))


def die(defect: BaseException) -> Stream[Never]:
    """A stream failing with the defect ``defect``."""
    return Stream(channel.die(defect))


# --- effects -------------------------------------------------------------------


def from_effect[A, E = Never, R = Never](eff: Effect[A, E, R]) -> Stream[A, E, R]:
    """A stream of the one item ``eff`` succeeds with."""
    require_effect(eff, "eff")
    return Stream(channel.from_effect(eff.map(_one)))


def from_effect_drain[A, E = Never, R = Never](eff: Effect[A, E, R]) -> Stream[Never, E, R]:
    """A stream that runs ``eff`` and ends, writing nothing."""
    require_effect(eff, "eff")
    return Stream(channel.from_effect_drain(eff))


@overload
def from_effect_repeat[A, R = Never](eff: Effect[A, Done, R]) -> Stream[A, Never, R]: ...
@overload
def from_effect_repeat[A, E, R = Never](eff: Effect[A, E | Done, R]) -> Stream[A, E, R]: ...
def from_effect_repeat(eff: Effect[Any, Any, Any]) -> Stream[Any, Any, Any]:
    """A stream of what ``eff`` succeeds with, run again for each item. It
    ends when ``eff`` fails with ``Done()``."""
    require_effect(eff, "eff")
    return from_pull(_Succeed(eff.map(_one)))


def from_effect_schedule[A, EE = Never, RR = Never](
    eff: Effect[A, EE, RR], schedule: Schedule[object, A, EE, RR]
) -> Stream[A, EE, RR]:
    """A stream of what ``eff`` succeeds with, run again after each delay
    of ``schedule`` (stepped with the last value) until it stops. Each run
    of ``eff`` sees the step's ``schedule.CurrentMetadata``."""
    require_effect(eff, "eff")

    def make_pull(step: Callable[[Any], Effect[Metadata[Any, Any] | Stop[Any], Any, Any]]) -> Any:
        first = _with_metadata(eff, CurrentMetadata.default())

        def started(value: Any) -> AnyPull:
            last = value

            def again(decision: Metadata[Any, Any] | Stop[Any]) -> AnyPull:
                if isinstance(decision, Stop):
                    return _ENDED
                return _with_metadata(eff, decision).map(keep)

            def keep(next_value: Any) -> tuple[Any]:
                nonlocal last
                last = next_value
                return (next_value,)

            emitted = False

            def pull() -> AnyPull:
                nonlocal emitted
                if not emitted:
                    emitted = True
                    return _Succeed((last,))
                return step(last).flat_map(again)

            return _Succeed(_Suspend(pull))

        return first.flat_map(started)

    return from_pull(to_step_with_metadata(schedule).flat_map(make_pull))


def service[S, T](tag: TagLike[S, T]) -> Stream[S, Never, T]:
    """A stream of the one item: the service ``tag`` names."""
    return from_effect(tag())


def service_option[S, T](tag: TagLike[S, T]) -> Stream[Option[S]]:
    """A stream of the one item ``Some(service)`` if ``tag``'s service is
    provided, else ``None``."""
    return from_effect(_service_option(tag))


# --- iterables -----------------------------------------------------------------


def from_iterable[A](iterable: Iterable[A], *, chunk_size: int | None = None) -> Stream[A]:
    """A stream of the items of ``iterable``. A list or a tuple is one
    chunk unless ``chunk_size`` is given; anything else is iterated anew
    each run (a generator or an iterator only once) in chunks of up to
    ``chunk_size`` (``DEFAULT_CHUNK_SIZE`` by default, at least 1)."""
    if isinstance(iterable, list | tuple) and chunk_size is None:
        chunk = tuple(iterable)
        return Stream(channel.succeed(chunk)) if chunk else empty
    size = DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
    chunks = channel.from_iterator_array(lambda: iter(iterable), size)
    return Stream(chunks.map_done(lambda _: None))


def from_arrays[A](*arrays: Iterable[A]) -> Stream[A]:
    """A stream of the items of ``arrays``, one chunk per non-empty array."""
    chunks = tuple(chunk for chunk in builtins.map(tuple, arrays) if chunk)
    return Stream(channel.from_iterable(chunks))


def from_iterable_effect[A, E = Never, R = Never](
    eff: Effect[Iterable[A], E, R],
) -> Stream[A, E, R]:
    """A stream of the items of the iterable ``eff`` succeeds with."""
    require_effect(eff, "eff")
    channels: Any = eff.map(_iterable_channel)
    return Stream(channel.unwrap(channels))


@overload
def from_iterable_effect_repeat[A, R = Never](
    eff: Effect[Iterable[A], Done, R],
) -> Stream[A, Never, R]: ...
@overload
def from_iterable_effect_repeat[A, E, R = Never](
    eff: Effect[Iterable[A], E | Done, R],
) -> Stream[A, E, R]: ...
def from_iterable_effect_repeat(eff: Effect[Any, Any, Any]) -> Stream[Any, Any, Any]:
    """A stream of the items of the iterables ``eff`` succeeds with, run
    again after each. It ends when ``eff`` fails with ``Done()``."""
    require_effect(eff, "eff")
    iterables: Any = channel.from_pull(_Succeed(eff))
    return Stream(iterables.flat_map(_iterable_channel))


def _iterable_channel(items: Iterable[Any]) -> Any:
    return from_iterable(items)._channel


# --- unfolding -----------------------------------------------------------------


def unfold[S, A, E = Never, R = Never](
    initial: S, f: Callable[[S], Effect[tuple[A, S] | None, E, R]]
) -> Stream[A, E, R]:
    """A stream of the items ``f`` makes from a state: ``f(state)``
    succeeds with ``(item, next_state)``, or ``None`` to end."""

    def make_pull() -> AnyPull:
        state = initial

        def written(step: tuple[A, S] | None) -> AnyPull:
            nonlocal state
            if step is None:
                return _ENDED
            item, state = step
            return _Succeed((item,))

        return _Suspend(lambda: f(state)).flat_map(written)

    return from_pull(_Sync(make_pull))


def paginate[S, A, E = Never, R = Never](
    initial: S, f: Callable[[S], Effect[tuple[Iterable[A], Option[S]], E, R]]
) -> Stream[A, E, R]:
    """A stream of pages: ``f(state)`` succeeds with ``(items, next)``,
    where ``next`` is ``Some(state)`` for another page or ``None`` after
    this one. Empty pages write nothing."""

    def make_pull() -> AnyPull:
        state = initial
        done = False

        def loop() -> AnyPull:
            return _ENDED if done else f(state).flat_map(written)

        def written(page: tuple[Iterable[A], Option[S]]) -> AnyPull:
            nonlocal state, done
            items, following = page
            if following is None:
                done = True
            else:
                state = following.value
            chunk = tuple(items)
            return _Succeed(chunk) if chunk else _Suspend(loop)

        return _Suspend(loop)

    return from_pull(_Sync(make_pull))


def iterate[A](initial: A, f: Callable[[A], A]) -> Stream[A]:
    """The endless stream ``initial``, ``f(initial)``, ``f(f(initial))``, ..."""
    return unfold(initial, lambda a: _Sync(lambda: (a, f(a))))


def range(start: int, stop: int, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Stream[int]:
    """The integers from ``start`` up to, not including, ``stop``, as
    Python's ``range`` (Effect's ``range`` includes its end: see
    ``range_inclusive``). Chunks hold up to ``chunk_size`` (at least 1)."""
    if start >= stop:
        return empty
    size = max(1, chunk_size)

    def make_pull() -> AnyPull:
        current = start

        def pull() -> AnyPull:
            nonlocal current
            if current >= stop:
                return _ENDED
            end = min(current + size, stop)
            chunk = tuple(builtins.range(current, end))
            current = end
            return _Succeed(chunk)

        return _Suspend(pull)

    return from_pull(_Sync(make_pull))


def range_inclusive(
    minimum: int, maximum: int, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Stream[int]:
    """The integers from ``minimum`` to ``maximum``, both included
    (Effect's ``range``); empty when ``minimum > maximum``."""
    return range(minimum, maximum + 1, chunk_size=chunk_size)


# --- deferred and scoped streams -----------------------------------------------


@overload
def unwrap[A, EE = Never, RR = Never](
    eff: Effect[StreamBase[A, EE, RR], EE, Scope],
) -> Stream[A, EE, RR]: ...
@overload
def unwrap[A, EE = Never, RR = Never](
    eff: Effect[StreamBase[A, EE, RR], EE, Scope | RR],
) -> Stream[A, EE, RR]: ...
def unwrap(eff: Effect[AnyStream, Any, Any]) -> Stream[Any, Any, Any]:
    """The stream ``eff`` succeeds with, built on the first pull. ``eff``
    runs with the stream's ``Scope``, so its resources live as long as the
    stream's."""
    require_effect(eff, "eff")
    channels: Any = eff.map(lambda stream: stream._channel)
    return from_channel(channel.unwrap(channels))


@overload
def scoped[A, E](stream: StreamBase[A, E, Scope]) -> Stream[A, E]: ...
@overload
def scoped[A, E, R](stream: StreamBase[A, E, Scope | R]) -> Stream[A, E, R]: ...
def scoped(stream: AnyStream) -> Stream[Any, Any, Any]:
    """Give the stream a ``Scope`` of its own, closed as soon as it fails
    or ends (or its run ends), and remove ``Scope`` from its services."""
    require_stream(stream, "stream")
    scoped_channel: Any = channel.scoped(stream._channel)
    return Stream(scoped_channel)
