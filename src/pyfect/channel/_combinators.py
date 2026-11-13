"""The work behind the mapping and sequencing ``Channel`` methods:
``map`` and ``map_effect``, ``map_done(_effect)``, ``map_input(_error)``,
sequential ``flat_map``, ``drain``, ``concat_with``, ``or_else_if_empty``,
``combine`` and ``pipe_to``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from pyfect._concurrency import Concurrency
from pyfect._core import (
    Effect,
    _FailCause,
    _FlatMap,
    _Map,
    _MatchCause,
    _Succeed,
    _Suspend,
    _Sync,
)
from pyfect.cause import Cause, fail
from pyfect.channel._base import AnyChannel, AnyPull, end_with, is_done
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._loop import PullLoop
from pyfect.exit import Success
from pyfect.pull import catch_done, filter_done
from pyfect.result import Ok
from pyfect.scope import CloseableScope

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]


def is_sequential(concurrency: Concurrency) -> bool:
    """Whether ``concurrency`` runs one at a time (Effect's
    ``concurrencyIsSequential``)."""
    return concurrency is None or (concurrency != "unbounded" and concurrency <= 1)


UNBOUNDED = 2**62
"""The number of fibers ``"unbounded"`` concurrency allows."""


def permits_of(concurrency: Concurrency) -> int:
    """How many fibers ``concurrency`` lets run at once."""
    if concurrency is None:
        return 1
    return UNBOUNDED if concurrency == "unbounded" else max(1, concurrency)


def map_(self: AnyChannel, f: Callable[[Any], Any]) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(_Map(pull, f)))


def map_effect(
    self: AnyChannel,
    f: Callable[[Any], Effect[Any, Any, Any]],
    concurrency: Concurrency,
    *,
    unordered: bool = False,
) -> Channel_:
    if is_sequential(concurrency):
        return transform_pull(self, lambda pull, _: _Succeed(_FlatMap(pull, f)))
    from pyfect.channel import _concurrent_map

    return _concurrent_map.map_effect_concurrent(self, f, concurrency, unordered=unordered)


def map_done(self: AnyChannel, f: Callable[[Any], Any]) -> Channel_:
    return transform_pull(
        self, lambda pull, _: _Succeed(catch_done(pull, lambda done: end_with(f(done))))
    )


def map_done_effect(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> Channel_:
    return transform_pull(
        self,
        lambda pull, _: _Succeed(catch_done(pull, lambda done: f(done).flat_map(end_with))),
    )


def map_input(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> Channel_:
    return Channel(lambda upstream, scope: self._transform(_FlatMap(upstream, f), scope))


def map_input_error(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> Channel_:
    def mapped(error: Any) -> Effect[Any, Any, Any]:
        if is_done(error):
            return _FailCause(fail(error))
        return f(error).flat_map(lambda e: _FailCause(fail(e)))

    return Channel(lambda upstream, scope: self._transform(upstream.catch_all(mapped), scope))


def drain(self: AnyChannel) -> Channel_:
    return transform_pull(self, lambda pull, _: _Succeed(PullLoop(pull, _ignore)))


def _ignore(_: object) -> None:
    return None


def flat_map(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> Channel_:
    """One inner channel at a time, each in a child scope closed when it
    ends; a child scope left open without finalizers is reused."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return self._transform(upstream, scope).map(
            lambda pull: _Suspend(_FlatMapRun(f, upstream, scope, pull).next_pull)
        )

    return from_transform(transform)


class _FlatMapRun:
    """One run of ``flat_map``: ``inner`` is the inner channel's pull while
    it runs, in ``used``; ``child_scope`` is the child scope to reuse. It is
    called with the inner pull's failure."""

    __slots__ = ("child_scope", "f", "inner", "pull", "scope", "upstream", "used")

    def __init__(
        self,
        f: Callable[[Any], AnyChannel],
        upstream: AnyPull,
        scope: CloseableScope,
        pull: AnyPull,
    ) -> None:
        self.f = f
        self.upstream = upstream
        self.scope = scope
        self.pull = pull
        self.inner: AnyPull | None = None
        self.child_scope: CloseableScope | None = None
        self.used: CloseableScope = scope

    def next_pull(self) -> AnyPull:
        inner = self.inner
        return _FlatMap(self.pull, self.start) if inner is None else _MatchCause(inner, self, None)

    def start(self, value: Any) -> AnyPull:
        if self.child_scope is None:
            self.child_scope = self.scope.fork_unsafe()
        used = self.child_scope
        return self.f(value)._transform(self.upstream, used).flat_map(partial(self.keep, used))

    def keep(self, used: CloseableScope, inner: AnyPull) -> AnyPull:
        self.inner, self.used = inner, used
        return _MatchCause(inner, self, None)

    def __call__(self, cause: Cause[Any]) -> AnyPull:
        found = filter_done(cause)
        return self._next_inner() if isinstance(found, Ok) else _FailCause(found.error)

    def _next_inner(self) -> AnyPull:
        used = self.used
        self.inner = None
        make_pull = _FlatMap(self.pull, self.start)
        if used.is_empty:
            return make_pull
        self.child_scope = None
        return used.close(Success(None)).and_then(make_pull)


