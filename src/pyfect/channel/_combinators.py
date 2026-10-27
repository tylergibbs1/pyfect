"""The ``Channel`` methods that transform a channel: ``map``, ``map_done``,
``map_done_effect``, ``concat_with`` and ``pipe_to``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _FailCause, _Map, _Succeed, _Suspend, _Sync
from pyfect.cause import fail
from pyfect.channel._channel import AnyPull, Channel, from_transform, transform_pull
from pyfect.errors import Done
from pyfect.exit import Success
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope

type AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


def map_(self: AnyChannel, f: Callable[[Any], Any]) -> AnyChannel:
    return transform_pull(self, lambda pull, _: _Succeed(_Map(pull, f)))


def _end_with(leftover: object) -> Effect[Any, Any, Any]:
    return _FailCause(fail(Done(leftover)))


def map_done(self: AnyChannel, f: Callable[[Any], Any]) -> AnyChannel:
    return transform_pull(
        self, lambda pull, _: _Succeed(catch_done(pull, lambda done: _end_with(f(done))))
    )


def map_done_effect(self: AnyChannel, f: Callable[[Any], Effect[Any, Any, Any]]) -> AnyChannel:
    return transform_pull(
        self,
        lambda pull, _: _Succeed(catch_done(pull, lambda done: f(done).flat_map(_end_with))),
    )


def concat_with(self: AnyChannel, f: Callable[[Any], AnyChannel]) -> AnyChannel:
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


def pipe_to(self: AnyChannel, that: AnyChannel) -> AnyChannel:
    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        return self._transform(upstream, scope).flat_map(lambda pull: that._transform(pull, scope))

    return from_transform(transform)
