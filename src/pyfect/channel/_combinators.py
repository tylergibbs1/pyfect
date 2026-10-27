"""The work behind the mapping and sequencing ``Channel`` methods:
``map`` and ``map_effect``, ``map_done(_effect)``, ``map_input(_error)``,
sequential ``flat_map``, ``drain``, ``concat_with``, ``or_else_if_empty``,
``combine`` and ``pipe_to``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._concurrency import Concurrency
from pyfect._core import Effect, _FailCause, _FlatMap, _Map, _Succeed, _Suspend, _Sync
from pyfect.cause import fail
from pyfect.channel._base import AnyChannel, AnyPull, end_with, is_done
from pyfect.channel._channel import Channel, from_transform, transform_pull
from pyfect.channel._loop import PullLoop
from pyfect.exit import Success
from pyfect.pull import catch_done
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
        def with_outer(pull: AnyPull) -> AnyPull:
            child_pull: AnyPull | None = None
            child_scope: CloseableScope | None = None

            def next_inner(used: CloseableScope) -> AnyPull:
                nonlocal child_pull, child_scope
                child_pull = None
                if used.is_empty:
                    return make_pull
                child_scope = None
                return used.close(Success(None)).and_then(make_pull)

            def start(value: Any) -> AnyPull:
                nonlocal child_scope
                if child_scope is None:
                    child_scope = scope._fork_now()
                used = child_scope
                return f(value)._transform(upstream, used).flat_map(lambda inner: keep(inner, used))

            def keep(inner: AnyPull, used: CloseableScope) -> AnyPull:
                nonlocal child_pull
                child_pull = catch_done(inner, lambda _: next_inner(used))
                return child_pull

            make_pull: AnyPull = _FlatMap(pull, start)
            return _Suspend(lambda: make_pull if child_pull is None else child_pull)

        return self._transform(upstream, scope).map(with_outer)

    return from_transform(transform)


def concat_with(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def make() -> AnyPull:
            current: AnyPull | None = None
            forked = scope._fork_now()

            def switch(pull: AnyPull) -> AnyPull:
                nonlocal current
                current = pull
                return pull

            def next_channel(leftover: Any) -> AnyPull:
                return (
                    forked.close(Success(None))
                    .and_then(_Suspend(lambda: f(leftover)._transform(upstream, scope)))
                    .flat_map(switch)
                )

            first = self._transform(upstream, forked).flat_map(
                lambda pull: switch(catch_done(pull, next_channel))
            )
            return _Suspend(lambda: first if current is None else current)

        return _Sync(make)

    return from_transform(transform)


def or_else_if_empty(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> Channel_:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def make() -> AnyPull:
            current: AnyPull | None = None
            forked = scope._fork_now()

            def switch(pull: AnyPull) -> AnyPull:
                nonlocal current
                current = pull
                return pull

            def otherwise(leftover: Any) -> AnyPull:
                return (
                    forked.close(Success(leftover))
                    .and_then(_Suspend(lambda: f(leftover)._transform(upstream, scope)))
                    .flat_map(switch)
                )

            def first_pull(pull: AnyPull) -> AnyPull:
                def wrote(item: Any) -> Effect[Any]:
                    switch(pull)
                    return _Succeed(item)

                return switch(catch_done(_FlatMap(pull, wrote), otherwise))

            first = self._transform(upstream, forked).flat_map(first_pull)
            return _Suspend(lambda: first if current is None else current)

        return _Sync(make)

    return from_transform(transform)


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
