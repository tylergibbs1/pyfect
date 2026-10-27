"""The work behind the filtering and folding ``Channel`` methods:
``filter`` and its effect and tuple variants, ``scan_effect``,
``map_accum`` and ``flatten_array``.

A pull that skips items pulls again from the continuation, so skipping
any number of items keeps the fiber's stack flat.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

from pyfect._core import Effect, _FailCause, _FlatMap, _MatchCause, _Succeed, _Suspend
from pyfect._iterables import filter as filter_items
from pyfect.cause import Cause
from pyfect.channel._base import AnyChannel, AnyPull
from pyfect.channel._channel import Channel, transform_pull

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]


def filter_(self: AnyChannel, predicate: Callable[[Any], bool]) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        def loop(item: Any) -> AnyPull:
            return _Succeed(item) if predicate(item) else _FlatMap(pull, loop)

        return _FlatMap(pull, loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def filter_effect(self: AnyChannel, predicate: Callable[[Any], Effect[bool, Any, Any]]) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        def loop(item: Any) -> AnyPull:
            return _FlatMap(
                predicate(item), lambda keep: _Succeed(item) if keep else _FlatMap(pull, loop)
            )

        return _FlatMap(pull, loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def filter_array(self: AnyChannel, predicate: Callable[[Any], bool]) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        def loop(items: tuple[Any, ...]) -> AnyPull:
            kept = tuple(item for item in items if predicate(item))
            return _Succeed(kept) if kept else _FlatMap(pull, loop)

        return _FlatMap(pull, loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def filter_array_effect(
    self: AnyChannel, predicate: Callable[[Any], Effect[bool, Any, Any]]
) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        filtered = _FlatMap(pull, lambda items: filter_items(items, predicate))

        def loop(kept: list[Any]) -> AnyPull:
            return _Succeed(tuple(kept)) if kept else _FlatMap(filtered, loop)

        return _FlatMap(filtered, loop)

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
        state = initial()
        pending: Sequence[Any] = ()
        index = 0
        halted: Cause[Any] | None = None

        def on_failure(cause: Cause[Any]) -> Effect[Any, Any, Any]:
            nonlocal halted
            halted = cause
            last = () if on_halt is None else on_halt(state)
            return _Succeed((state, last)) if last else _FailCause(cause)

        def on_success(item: Any) -> Effect[Any, Any, Any]:
            step: object = f(state, item)
            if isinstance(step, tuple):
                return _Succeed(cast("tuple[Any, Sequence[Any]]", step))
            return cast("Effect[Any, Any, Any]", step)

        pull_next = _MatchCause(pull, on_failure, on_success)

        def written(result: tuple[Any, Sequence[Any]]) -> AnyPull:
            nonlocal state, pending, index
            state, values = result
            if len(values) == 1:
                return _Succeed(values[0])
            pending, index = values, 0
            return loop()

        def loop() -> AnyPull:
            nonlocal pending, index
            if index < len(pending):
                item = pending[index]
                index += 1
                return _Succeed(item)
            if halted is not None:
                return _FailCause(halted)
            return _FlatMap(pull_next, written)

        return _Suspend(loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def flatten_array(self: AnyChannel) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        pending: Sequence[Any] = ()
        index = 0

        def refill(items: Sequence[Any]) -> AnyPull:
            nonlocal pending, index
            if len(items) == 1:
                return _Succeed(items[0])
            pending, index = items, 0
            return loop()

        def loop() -> AnyPull:
            nonlocal index
            if index < len(pending):
                item = pending[index]
                index += 1
                return _Succeed(item)
            return _FlatMap(pull, refill)

        return _Suspend(loop)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))
