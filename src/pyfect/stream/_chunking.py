"""The work behind ``Stream``'s chunk, window, scan and neighbour methods."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from pyfect._core import Effect, _FailCause, _FlatMap, _MatchCause, _Succeed, _Suspend
from pyfect.cause import Cause
from pyfect.channel import transform_pull
from pyfect.channel._base import end_with
from pyfect.option import Some
from pyfect.stream._base import AnyStream
from pyfect.stream._mapping import map_chunks, one
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]
type OnHalt = Callable[[Any], Sequence[Any]] | None

_ENDED: AnyEffect = end_with(None)


def size_of(n: int) -> int:
    """Effect's ``Count.normalizeNonEmpty`` for an ``int``: at least one."""
    return max(1, n)


def _pulling(self: AnyStream, build: Callable[[AnyEffect], AnyEffect]) -> AnyStream_:
    return Stream(transform_pull(self._channel, lambda pull, _: _Succeed(build(pull))))


def _as_chunks(values: Sequence[Any]) -> list[Chunk]:
    return [tuple(values)] if values else []


# --- chunks and windows -------------------------------------------------------


def rechunk(self: AnyStream, size: int) -> AnyStream_:
    target = size_of(size)

    def build(pull: AnyEffect) -> AnyEffect:
        state = _Rechunk(pull, target)
        return _MatchCause(_Suspend(state.loop), state.flush, None)

    return _pulling(self, build)


class _Rechunk:
    """One run of ``rechunk``: a loop on a state object, not closures that
    reach each other (that cycle would keep the pull alive after the run)."""

    __slots__ = ("held", "pull", "stopped", "target")

    def __init__(self, pull: AnyEffect, target: int) -> None:
        self.pull = pull
        self.target = target
        self.held: list[Any] = []
        self.stopped: Cause[Any] | None = None

    def emit(self) -> AnyEffect:
        held = self.held
        out = tuple(held[: self.target])
        del held[: self.target]
        return _Succeed(out)

    def got(self, chunk: Chunk) -> AnyEffect:
        if not self.held and len(chunk) == self.target:
            return _Succeed(chunk)
        self.held.extend(chunk)
        return self.loop()

    def loop(self) -> AnyEffect:
        if self.stopped is not None:
            return _FailCause(self.stopped)
        return self.emit() if len(self.held) >= self.target else _FlatMap(self.pull, self.got)

    def flush(self, cause: Cause[Any]) -> AnyEffect:
        # The upstream's end or failure: emit what is held first, then stop with it.
        if not self.held:
            return _FailCause(cause)
        self.stopped = cause
        out = tuple(self.held)
        self.held.clear()
        return _Succeed(out)


def accumulate(self: AnyStream) -> AnyStream_:
    def step(held: Chunk, chunk: Chunk) -> tuple[Chunk, list[Chunk]]:
        combined = held + chunk
        return combined, [(combined,)]

    return Stream(self._channel.map_accum(tuple, step))


def sliding_size(self: AnyStream, size: int, step: int) -> AnyStream_:
    window = size_of(size)
    stride = size_of(step)

    def build(upstream: AnyEffect) -> AnyEffect:
        sliding = _Sliding(upstream, window, stride)
        pull = _MatchCause(upstream, sliding.on_failure, sliding)
        return _Suspend(lambda: pull if sliding.stopped is None else _FailCause(sliding.stopped))

    return _pulling(self, build)


class _Sliding:
    """One run of ``sliding_size``, called with each chunk."""

    __slots__ = ("emitted", "held", "skip", "stopped", "stride", "upstream", "window")

    def __init__(self, upstream: AnyEffect, window: int, stride: int) -> None:
        self.upstream = upstream
        self.window = window
        self.stride = stride
        self.held: deque[Any] = deque()
        self.stopped: Cause[Any] | None = None
        self.emitted = False
        self.skip = 0

    def _drop_front(self, n: int) -> None:
        held = self.held
        for _ in range(min(n, len(held))):
            held.popleft()

    def __call__(self, chunk: Chunk) -> AnyEffect:
        held, window, stride = self.held, self.window, self.stride
        held.extend(chunk)
        if self.skip > 0:
            length = len(held)
            self._drop_front(self.skip)
            self.skip = max(0, self.skip - length)
        if len(held) < window:
            return _MatchCause(self.upstream, self.on_failure, self)
        self.emitted = True
        windows: list[Chunk] = []
        while len(held) >= window:
            windows.append(tuple(held[i] for i in range(window)))
            length = len(held)
            self._drop_front(stride)
            self.skip = max(0, stride - length)
        return _Succeed(tuple(windows))

    def on_failure(self, cause: Cause[Any]) -> AnyEffect:
        held = self.held
        # A full window already moved the buffer on by the step.
        if not held or (self.emitted and len(held) <= self.window - self.stride):
            return _FailCause(cause)
        self.stopped = cause
        rest = tuple(held)
        held.clear()
        return _Succeed((rest,))


