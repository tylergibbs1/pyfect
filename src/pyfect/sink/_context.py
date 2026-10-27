"""Services for sinks: the curried providers (used with ``.pipe``, since
they remove what they provide from ``R``) and ``unwrap``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never, overload

from pyfect._core import Effect, _Locally
from pyfect._effect_args import require_effect
from pyfect.context import Context, TagLike, tag_class
from pyfect.scope import CloseableScope, Scope
from pyfect.sink._combinators import transform_effect
from pyfect.sink._sink import AnySink, Sink, Upstream, require_sink

type Sink_ = Sink[Any, Any, Any, Any, Any]


class _ProvideService[S, T]:
    __slots__ = ("service", "tag")

    def __init__(self, tag: type[Any], service: S) -> None:
        self.tag = tag
        self.service = service

    @overload
    def __call__[A, In, L, E](self, sink: Sink[A, In, L, E, T]) -> Sink[A, In, L, E]: ...
    @overload
    def __call__[A, In, L, E, R](self, sink: Sink[A, In, L, E, T | R]) -> Sink[A, In, L, E, R]: ...
    def __call__(self, sink: AnySink) -> Sink_:
        require_sink(sink, "sink")
        tag, service = self.tag, self.service
        return transform_effect(sink, lambda eff: _Locally(eff, lambda ctx: ctx.add(tag, service)))


def provide_service[S, T](tag: TagLike[S, T], service: S) -> _ProvideService[S, T]:
    """Provide one service to a sink and remove it from ``R``::

    sink.pipe(provide_service(Database, InMemoryDb()))
    """
    return _ProvideService(tag_class(tag), service)


class _ProvideContext[RO]:
    __slots__ = ("ctx",)

    def __init__(self, ctx: Context[RO]) -> None:
        self.ctx = ctx

    @overload
    def __call__[A, In, L, E](self, sink: Sink[A, In, L, E, RO]) -> Sink[A, In, L, E]: ...
    @overload
    def __call__[A, In, L, E, R](self, sink: Sink[A, In, L, E, RO | R]) -> Sink[A, In, L, E, R]: ...
    def __call__(self, sink: AnySink) -> Sink_:
        require_sink(sink, "sink")
        ctx = self.ctx
        return transform_effect(sink, lambda eff: _Locally(eff, lambda current: current.merge(ctx)))


def provide_context[RO](ctx: Context[RO]) -> _ProvideContext[RO]:
    """Provide every service of ``ctx`` to a sink and remove them from
    ``R``::

    sink.pipe(provide_context(ctx))
    """
    return _ProvideContext(ctx)


@overload
def unwrap[A, In, L, EE = Never, RR = Never](
    eff: Effect[Sink[A, In, L, EE, RR], EE, Scope],
) -> Sink[A, In, L, EE, RR]: ...
@overload
def unwrap[A, In, L, EE = Never, RR = Never](
    eff: Effect[Sink[A, In, L, EE, RR], EE, Scope | RR],
) -> Sink[A, In, L, EE, RR]: ...
def unwrap(eff: Effect[AnySink, Any, Any]) -> Sink_:
    """The sink ``eff`` succeeds with, built each time it runs. ``eff``
    runs with the sink's ``Scope``, so its resources live as long as the
    sink's run."""
    require_effect(eff, "eff")

    def transform(upstream: Upstream[Any], scope: CloseableScope) -> Effect[Any, Any, Any]:
        built: Effect[AnySink, Any, Any] = _Locally(eff, lambda ctx: ctx.add(Scope, scope))
        return built.flat_map(lambda sink: sink._transform(upstream, scope))

    return Sink(transform)
