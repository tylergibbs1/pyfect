"""Stream providers, curried for ``.pipe`` since they remove what they
provide from the stream's services::

    users.pipe(stream.provide_service(Database, InMemoryDb()))

Each wraps the channel provider of the same name, so a provided service
reaches the build of the stream's pull and every pull.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect import channel
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._layer_core import require_layer
from pyfect.channel._context import update_context_with
from pyfect.context import Context, TagLike
from pyfect.layer import Layer
from pyfect.stream._base import AnyStream, StreamBase, require_stream
from pyfect.stream._stream import Stream

type _AnyStream = Stream[Any, Any, Any]
type _ChannelProvider = Callable[[Any], Any]


def _on_channel(provider: _ChannelProvider, stream: AnyStream) -> _AnyStream:
    require_stream(stream, "stream")
    return Stream(provider(stream._channel))


class _ProvideService[T]:
    __slots__ = ("provider",)

    def __init__(self, provider: _ChannelProvider) -> None:
        self.provider = provider

    @overload
    def __call__[A, E](self, stream: StreamBase[A, E, T]) -> Stream[A, E]: ...
    @overload
    def __call__[A, E, R](self, stream: StreamBase[A, E, T | R]) -> Stream[A, E, R]: ...
    def __call__(self, stream: AnyStream) -> _AnyStream:
        return _on_channel(self.provider, stream)


def provide_service[S, T](tag: TagLike[S, T], service: S) -> _ProvideService[T]:
    """Provide one service to a stream and remove it from its services::

    users.pipe(stream.provide_service(Database, InMemoryDb()))
    """
    return _ProvideService(channel.provide_service(tag, service))


class _ProvideServiceEffect[T, E2, R2]:
    __slots__ = ("provider",)

    def __init__(self, provider: _ChannelProvider) -> None:
        self.provider = provider

    @overload
    def __call__[A, E](self, stream: StreamBase[A, E, T]) -> Stream[A, E | E2, R2]: ...
    @overload
    def __call__[A, E, R](self, stream: StreamBase[A, E, T | R]) -> Stream[A, E | E2, R | R2]: ...
    def __call__(self, stream: AnyStream) -> _AnyStream:
        return _on_channel(self.provider, stream)


def provide_service_effect[S, T, E2 = Never, R2 = Never](
    tag: TagLike[S, T], acquire: Effect[S, E2, R2]
) -> _ProvideServiceEffect[T, E2, R2]:
    """Run ``acquire`` each time the stream runs and provide its value as
    ``tag``'s service, removing ``tag`` from the stream's services."""
    require_effect(acquire, "acquire")
    return _ProvideServiceEffect(channel.provide_service_effect(tag, acquire))


class _ProvideContext[RO]:
    __slots__ = ("provider",)

    def __init__(self, provider: _ChannelProvider) -> None:
        self.provider = provider

    @overload
    def __call__[A, E](self, stream: StreamBase[A, E, RO]) -> Stream[A, E]: ...
    @overload
    def __call__[A, E, R](self, stream: StreamBase[A, E, RO | R]) -> Stream[A, E, R]: ...
    def __call__(self, stream: AnyStream) -> _AnyStream:
        return _on_channel(self.provider, stream)


def provide_context[RO](ctx: Context[RO]) -> _ProvideContext[RO]:
    """Provide every service of ``ctx`` to a stream and remove them from
    its services."""
    return _ProvideContext(channel.provide_context(ctx))


class _ProvideLayer[RO, E2, RI]:
    __slots__ = ("provider",)

    def __init__(self, provider: _ChannelProvider) -> None:
        self.provider = provider

    @overload
    def __call__[A, E](self, stream: StreamBase[A, E, RO]) -> Stream[A, E | E2, RI]: ...
    @overload
    def __call__[A, E, R](self, stream: StreamBase[A, E, RO | R]) -> Stream[A, E | E2, R | RI]: ...
    def __call__(self, stream: AnyStream) -> _AnyStream:
        return _on_channel(self.provider, stream)


@overload
def provide[RO](source: Context[RO], /) -> _ProvideContext[RO]: ...
@overload
def provide[RO, E2 = Never, RI = Never](
    source: Layer[RO, E2, RI], /, *, local: bool = False
) -> _ProvideLayer[RO, E2, RI]: ...
def provide(
    source: Layer[Any, Any, Any] | Context[Any], /, *, local: bool = False
) -> _ProvideLayer[Any, Any, Any] | _ProvideContext[Any]:
    """Provide a context's services, or build a layer each time the stream
    runs (its resources released when the run ends) and provide what it
    builds. Layers an enclosing ``provide`` built are reused unless
    ``local``."""
    if isinstance(source, Context):
        return _ProvideContext(channel.provide_context(source))
    require_layer(source, "source", "a Layer or a Context")
    return _ProvideLayer(channel.provide(source, local=local))


class _UpdateContext[R2, RO]:
    __slots__ = ("provider",)

    def __init__(self, provider: _ChannelProvider) -> None:
        self.provider = provider

    def __call__[A, E](self, stream: StreamBase[A, E, RO]) -> Stream[A, E, R2]:
        return _on_channel(self.provider, stream)


def update_context[R2, RO](f: Callable[[Context[R2]], Context[RO]]) -> _UpdateContext[R2, RO]:
    """Build the stream with the services ``f(context)`` instead of
    ``context``, so it needs ``R2`` instead of what it needed."""
    update: Callable[[Context[Any]], Context[Any]] = f
    return _UpdateContext(lambda ch: update_context_with(ch, update))