def split(self: AnyStream, predicate: Callable[[Any], bool]) -> AnyStream_:
    def step(run: list[Any], chunk: Chunk) -> tuple[list[Any], list[Chunk]]:
        out: list[Chunk] = []
        for item in chunk:
            if not predicate(item):
                run.append(item)
            elif run:
                out.append(tuple(run))
                run = []
        return run, [tuple(out)] if out else []

    def on_halt(run: list[Any]) -> list[Chunk]:
        return [(tuple(run),)] if run else []

    return Stream(self._channel.map_accum(list[Any], step, on_halt=on_halt))


# --- scans and accumulating maps ----------------------------------------------


def scan(self: AnyStream, initial: Callable[[], Any], f: Callable[[Any, Any], Any]) -> AnyStream_:
    from pyfect.stream._concat import concat
    from pyfect.stream._constructors import succeed, suspend

    def states(state: Any, chunk: Chunk) -> tuple[Any, list[Chunk]]:
        out: list[Any] = []
        for item in chunk:
            state = f(state, item)
            out.append(state)
        return state, [tuple(out)]

    def make() -> AnyStream_:
        seed = initial()
        return concat(succeed(seed), Stream(self._channel.map_accum(lambda: seed, states)))

    return suspend(make)


def scan_effect(
    self: AnyStream, initial: Callable[[], Any], f: Callable[[Any, Any], AnyEffect]
) -> AnyStream_:
    from pyfect.stream._constructors import suspend

    return suspend(lambda: Stream(self._channel.flatten_array().scan_effect(initial(), f).map(one)))


def _halting(on_halt: OnHalt) -> OnHalt:
    if on_halt is None:
        return None
    return lambda state: _as_chunks(on_halt(state))


def map_accum(
    self: AnyStream,
    initial: Callable[[], Any],
    f: Callable[[Any, Any], tuple[Any, Sequence[Any]]],
    on_halt: OnHalt,
    *,
    array: bool,
) -> AnyStream_:
    def per_item(state: Any, chunk: Chunk) -> tuple[Any, list[Chunk]]:
        out: list[Any] = []
        for item in chunk:
            state, values = f(state, item)
            out.extend(values)
        return state, _as_chunks(out)

    def per_chunk(state: Any, chunk: Chunk) -> tuple[Any, list[Chunk]]:
        state, values = f(state, chunk)
        return state, _as_chunks(values)

    step = per_chunk if array else per_item
    return Stream(self._channel.map_accum(initial, step, on_halt=_halting(on_halt)))


def map_accum_effect(
    self: AnyStream,
    initial: Callable[[], Any],
    f: Callable[[Any, Any], AnyEffect],
    on_halt: OnHalt,
    *,
    array: bool,
) -> AnyStream_:
    def wrap(result: tuple[Any, Sequence[Any]]) -> tuple[Any, list[Chunk]]:
        state, values = result
        return state, _as_chunks(values)

    source = self._channel if array else self._channel.flatten_array()
    accumulated: Any = source.map_accum(
        initial, lambda state, a: f(state, a).map(wrap), on_halt=_halting(on_halt)
    )
    return Stream(accumulated)


# --- positions and neighbours -------------------------------------------------


def zip_with_index(self: AnyStream) -> AnyStream_:
    def make() -> Callable[[Chunk], Chunk]:
        index = 0

        def pair(chunk: Chunk) -> Chunk:
            nonlocal index
            start = index
            index += len(chunk)
            return tuple(zip(chunk, range(start, index), strict=True))

        return pair

    return map_chunks(self, make)


class _Previous:
    """The last item seen, if any (``Option`` cannot hold ``None`` apart)."""

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: Some[Any] | None = None


def zip_with_next(self: AnyStream) -> AnyStream_:
    def step(last: _Previous, chunk: Chunk) -> tuple[_Previous, list[Chunk]]:
        items = iter(chunk)
        if last.value is None:
            last.value = Some(next(items))
        pairs: list[Any] = []
        for item in items:
            following = Some(item)
            pairs.append((last.value.value, following))
            last.value = following
        return last, _as_chunks(pairs)

    def on_halt(last: _Previous) -> list[Chunk]:
        return [] if last.value is None else [((last.value.value, None),)]

    return Stream(self._channel.map_accum(_Previous, step, on_halt=on_halt))


def zip_with_previous(self: AnyStream) -> AnyStream_:
    def make() -> Callable[[Chunk], Chunk]:
        previous: Some[Any] | None = None

        def pair(chunk: Chunk) -> Chunk:
            nonlocal previous
            out: list[Any] = []
            for item in chunk:
                out.append((previous, item))
                previous = Some(item)
            return tuple(out)

        return pair

    return map_chunks(self, make)


def zip_with_previous_and_next(self: AnyStream) -> AnyStream_:
    def step(state: list[Any], chunk: Chunk) -> tuple[list[Any], list[Chunk]]:
        # state: [previous (Option), current (Option)]
        items = iter(chunk)
        if state[1] is None:
            state[1] = Some(next(items))
        out: list[Any] = []
        for item in items:
            current = state[1].value
            state[1] = Some(item)
            out.append((state[0], current, state[1]))
            state[0] = Some(current)
        return state, _as_chunks(out)

    def on_halt(state: list[Any]) -> list[Chunk]:
        return [] if state[1] is None else [((state[0], state[1].value, None),)]

    return Stream(self._channel.map_accum(lambda: [None, None], step, on_halt=on_halt))
