"""Services for channels: the curried providers (used with ``.pipe``, since
they remove what they provide from ``Env``), ``scoped``, and the context
updates behind ``update_service`` and ``with_span``.

A provided service reaches both the build of the channel's pull and every
pull, so resources acquired while building and effects run per item see
the same services.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect._core import Effect, _Locally, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._layer_core import require_layer
from pyfect.channel._base import AnyChannel, AnyPull, ChannelBase, require_channel
from pyfect.channel._channel import Channel, from_transform
from pyfect.channel._constructors import bracket
from pyfect.context import Context, TagLike, tag_class
from pyfect.layer import Layer, MemoMap
from pyfect.scope import CloseableScope, Scope

type Channel_ = Channel[Any, Any, Any, Any, Any, Any, Any]
type Update = Callable[[Context[Any]], Context[Any]]


def _locally(self: AnyChannel, update: Update) -> Channel_:
    def provided(pull: AnyPull) -> AnyPull:
        return _Locally(pull, update)

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        built: Effect[AnyPull] = _Locally(self._transform(upstream, scope), update)
        return built.map(provided)

    return from_transform(transform)


def update_context_with(self: AnyChannel, f: Update) -> Channel_:
    """The channel with the services ``f(context)``, where ``context`` is
    the services the channel is built with."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull]:
        def build(fiber: Any) -> Effect[AnyPull]:
            provided = f(fiber._context)
            return _locally(self, lambda current: current.merge(provided))._transform(
                upstream, scope
            )

        return _WithFiber(build)

    return from_transform(transform)


class _ProvideService[T]:
    __slots__ = ("service", "tag")

    def __init__(self, tag: type[Any], service: object) -> None:
        self.tag = tag
        self.service = service

    @overload
    def __call__[O, E, D, I, IE, ID](
        self, channel: ChannelBase[O, E, D, I, IE, ID, T]
    ) -> Channel[O, E, D, I, IE, ID]: ...
    @overload
    def __call__[O, E, D, I, IE, ID, R](
        self, channel: ChannelBase[O, E, D, I, IE, ID, T | R]
    ) -> Channel[O, E, D, I, IE, ID, R]: ...
    def __call__(self, channel: AnyChannel) -> Channel_:
        tag, service = self.tag, self.service
        return _locally(channel, lambda ctx: ctx.add(tag, service))


def provide_service[S, T](tag: TagLike[S, T], service: S) -> _ProvideService[T]:
    """Provide one service to a channel and remove it from ``Env``::

    channel.pipe(provide_service(Database, InMemoryDb()))
    """
    return _ProvideService(tag_class(tag), service)


class _ProvideServiceEffect[T, E2, R2]:
    __slots__ = ("acquire", "tag")

    def __init__(self, tag: type[Any], acquire: Effect[Any, E2, R2]) -> None:
        self.tag = tag
        self.acquire = acquire

    @overload
    def __call__[O, E, D, I, IE, ID](
        self, channel: ChannelBase[O, E, D, I, IE, ID, T]
    ) -> Channel[O, E | E2, D, I, IE, ID, R2]: ...
    @overload
    def __call__[O, E, D, I, IE, ID, R](
        self, channel: ChannelBase[O, E, D, I, IE, ID, T | R]
    ) -> Channel[O, E | E2, D, I, IE, ID, R | R2]: ...
    def __call__(self, channel: AnyChannel) -> Channel_:
        tag, acquire = self.tag, self.acquire

        def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Any, Any]:
            return acquire.flat_map(
                lambda service: _locally(channel, lambda ctx: ctx.add(tag, service))._transform(
                    upstream, scope
                )
            )

        return from_transform(transform)


def provide_service_effect[S, T, E2 = Never, R2 = Never](
    tag: TagLike[S, T], acquire: Effect[S, E2, R2]
) -> _ProvideServiceEffect[T, E2, R2]:
    """Run ``acquire`` each time the channel runs and provide its value as
    ``tag``'s service, removing ``tag`` from ``Env``."""
    require_effect(acquire, "acquire")
    return _ProvideServiceEffect(tag_class(tag), acquire)


