"""Effects that read or provide services: ``context``, ``service_option``,
``provide_context``, ``provide_service_effect`` and ``update_service_scoped``.

The providers remove what they provide from ``R``, so they are used with
``.pipe``; ``Effect.update_service`` adds a requirement, so it is a method.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect._core import Effect, _Locally, _Succeed, _Suspend, _WithFiber
from pyfect._fiber import Fiber
from pyfect.context import Context, TagLike, tag_class
from pyfect.exit import Exit
from pyfect.option import Option
from pyfect.scope import Scope

_VOID: Effect[None] = _Succeed(None)


def context[T = Never](*tags: TagLike[Any, T]) -> Effect[Context[T], Never, T]:
    """The current fiber's services. Name the tags the caller reads (Effect's
    ``context<R>()``): they join ``R``, and the context is typed to hold
    them::

        ctx = yield from fx.context(Database, Clock)
    """
    return _WithFiber(lambda fiber: _Succeed(fiber._context))


def service_option[S, T](tag: TagLike[S, T]) -> Effect[Option[S]]:
    """``Some(service)`` if it is provided, else ``None``. Never needs the
    service, so ``tag`` does not join ``R``."""
    return _WithFiber(lambda fiber: _Succeed(fiber._context.get_option(tag)))


class _ProvideContext[RO]:
    __slots__ = ("ctx",)

    def __init__(self, ctx: Context[RO]) -> None:
        self.ctx = ctx

    @overload
    def __call__[A, E = Never](self, target: Effect[A, E, RO]) -> Effect[A, E]: ...
    @overload
    def __call__[A, E = Never, R = Never](
        self, target: Effect[A, E, RO | R]
    ) -> Effect[A, E, R]: ...
    def __call__(self, target: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        ctx = self.ctx
        return _Locally(target, lambda current: current.merge(ctx))


def provide_context[RO](ctx: Context[RO]) -> _ProvideContext[RO]:
    """Provide every service of ``ctx`` and remove them from ``R``::

    eff.pipe(provide_context(ctx))
    """
    return _ProvideContext(ctx)


class _ProvideServiceEffect[T, E2, R2]:
    __slots__ = ("acquire", "tag")

    def __init__(self, tag: type[Any], acquire: Effect[Any, E2, R2]) -> None:
        self.tag = tag
        self.acquire = acquire

    @overload
    def __call__[A, E = Never](self, eff: Effect[A, E, T]) -> Effect[A, E | E2, R2]: ...
    @overload
    def __call__[A, E = Never, R = Never](
        self, eff: Effect[A, E, T | R]
    ) -> Effect[A, E | E2, R | R2]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        tag = self.tag
        return self.acquire.flat_map(
            lambda service: _Locally(eff, lambda ctx: ctx.add(tag, service))
        )


def provide_service_effect[S, T, E2 = Never, R2 = Never](
    tag: TagLike[S, T], acquire: Effect[S, E2, R2]
) -> _ProvideServiceEffect[T, E2, R2]:
    """Run ``acquire`` and provide its value as ``tag``'s service, removing
    ``tag`` from ``R``::

    eff.pipe(provide_service_effect(Database, connect()))
    """
    return _ProvideServiceEffect(tag_class(tag), acquire)


def update_service_scoped[S, T](
    tag: TagLike[S, T],
    f: Callable[[S], S],
    *,
    reset: Callable[[S, S, S], S] | None = None,
) -> Effect[None, Never, T | Scope]:
    """Replace the service of ``tag`` with ``f(service)`` for the rest of
    the current fiber's region, and put the original back when the current
    ``Scope`` closes, unless the service has changed again by then.
    ``reset(original, updated, current)`` decides what to put back instead.
    """

    def update(fiber: Fiber[Any, Any]) -> Effect[None]:
        original = fiber._context.unsafe_get(tag)
        updated = f(original)
        fiber._set_context(fiber._context.add(tag, updated))

        def put_back() -> Effect[None]:
            current = fiber._context.get_option(tag)
            if current is None or (reset is None and current.value is not updated):
                return _VOID
            restored = original if reset is None else reset(original, updated, current.value)
            fiber._set_context(fiber._context.add(tag, restored))
            return _VOID

        def finalizer(_ex: Exit[Any, Any]) -> Effect[None]:
            return _Suspend(put_back)

        scope = fiber._context.unsafe_get(Scope)
        if scope._closed is not None:
            return finalizer(scope._closed)
        # Not ``add_finalizer``: it restores the closing fiber's services
        # afterwards, which would undo the put-back when this fiber closes.
        scope._add(object(), finalizer)
        return _VOID

    return _WithFiber(update).uninterruptible()