def concat_with(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def make() -> AnyPull:
            run = _Concat(f, upstream, scope)
            first = self._transform(upstream, run.forked).flat_map(run.started)
            return _Suspend(lambda: run.next_pull(first))

        return _Sync(make)

    return from_transform(transform)


def or_else_if_empty(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def make() -> AnyPull:
            run = _OrElseIfEmpty(f, upstream, scope)
            first = self._transform(upstream, run.forked).flat_map(run.started)
            return _Suspend(lambda: run.next_pull(first))

        return _Sync(make)

    return from_transform(transform)


class _Concat:
    """One run of ``concat_with``: the first channel's pull until it is done,
    then ``f(leftover)``'s. It keeps the first pull bare and wraps it with
    itself (the done handler) on each pull: a stored wrapped pull would refer
    back here, a cycle that kept the run alive after it ended."""

    __slots__ = ("current", "f", "first", "forked", "scope", "upstream")

    def __init__(
        self,
        f: Callable[[Any], AnyChannel],
        upstream: AnyPull,
        scope: CloseableScope,
    ) -> None:
        self.f = f
        self.upstream = upstream
        self.scope = scope
        self.forked = scope.fork_unsafe()
        self.first: AnyPull | None = None
        self.current: AnyPull | None = None

    def started(self, pull: AnyPull) -> AnyPull:
        self.first = pull
        return self.wrapped(pull)

    def wrapped(self, pull: AnyPull) -> AnyPull:
        return _MatchCause(pull, self, None)

    def next_pull(self, first: AnyPull) -> AnyPull:
        if self.current is not None:
            return self.current
        return first if self.first is None else self.wrapped(self.first)

    def switch(self, pull: AnyPull) -> AnyPull:
        self.current = pull
        return pull

    def close_with(self, leftover: Any) -> Success[Any]:
        del leftover
        return Success(None)

    def __call__(self, cause: Cause[Any]) -> AnyPull:
        found = filter_done(cause)
        if not isinstance(found, Ok):
            return _FailCause(found.error)
        leftover = found.value.value
        return (
            self.forked.close(self.close_with(leftover))
            .and_then(_Suspend(lambda: self.f(leftover)._transform(self.upstream, self.scope)))
            .flat_map(self.switch)
        )


class _OrElseIfEmpty(_Concat):
    """One run of ``or_else_if_empty``: like ``_Concat``, but only until the
    first channel writes, which makes its bare pull the current one."""

    __slots__ = ()

    def wrapped(self, pull: AnyPull) -> AnyPull:
        return _MatchCause(_FlatMap(pull, self.wrote), self, None)

    def wrote(self, item: Any) -> Effect[Any]:
        self.current = self.first
        return _Succeed(item)

    def close_with(self, leftover: Any) -> Success[Any]:
        return Success(leftover)


def combine(
    self: AnyChannel,
    that: AnyChannel,
    initial: Callable[[], Any],
    f: Callable[[Any, AnyPull, AnyPull], Effect[tuple[Any, Any], Any, Any]],
) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def with_pulls(left: AnyPull, right: AnyPull) -> AnyPull:
            state = initial()

            def step(result: tuple[Any, Any]) -> Any:
                nonlocal state
                value, state = result
                return value

            return _Suspend(lambda: _Map(f(state, left, right), step))

        return self._transform(upstream, scope).flat_map(
            lambda left: that._transform(upstream, scope).map(lambda right: with_pulls(left, right))
        )

    return from_transform(transform)


def pipe_to(self: AnyChannel, that: AnyChannel) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return self._transform(upstream, scope).flat_map(lambda pull: that._transform(pull, scope))

    return from_transform(transform)
