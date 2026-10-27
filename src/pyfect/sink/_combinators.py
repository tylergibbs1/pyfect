"""The work behind ``Sink``'s methods: mapping the value, the input and the
leftovers, sequencing sinks, and handling failures and exits.

The stream's own failures reach a sink as hidden defects (see
``pyfect.channel._upstream``), so the failure handlers here let them by.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect, _FailCause, _Gen, _Succeed, _Suspend
from pyfect.cause import Cause
from pyfect.channel._upstream import has_upstream_failure
from pyfect.clock import monotonic_nanos
from pyfect.exit import Exit, Failure, interrupt
from pyfect.scope import CloseableScope
from pyfect.sink._sink import AnySink, End, Sink, Upstream
from pyfect.sink._steps import ENDED

type AnyEffect = Effect[Any, Any, Any]
type AnyEnd = End[Any, Any]
type Sink_ = Sink[Any, Any, Any, Any, Any]


def transform_effect(self: AnySink, f: Callable[[AnyEffect], AnyEffect]) -> Sink_:
    """The sink whose run is ``f`` of this sink's run."""
    return Sink(lambda upstream, scope: f(self._transform(upstream, scope)))


def map_end(self: AnySink, f: Callable[[AnyEnd], AnyEnd]) -> Sink_:
    return transform_effect(self, lambda eff: eff.map(f))


def map_effect_end(self: AnySink, f: Callable[[AnyEnd], AnyEffect]) -> Sink_:
    return transform_effect(self, lambda eff: eff.flat_map(f))


def map_input_array(self: AnySink, f: Callable[[tuple[Any, ...]], tuple[Any, ...]]) -> Sink_:
    return Sink(lambda upstream, scope: self._transform(upstream.map(f), scope))


def map_input_array_effect(self: AnySink, f: Callable[[tuple[Any, ...]], AnyEffect]) -> Sink_:
    return Sink(lambda upstream, scope: self._transform(upstream.flat_map(f), scope))


def map_input_effect(self: AnySink, f: Callable[[Any], AnyEffect]) -> Sink_:
    return map_input_array_effect(self, lambda chunk: for_each(chunk, f).map(tuple))


def summarized(self: AnySink, summary: AnyEffect, f: Callable[[Any, Any], Any]) -> Sink_:
    def transform(upstream: Upstream[Any], scope: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEnd]:
            start = yield summary
            value, leftover = yield self._transform(upstream, scope)
            end = yield summary
            return ((value, f(start, end)), leftover)

        return _Gen(body)

    return Sink(transform)


def with_duration(self: AnySink) -> Sink_:
    return summarized(self, monotonic_nanos(), lambda start, end: (end - start) / 1_000_000_000)


class _Tracked:
    """An upstream that remembers it has failed or ended, so a sink that
    takes over after another does not pull past the end."""

    __slots__ = ("done", "pull", "upstream")

    def __init__(self, upstream: Upstream[Any]) -> None:
        self.upstream = upstream
        self.done = False
        self.pull: AnyEffect = upstream.catch_cause(self._failed)

    def _failed(self, cause: Cause[Any]) -> AnyEffect:
        self.done = True
        return _FailCause(cause)

    def rest(self) -> AnyEffect:
        return ENDED if self.done else self.upstream


def flat_map(self: AnySink, f: Callable[[Any], AnySink]) -> Sink_:
    def transform(upstream: Upstream[Any], scope: CloseableScope) -> AnyEffect:
        tracked = _Tracked(upstream)

        def then(end: AnyEnd) -> AnyEffect:
            value, pending = end

            def next_pull() -> AnyEffect:
                nonlocal pending
                if pending is not None:
                    chunk, pending = pending, None
                    return _Succeed(chunk)
                return tracked.rest()

            def keep_pending(end: AnyEnd) -> AnyEnd:
                if pending is None:
                    return end
                return (end[0], pending if end[1] is None else end[1] + pending)

            return f(value)._transform(_Suspend(next_pull), scope).map(keep_pending)

        return self._transform(tracked.pull, scope).flat_map(then)

    return Sink(transform)


def _no_leftover(value: Any) -> AnyEnd:
    return (value, None)


def catch_all(self: AnySink, f: Callable[[Any], AnyEffect]) -> Sink_:
    return transform_effect(
        self, lambda eff: eff.catch_all(lambda error: f(error).map(_no_leftover))
    )


def catch_cause(self: AnySink, f: Callable[[Cause[Any]], AnyEffect]) -> Sink_:
    def handle(cause: Cause[Any]) -> AnyEffect:
        if has_upstream_failure(cause):
            return _FailCause(cause)
        return f(cause).map(_no_leftover)

    return transform_effect(self, lambda eff: eff.catch_cause(handle))


def or_else(self: AnySink, f: Callable[[Any], AnySink]) -> Sink_:
    def transform(upstream: Upstream[Any], scope: CloseableScope) -> AnyEffect:
        tracked = _Tracked(upstream)
        return self._transform(tracked.pull, scope).catch_all(
            lambda error: f(error)._transform(_Suspend(tracked.rest), scope)
        )

    return Sink(transform)


def on_exit(self: AnySink, f: Callable[[Exit[Any, Any]], AnyEffect]) -> Sink_:
    def observed(ex: Exit[AnyEnd, Any]) -> AnyEffect:
        if isinstance(ex, Failure) and has_upstream_failure(ex.cause):
            return f(interrupt())
        return f(ex.map(lambda end: end[0]))

    return transform_effect(self, lambda eff: eff.on_exit(observed))
