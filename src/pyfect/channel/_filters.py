"""The work behind the filtering and folding ``Channel`` methods:
``filter`` and ``filter_map`` with their effect and tuple variants (a
filter returns ``Ok(value)`` to write ``value``, ``Err`` to skip),
``scan_effect``,
``map_accum`` and ``flatten_array``.

A pull that skips items pulls again from the continuation, so skipping
any number of items keeps the fiber's stack flat.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

from pyfect._concurrency import for_each
from pyfect._core import Effect, _FailCause, _FlatMap, _MatchCause, _Succeed, _Suspend
from pyfect._iterables import filter as filter_items
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull
from pyfect.channel._channel import Channel, transform_pull
from pyfect.result import Ok, Result

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]


def filter_(self: AnyChannel, predicate: Callable[[Any], bool]) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(_FlatMap(pull, _Filter(pull, predicate))))


class _Filter:
    """One run of ``filter``. Each loop here is a callable state object, not
    a closure that calls itself (that cycle would keep the pull alive after
    the run), so skipping an item allocates no more than a closure did."""

    __slots__ = ("predicate", "pull")

    def __init__(self, pull: AnyPull, predicate: Callable[[Any], bool]) -> None:
        self.pull = pull
        self.predicate = predicate

    def __call__(self, item: Any) -> AnyPull:
        return _Succeed(item) if self.predicate(item) else _FlatMap(self.pull, self)


def filter_effect(self: AnyChannel, predicate: Callable[[Any], Effect[bool, Any, Any]]) -> Channel_:
    return transform_pull(
        self, lambda pull, _: _Succeed(_FlatMap(pull, _FilterEffect(pull, predicate)))
    )


class _FilterEffect:
    __slots__ = ("predicate", "pull")

    def __init__(self, pull: AnyPull, predicate: Callable[[Any], Effect[bool, Any, Any]]) -> None:
        self.pull = pull
        self.predicate = predicate

    def __call__(self, item: Any) -> AnyPull:
        return _FlatMap(
            self.predicate(item), lambda keep: _Succeed(item) if keep else _FlatMap(self.pull, self)
        )


def filter_array(self: AnyChannel, predicate: Callable[[Any], bool]) -> Channel_:
    return transform_pull(
        self, lambda pull, _: _Succeed(_FlatMap(pull, _FilterArray(pull, predicate)))
    )


class _FilterArray:
    __slots__ = ("predicate", "pull")

    def __init__(self, pull: AnyPull, predicate: Callable[[Any], bool]) -> None:
        self.pull = pull
        self.predicate = predicate

    def __call__(self, items: tuple[Any, ...]) -> AnyPull:
        predicate = self.predicate
        kept = tuple(item for item in items if predicate(item))
        return _Succeed(kept) if kept else _FlatMap(self.pull, self)


def filter_array_effect(
    self: AnyChannel, predicate: Callable[[Any], Effect[bool, Any, Any]]
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        filtered = _FlatMap(pull, lambda items: filter_items(items, predicate))
        return _FlatMap(filtered, _UntilKept(filtered))

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


class _UntilKept:
    """Pull ``pull`` again until it gives a non-empty sequence, written as a
    tuple."""

    __slots__ = ("pull",)

    def __init__(self, pull: AnyPull) -> None:
        self.pull = pull

    def __call__(self, kept: Sequence[Any]) -> AnyPull:
        return _Succeed(tuple(kept)) if kept else _FlatMap(self.pull, self)


def filter_map(self: AnyChannel, f: Callable[[Any], Result[Any, object]]) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(_FlatMap(pull, _FilterMap(pull, f))))


class _FilterMap:
    __slots__ = ("f", "pull")

    def __init__(self, pull: AnyPull, f: Callable[[Any], Result[Any, object]]) -> None:
        self.pull = pull
        self.f = f

    def __call__(self, item: Any) -> AnyPull:
        result = self.f(item)
        return _Succeed(result.value) if isinstance(result, Ok) else _FlatMap(self.pull, self)


def filter_map_effect(
    self: AnyChannel, f: Callable[[Any], Effect[Result[Any, object], Any, Any]]
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        mapped = _FlatMap(pull, f)
        return _FlatMap(mapped, _UntilOk(mapped))

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


class _UntilOk:
    """Pull ``pull`` again until it gives ``Ok(value)``, written as ``value``."""

    __slots__ = ("pull",)

    def __init__(self, pull: AnyPull) -> None:
        self.pull = pull

    def __call__(self, result: Result[Any, object]) -> AnyPull:
        return _Succeed(result.value) if isinstance(result, Ok) else _FlatMap(self.pull, self)


def _passing(results: Sequence[Result[Any, object]]) -> tuple[Any, ...]:
    return tuple(result.value for result in results if isinstance(result, Ok))


def filter_map_array(self: AnyChannel, f: Callable[[Any], Result[Any, object]]) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(_FlatMap(pull, _FilterMapArray(pull, f))))


class _FilterMapArray:
    __slots__ = ("f", "pull")

    def __init__(self, pull: AnyPull, f: Callable[[Any], Result[Any, object]]) -> None:
        self.pull = pull
        self.f = f

    def __call__(self, items: tuple[Any, ...]) -> AnyPull:
        f = self.f
        kept = _passing([f(item) for item in items])
        return _Succeed(kept) if kept else _FlatMap(self.pull, self)


def filter_map_array_effect(
    self: AnyChannel, f: Callable[[Any], Effect[Result[Any, object], Any, Any]]
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        filtered = _FlatMap(pull, lambda items: for_each(items, f).map(_passing))
        return _FlatMap(filtered, _UntilKept(filtered))

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def scan_effect(
    self: AnyChannel, initial: Any, f: Callable[[Any, Any], Effect[Any, Any, Any]]
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        state = initial
        first = True

        def keep(new_state: Any) -> AnyPull:
            nonlocal state
            state = new_state
            return _Succeed(new_state)

        def next_state() -> AnyPull:
            nonlocal first
            if first:
                first = False
                return _Succeed(state)
            return _FlatMap(_FlatMap(pull, lambda item: f(state, item)), keep)

        return _Suspend(next_state)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def map_accum(
    self: AnyChannel,
    initial: Callable[[], Any],
    f: Callable[[Any, Any], Any],
    on_halt: Callable[[Any], Sequence[Any]] | None,
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        acc = _Accum(initial(), f, on_halt)
        return _Suspend(_MapAccum(acc, _MatchCause(pull, acc.on_failure, acc.on_success)).loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


class _Accum:
    """The state of one ``map_accum`` run. It holds no effect, so the pull
    built from its methods can sit in ``_MapAccum`` without a cycle."""

    __slots__ = ("f", "halted", "on_halt", "state")

    def __init__(
        self,
        state: Any,
        f: Callable[[Any, Any], Any],
        on_halt: Callable[[Any], Sequence[Any]] | None,
    ) -> None:
        self.state = state
        self.f = f
        self.on_halt = on_halt
        self.halted: Cause[Any] | None = None

    def on_failure(self, cause: Cause[Any]) -> Effect[Any, Any, Any]:
        self.halted = cause
        last = () if self.on_halt is None else self.on_halt(self.state)
        return _Succeed((self.state, last)) if last else _FailCause(cause)

    def on_success(self, item: Any) -> Effect[Any, Any, Any]:
        step: object = self.f(self.state, item)
        if isinstance(step, tuple):
            return _Succeed(cast("tuple[Any, Sequence[Any]]", step))
        return cast("Effect[Any, Any, Any]", step)


class _MapAccum:
    __slots__ = ("acc", "index", "pending", "pull_next")

    def __init__(self, acc: _Accum, pull_next: AnyPull) -> None:
        self.acc = acc
        self.pull_next = pull_next
        self.pending: Sequence[Any] = ()
        self.index = 0

    def __call__(self, result: tuple[Any, Sequence[Any]]) -> AnyPull:
        self.acc.state, values = result
        if len(values) == 1:
            return _Succeed(values[0])
        self.pending, self.index = values, 0
        return self.loop()

    def loop(self) -> AnyPull:
        if self.index < len(self.pending):
            item = self.pending[self.index]
            self.index += 1
            return _Succeed(item)
        if self.acc.halted is not None:
            return _FailCause(self.acc.halted)
        return _FlatMap(self.pull_next, self)


def flatten_array(self: AnyChannel) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(_Suspend(_FlattenArray(pull).loop)))


class _FlattenArray:
    __slots__ = ("index", "pending", "pull")

    def __init__(self, pull: AnyPull) -> None:
        self.pull = pull
        self.pending: Sequence[Any] = ()
        self.index = 0

    def __call__(self, items: Sequence[Any]) -> AnyPull:
        if len(items) == 1:
            return _Succeed(items[0])
        self.pending, self.index = items, 0
        return self.loop()

    def loop(self) -> AnyPull:
        if self.index < len(self.pending):
            item = self.pending[self.index]
            self.index += 1
            return _Succeed(item)
        return _FlatMap(self.pull, self)
