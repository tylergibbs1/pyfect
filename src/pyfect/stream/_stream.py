"""The ``Stream`` type and the functions between streams, channels and
pulls.

A ``Stream[A, E, R]`` is a ``Channel`` writing non-empty tuples of ``A``
(Effect v4's ``Stream`` over ``Channel<NonEmptyReadonlyArray<A>>``).
Nothing runs until a run function or ``to_pull`` builds the channel's
pull. ``Stream``'s methods come in groups, one module each (see
``pyfect.stream._base``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect._effect_args import require_effect
from pyfect.channel import Channel, from_transform, from_transform_bracket
from pyfect.channel import from_pull as channel_from_pull
from pyfect.channel._base import require_channel
from pyfect.stream._base import A_co, E_co, R_co, StreamBase, StreamChannel, require_stream
from pyfect.stream._bridge_methods import BridgeMethods
from pyfect.stream._channel_methods import ChannelMethods
from pyfect.stream._chunk_methods import ChunkMethods
from pyfect.stream._error_methods import ErrorMethods
from pyfect.stream._fanout_methods import FanOutMethods
from pyfect.stream._filter_methods import FilterMethods
from pyfect.stream._map_methods import MapMethods
from pyfect.stream._run_methods import RunMethods
from pyfect.stream._service_methods import ServiceMethods
from pyfect.stream._sink_methods import SinkMethods
from pyfect.stream._timing_methods import TimingMethods
from pyfect.stream._zip_methods import ZipMethods

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.errors import Done
    from pyfect.pull import Pull
    from pyfect.scope import CloseableScope


class Stream(
    MapMethods[A_co, E_co, R_co],
    FilterMethods[A_co, E_co, R_co],
    ChunkMethods[A_co, E_co, R_co],
    ZipMethods[A_co, E_co, R_co],
    ErrorMethods[A_co, E_co, R_co],
    TimingMethods[A_co, E_co, R_co],
    ServiceMethods[A_co, E_co, R_co],
    RunMethods[A_co, E_co, R_co],
    SinkMethods[A_co, E_co, R_co],
    FanOutMethods[A_co, E_co, R_co],
    BridgeMethods[A_co, E_co, R_co],
    ChannelMethods[A_co, E_co, R_co],
):
    """``Stream[A, E, R]``: writes items of type ``A`` in non-empty tuples
    (chunks), then fails with ``E`` or ends; needs the services ``R``.

    Build streams with the functions in ``pyfect.stream``; methods that
    keep or add to the type parameters are here. Combinators that remove
    something from a type (``scoped``, ``catch_tag``, ``catch_if``,
    ``provide*``, ``update_context``) are
    functions in ``pyfect.stream``, used with ``.pipe``.
    """

    __slots__ = ()


def from_channel[A, E = Never, R = Never](
    channel: Channel[tuple[A, ...], E, None, object, object, object, R],
) -> Stream[A, E, R]:
    """The stream of the items in the tuples ``channel`` writes. Each tuple
    must be non-empty."""
    require_channel(channel, "channel")
    return Stream(channel)


def to_channel[A, E, R](stream: StreamBase[A, E, R]) -> StreamChannel[A, E, R]:
    """The channel a stream is made of: it writes the stream's chunks."""
    require_stream(stream, "stream")
    return stream._channel


@overload
def from_pull[A, EE = Never, RR = Never](
    make: Effect[Effect[tuple[A, ...], Done, RR], EE, RR],
) -> Stream[A, EE, RR]: ...
@overload
def from_pull[A, EE = Never, RR = Never](
    make: Effect[Effect[tuple[A, ...], EE | Done, RR], EE, RR],
) -> Stream[A, EE, RR]: ...
def from_pull(make: Effect[Any, Any, Any]) -> Stream[Any, Any, Any]:
    """A stream whose pull ``make`` builds each time it runs. The pull
    succeeds with a non-empty tuple, fails, or ends with ``Done()``."""
    require_effect(make, "make")
    return Stream(channel_from_pull(make))


@overload
def transform_pull[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E], CloseableScope],
        Effect[Effect[tuple[B, ...], Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]: ...
@overload
def transform_pull[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E], CloseableScope],
        Effect[Effect[tuple[B, ...], EE | Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]: ...
def transform_pull[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E], CloseableScope],
        Effect[Effect[tuple[B, ...], EE | Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]:
    """A stream whose pull is ``f(pull, scope)`` of ``stream``'s pull. The
    upstream pull is built in the new stream's scope."""
    require_stream(stream, "stream")
    channel = stream._channel
    # ``f`` is given a pull without requirements, as in Effect.
    run: Callable[[Any, CloseableScope], Effect[Any, Any, Any]] = f

    def transform(_upstream: Any, scope: CloseableScope) -> Effect[Any, Any, Any]:
        return channel.to_pull_scoped(scope).flat_map(lambda pull: run(pull, scope))

    built: Channel[Any, Any, Any, Any, Any, Any, Any] = from_transform(transform)
    return Stream(built)


@overload
def transform_pull_bracket[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E, None, RR], CloseableScope, CloseableScope],
        Effect[Effect[tuple[B, ...], Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]: ...
@overload
def transform_pull_bracket[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E, None, RR], CloseableScope, CloseableScope],
        Effect[Effect[tuple[B, ...], EE | Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]: ...
def transform_pull_bracket[A, E, B, EE = Never, RR = Never](
    stream: StreamBase[A, E, RR],
    f: Callable[
        [Pull[tuple[A, ...], E, None, RR], CloseableScope, CloseableScope],
        Effect[Effect[tuple[B, ...], EE | Done, RR], EE, RR],
    ],
) -> Stream[B, EE, RR]:
    """``transform_pull`` with a third argument: a child of the stream's
    scope, closed as soon as the new stream fails or ends."""
    require_stream(stream, "stream")
    channel = stream._channel

    def transform(
        _upstream: Any, scope: CloseableScope, forked: CloseableScope
    ) -> Effect[Any, Any, Any]:
        return channel.to_pull_scoped(scope).flat_map(lambda pull: f(pull, scope, forked))

    built: Channel[Any, Any, Any, Any, Any, Any, Any] = from_transform_bracket(transform)
    return Stream(built)
