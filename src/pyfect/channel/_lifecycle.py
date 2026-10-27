"""The work behind ``on_start``, ``on_first``, ``on_end``, ``on_exit`` and
``with_span``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _FlatMap, _Succeed, _Suspend, _WithFiber
from pyfect.channel._base import AnyChannel, AnyPull, end_with
from pyfect.channel._channel import Channel, transform_pull
from pyfect.channel._constructors import acquire_use_release, bracket, unwrap_effect
from pyfect.channel._context import update_context_with
from pyfect.clock import Clock
from pyfect.exit import Exit
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.tracer import Span, SpanOptions
from pyfect.tracer._refs import ParentSpan, TracerTimingEnabled
from pyfect.tracer._spans import _SpanEnder, make_span

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]


def on_start(self: AnyChannel, eff: Effect[Any, Any, Any]) -> Channel_:
    return unwrap_effect(eff.as_(self))


def on_first(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> Channel_:
    def with_pull(pull: AnyPull) -> AnyPull:
        first = True

        def tap(item: Any) -> Effect[Any, Any, Any]:
            nonlocal first
            first = False
            return f(item).as_(item)

        pull_first = _FlatMap(pull, tap)
        return _Suspend(lambda: pull_first if first else pull)

    return transform_pull(self, lambda pull, _: _Succeed(with_pull(pull)))


def on_end(self: AnyChannel, eff: Effect[Any, Any, Any]) -> Channel_:
    def ended(leftover: Any) -> AnyPull:
        return eff.and_then(end_with(leftover))

    return transform_pull(self, lambda pull, _: _Succeed(catch_done(pull, ended)))


def on_exit(self: AnyChannel, f: Callable[[Exit[Any, Any]], Effect[Any, Any, Any]]) -> Channel_:
    def build(upstream: AnyPull, scope: CloseableScope, forked: CloseableScope) -> Effect[AnyPull]:
        return forked.add_finalizer(f).and_then(self._transform(upstream, scope))

    return bracket(build)


def with_span(self: AnyChannel, name: str, options: SpanOptions) -> Channel_:
    def use(span: Span) -> Channel_:
        return update_context_with(self, lambda ctx: ctx.add(ParentSpan, span))

    def end(span: Span, ex: Exit[Any, Any]) -> Effect[None]:
        def run(fiber: Any) -> Effect[None]:
            _SpanEnder(span, fiber.get_ref(Clock), fiber.get_ref(TracerTimingEnabled))(ex)
            return _Succeed(None)

        return _WithFiber(run)

    channel: Channel_ = acquire_use_release(make_span(name, **options), use, end)
    return channel