class _ProvideContext[RO]:
    __slots__ = ("ctx",)

    def __init__(self, ctx: Context[RO]) -> None:
        self.ctx = ctx

    @overload
    def __call__[O, E, D, I, IE, ID](
        self, channel: ChannelBase[O, E, D, I, IE, ID, RO]
    ) -> Channel[O, E, D, I, IE, ID]: ...
    @overload
    def __call__[O, E, D, I, IE, ID, R](
        self, channel: ChannelBase[O, E, D, I, IE, ID, RO | R]
    ) -> Channel[O, E, D, I, IE, ID, R]: ...
    def __call__(self, channel: AnyChannel) -> Channel_:
        ctx = self.ctx
        return _locally(channel, lambda current: current.merge(ctx))


def provide_context[RO](ctx: Context[RO]) -> _ProvideContext[RO]:
    """Provide every service of ``ctx`` to a channel and remove them from
    ``Env``."""
    return _ProvideContext(ctx)


class _ProvideLayer[RO, E2, RI]:
    __slots__ = ("layer", "local")

    def __init__(self, layer: Layer[RO, E2, RI], local: bool) -> None:
        self.layer = layer
        self.local = local

    @overload
    def __call__[O, E, D, I, IE, ID](
        self, channel: ChannelBase[O, E, D, I, IE, ID, RO]
    ) -> Channel[O, E | E2, D, I, IE, ID, RI]: ...
    @overload
    def __call__[O, E, D, I, IE, ID, R](
        self, channel: ChannelBase[O, E, D, I, IE, ID, RO | R]
    ) -> Channel[O, E | E2, D, I, IE, ID, R | RI]: ...
    def __call__(self, channel: AnyChannel) -> Channel_:
        layer, local = self.layer, self.local

        def transform(upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Any, Any]:
            built = (
                layer.build_with_memo_map(MemoMap(), scope)
                if local
                else layer.build_with_scope(scope)
            )
            return built.flat_map(
                lambda ctx: _locally(channel, lambda current: current.merge(ctx))._transform(
                    upstream, scope
                )
            )

        return from_transform(transform)


@overload
def provide[RO](source: Context[RO], /) -> _ProvideContext[RO]: ...
@overload
def provide[RO, E2 = Never, RI = Never](
    source: Layer[RO, E2, RI], /, *, local: bool = False
) -> _ProvideLayer[RO, E2, RI]: ...
def provide(
    source: Layer[Any, Any, Any] | Context[Any], /, *, local: bool = False
) -> _ProvideLayer[Any, Any, Any] | _ProvideContext[Any]:
    """Provide a context's services, or build a layer each time the channel
    runs (its resources released when the run ends) and provide what it
    builds. Layers an enclosing ``provide`` built are reused unless
    ``local``."""
    if isinstance(source, Context):
        return _ProvideContext(source)
    require_layer(source, "source", "a Layer or a Context")
    return _ProvideLayer(source, local)


class _UpdateContext[R2, RO]:
    __slots__ = ("f",)

    def __init__(self, f: Callable[[Context[R2]], Context[RO]]) -> None:
        self.f = f

    def __call__[O, E, D, I, IE, ID](
        self, channel: ChannelBase[O, E, D, I, IE, ID, RO]
    ) -> Channel[O, E, D, I, IE, ID, R2]:
        return update_context_with(channel, self.f)


def update_context[R2, RO](f: Callable[[Context[R2]], Context[RO]]) -> _UpdateContext[R2, RO]:
    """Build the channel with the services ``f(context)`` instead of
    ``context``, so it needs ``R2`` instead of what it needed."""
    return _UpdateContext(f)


@overload
def scoped[O, E, D, I, IE, ID](
    channel: ChannelBase[O, E, D, I, IE, ID, Scope],
) -> Channel[O, E, D, I, IE, ID]: ...
@overload
def scoped[O, E, D, I, IE, ID, R](
    channel: ChannelBase[O, E, D, I, IE, ID, Scope | R],
) -> Channel[O, E, D, I, IE, ID, R]: ...
def scoped(channel: AnyChannel) -> Channel_:
    """Give the channel a ``Scope`` of its own, closed as soon as it fails
    or ends (or its run ends), and remove ``Scope`` from ``Env``."""
    require_channel(channel, "channel")

    def build(upstream: AnyPull, scope: CloseableScope, forked: CloseableScope) -> Effect[AnyPull]:
        return _locally(channel, lambda ctx: ctx.add(Scope, forked))._transform(upstream, scope)

    return bracket(build)
