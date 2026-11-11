"""Sink constructors: from transforms, channels, effects and stream
pipelines; values and failures; and sinks writing to queues and pubsubs."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect import effect as _effect
from pyfect._core import Effect, _Locally, _Succeed, _Sync
from pyfect._effect_args import require_effect
from pyfect.cause import Cause
from pyfect.channel import Channel
from pyfect.channel._base import end_with, require_channel
from pyfect.channel._loop import PullLoop
from pyfect.errors import Done
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope, Scope
from pyfect.sink._combinators import map_end, with_duration
from pyfect.sink._for_each import for_each_array
from pyfect.sink._sink import End, Sink, Upstream, require_sink

if TYPE_CHECKING:
    from pyfect.pubsub import PubSub
    from pyfect.queue import Enqueue
    from pyfect.stream import Stream

type AnyEffect = Effect[Any, Any, Any]


def _ignore(_: object) -> None:
    return None


_END_VOID: Effect[End[None]] = _Succeed((None, None))


def from_transform[In, A, L = Never, E = Never, R = Never](
    transform: Callable[[Upstream[In], CloseableScope], Effect[End[A, L], E, R]],
) -> Sink[A, In, L, E, R]:
    """A sink from ``transform(upstream, scope)``: an effect that pulls
    non-empty tuples from ``upstream`` (which ends with ``Done()``) and
    succeeds with the sink's ``End``. Resources go in ``scope``."""
    return Sink(transform)


def to_channel[A, In, L, E, R](
    sink: Sink[A, In, L, E, R],
) -> Channel[Never, E, End[A, L], tuple[In, ...], Never, None, R]:
    """The channel that reads what the sink reads and ends with its
    ``End``."""
    require_sink(sink, "sink")

    def transform(upstream: Any, scope: CloseableScope) -> AnyEffect:
        return _Succeed(sink._transform(upstream, scope).flat_map(end_with))

    built: Channel[Any, Any, Any, Any, Any, Any, Any] = Channel(transform)
    return built


def from_channel[A, In, L = Never, E = Never, R = Never](
    channel: Channel[Never, E, End[A, L], tuple[In, ...], Never, None, R],
) -> Sink[A, In, L, E, R]:
    """The sink that feeds its input to ``channel`` and ends with the
    ``End`` the channel ends with."""
    require_channel(channel, "channel")

    def transform(upstream: Upstream[Any], scope: CloseableScope) -> AnyEffect:
        drained = channel._transform(upstream, scope).flat_map(lambda pull: PullLoop(pull, _ignore))
        return catch_done(drained, _Succeed)

    return Sink(transform)


@overload
def make[In, B, E = Never](
    f: Callable[[Stream[In]], Effect[B, E, Scope]],
) -> Sink[B, In, Never, E]: ...
@overload
def make[In, B, E = Never, R = Never](
    f: Callable[[Stream[In]], Effect[B, E, Scope | R]],
) -> Sink[B, In, Never, E, R]: ...
def make[In, B, E = Never, R = Never](
    f: Callable[[Stream[In]], Effect[B, E, Scope | R]],
) -> Sink[B, In, Never, E, R]:
    """A sink from a stream pipeline: ``f`` gets the sink's input as a
    ``Stream`` and returns the effect whose value is the sink's (Effect's
    ``Sink.make<In>()(...)``). The effect runs with the sink's ``Scope``::

        sink.make(lambda s: s.run_sum())
    """
    from pyfect.stream import from_pull

    def transform(upstream: Upstream[Any], scope: CloseableScope) -> AnyEffect:
        run = f(from_pull(_Succeed(upstream))).map(lambda value: (value, None))
        return _Locally(run, lambda ctx: ctx.add(Scope, scope))

    return Sink(transform)


def from_effect_end[A, L = Never, E = Never, R = Never](
    eff: Effect[End[A, L], E, R],
) -> Sink[A, object, L, E, R]:
    """A sink that reads nothing and ends with what ``eff`` succeeds
    with."""
    require_effect(eff, "eff")
    return Sink(lambda _upstream, _scope: eff)


def from_effect[A, E = Never, R = Never](eff: Effect[A, E, R]) -> Sink[A, object, Never, E, R]:
    """A sink that reads nothing and succeeds with ``eff``'s value."""
    require_effect(eff, "eff")
    return from_effect_end(eff.map(lambda value: (value, None)))


def succeed[A, L = Never](value: A, leftover: tuple[L, ...] | None = None) -> Sink[A, object, L]:
    """A sink that reads nothing and succeeds with ``value``, leaving
    ``leftover`` over (an empty tuple is no leftover)."""
    end: End[A, L] = (value, leftover or None)
    return from_effect_end(_Succeed(end))


def sync[A](thunk: Callable[[], A]) -> Sink[A]:
    """A sink that reads nothing and succeeds with ``thunk()``, called
    each time it runs."""
    return from_effect_end(_Sync(lambda: (thunk(), None)))


def suspend[A, In, L, E, R](thunk: Callable[[], Sink[A, In, L, E, R]]) -> Sink[A, In, L, E, R]:
    """The sink ``thunk()`` returns, built each time it runs."""
    return Sink(lambda upstream, scope: thunk()._transform(upstream, scope))


def fail[E](error: E) -> Sink[Never, object, Never, E]:
    """A sink that reads nothing and fails with ``error``."""
    return from_effect_end(_effect.fail(error))


def fail_sync[E](thunk: Callable[[], E]) -> Sink[Never, object, Never, E]:
    """A sink that reads nothing and fails with ``thunk()``."""
    return from_effect_end(_effect.fail_sync(thunk))


def fail_cause[E](cause: Cause[E]) -> Sink[Never, object, Never, E]:
    """A sink that reads nothing and fails with ``cause``."""
    return from_effect_end(_effect.fail_cause(cause))


def fail_cause_sync[E](thunk: Callable[[], Cause[E]]) -> Sink[Never, object, Never, E]:
    """A sink that reads nothing and fails with the cause ``thunk()``."""
    return from_effect_end(_effect.fail_cause_sync(thunk))


def die(defect: BaseException) -> Sink[Never]:
    """A sink that reads nothing and dies with ``defect``."""
    return from_effect_end(_effect.die(defect))


never: Sink[Never] = from_effect_end(_effect.never)
"""A sink that reads nothing and never ends."""


def _drain(upstream: Upstream[object], _scope: CloseableScope) -> Effect[End[None]]:
    return catch_done(PullLoop(upstream, _ignore), lambda _: _END_VOID)


drain: Sink[None] = Sink(_drain)
"""A sink that reads all of its input and succeeds with ``None``."""

timed: Sink[float] = map_end(with_duration(drain), lambda end: (end[0][1], None))
"""A sink that reads all of its input and succeeds with how long that
took, in seconds."""


def from_queue[A](queue: Enqueue[A, Done]) -> Sink[None, A]:
    """A sink that offers its input to ``queue`` and ends the queue when the
    input ends."""

    def transform(upstream: Upstream[A], _scope: CloseableScope) -> AnyEffect:
        offered = PullLoop(upstream.flat_map(queue.offer_all), _ignore)
        return catch_done(offered, lambda _: queue.end().and_then(_END_VOID))

    return Sink(transform)


def from_pubsub[A](pubsub: PubSub[A]) -> Sink[None, A]:
    """A sink that publishes its input to ``pubsub``."""
    return for_each_array(pubsub.publish_all)
