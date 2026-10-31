"""Atoms backed by effects and streams: how a build runs one and turns its
progress into an ``AsyncResult``.

A build runs the effect on a fiber of the registry's scheduler, at once:
if it finishes before waiting, the build returns its result; otherwise the
atom is ``waiting`` until the fiber's exit replaces its value. The fiber
gets a ``Scope`` closed when the build is replaced and the
``AtomRegistry``; replacing the build interrupts it (unless
``uninterruptible``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect._core import Effect, _Succeed
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.errors import NoSuchElementException
from pyfect.exit import Exit
from pyfect.exit import succeed as exit_succeed
from pyfect.logger._log import log_unhandled
from pyfect.option import Some
from pyfect.pull import is_done_cause
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._types import AtomContext, Writable, WriteContext, writable
from pyfect.reactivity.atom_registry import AtomRegistry, consume_skip_initial_run
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.reactivity.atom_registry import AtomRegistryService

_EMPTY: Context[Never] = Context.empty()

type Services = Context[Any] | Callable[[], Context[Any]]

MISSING: Any = object()
"""The default of the public ``initial_value`` options: no initial value.
``initial_option`` turns an option into ``Some(value) | None`` at the
boundary, and only that reaches the internals."""


def initial_option(initial_value: object) -> Some[Any] | None:
    return None if initial_value is MISSING else Some(initial_value)


_VOID: Effect[None] = _Succeed(None)


def _set_self[A](ctx: WriteContext[A], value: A) -> None:
    ctx.set_self(value)


def state[A](initial: A) -> Writable[A, A]:
    """A writable atom holding ``initial`` until it is set."""
    return writable(lambda _get: initial, _set_self)


def _close_scope(scope: CloseableScope) -> Effect[None]:
    def report(cause: Cause[Any]) -> Effect[None]:
        if cause.has_interrupts_only:
            return _VOID
        return log_unhandled("Unhandled error in atom finalizer", cause)

    return scope.close(exit_succeed(None)).catch_cause(report)


def run_callback_sync[A, E](
    registry: AtomRegistryService,
    services: Context[Any],
    effect: Effect[A, E, Any],
    on_exit: Callable[[Exit[A, E]], None],
    uninterruptible: bool = False,
) -> Callable[[], None] | None:
    """Run ``effect`` at once; ``on_exit`` gets its exit (now, if it
    finishes before waiting: then ``None`` is returned, else the function
    that stops listening and interrupts it)."""
    fiber = registry.fork(effect, services)
    result = fiber.poll_unsafe()
    if result is not None:
        on_exit(result)
        return None
    remove = fiber.add_observer_unsafe(on_exit)

    def cancel() -> None:
        remove()
        if not uninterruptible:
            fiber.interrupt_as_unsafe(None)

    return cancel


def make_effect[A, E](
    ctx: AtomContext,
    effect: Effect[A, E, Any],
    initial_value: AsyncResult[A, E],
    services: Services = _EMPTY,
    uninterruptible: bool = False,
) -> AsyncResult[A, E]:
    """Run ``effect`` for this build (see the module docs)."""
    previous = ctx.self()
    if previous is not None and consume_skip_initial_run(ctx):
        return cast("AsyncResult[A, E]", previous.value)

    def get_services() -> Context[Any]:
        return services if isinstance(services, Context) else services()

    registry = ctx.registry
    scope = CloseableScope()
    ctx.add_finalizer(lambda: _discard(registry.fork(_close_scope(scope), get_services())))
    found: list[AsyncResult[A, E]] = []
    running = [False]

    def on_exit(exit: Exit[A, E]) -> None:
        if running[0]:
            # The live value, not ``previous``: while the effect ran the
            # atom may have shown ``initial_value`` or a ``set_self``
            # success, and a failure keeps the latest success shown.
            ctx.set_self(async_result.from_exit_with_previous(exit, ctx.self()))
        else:
            found.append(async_result.from_exit_with_previous(exit, previous))

    context = get_services().add(Scope, scope).add(AtomRegistry, registry)
    cancel = run_callback_sync(registry, context, effect, on_exit, uninterruptible)
    running[0] = True
    if cancel is not None:
        ctx.add_finalizer(cancel)
    if found:
        return found[0]
    if previous is not None:
        return async_result.waiting_from(previous)
    return async_result.waiting(initial_value)


def _discard(_: object) -> None:
    pass


def initial_result[A, E](initial_value: Some[A] | None) -> AsyncResult[A, E]:
    if initial_value is None:
        return async_result.initial()
    return async_result.success(initial_value.value)


def effect_result[A, E](
    get: AtomContext,
    effect: Effect[A, E, Any],
    initial_value: Some[A] | None,
    uninterruptible: bool,
    services: Services = _EMPTY,
) -> AsyncResult[A, E]:
    return make_effect(get, effect, initial_result(initial_value), services, uninterruptible)


def make_stream[A, E](
    ctx: AtomContext,
    stream: Stream[A, E, Any],
    initial_value: AsyncResult[A, E | NoSuchElementException],
    services: Context[Any] = _EMPTY,
) -> AsyncResult[A, E | NoSuchElementException]:
    """Run ``stream`` for this build: each chunk's last item becomes a
    waiting success; its end makes the last value final (or fails with
    ``NoSuchElementException`` if it had none)."""
    from pyfect.scope import scoped_with

    previous = ctx.self()
    if previous is not None and consume_skip_initial_run(ctx):
        return cast("AsyncResult[A, E | NoSuchElementException]", previous.value)
    registry = ctx.registry

    def step(items: tuple[A, ...]) -> None:
        ctx.set_self(async_result.success(items[-1], waiting=True))

    def run(scope: CloseableScope) -> Effect[None, Any, Any]:
        return stream.channel.to_pull_scoped(scope).flat_map(
            lambda pull: pull.map(step).forever(disable_yield=True)
        )

    def on_end(cause: Cause[Any]) -> Effect[None]:
        current: Any = ctx.self()
        if is_done_cause(cause):
            last = None if current is None else async_result.value(current.value)
            if last is None:
                ctx.set_self(
                    async_result.fail_with_previous(NoSuchElementException(), previous=current)
                )
            else:
                ctx.set_self(async_result.success(last.value))
        else:
            ctx.set_self(async_result.failure_with_previous(cause, previous=current))
        return _VOID

    runner = scoped_with(run).catch_cause(on_end)
    context = services.add(AtomRegistry, registry)
    cancel = run_callback_sync(registry, context, runner, _discard)
    if cancel is not None:
        ctx.add_finalizer(cancel)
    if previous is not None:
        return async_result.waiting_from(previous)
    return async_result.waiting(initial_value)


def stream_result[A, E](
    get: AtomContext,
    stream: Stream[A, E, Any],
    initial_value: Some[A] | None,
    services: Context[Any] = _EMPTY,
) -> AsyncResult[A, E | NoSuchElementException]:
    return make_stream(get, stream, initial_result(initial_value), services)


type Read[A] = Callable[[AtomContext, Context[Any]], A]
"""A read function that also takes the services a runtime provides."""


def make_read(
    arg: object, initial_value: Some[Any] | None, uninterruptible: bool
) -> Read[Any] | Writable[Any, Any]:
    """The read function of ``atom.make(arg)``: of an effect, a stream, or
    a function (whose result is run if it is an effect or a stream); a
    plain value makes a ``state`` atom instead."""
    if isinstance(arg, Effect):
        eff = cast("Effect[Any, Any, Any]", arg)
        return lambda get, services: effect_result(
            get, eff, initial_value, uninterruptible, services
        )
    if isinstance(arg, Stream):
        src = cast("Stream[Any, Any, Any]", arg)
        return lambda get, services: stream_result(get, src, initial_value, services)
    if callable(arg):
        create = cast("Callable[[AtomContext], object]", arg)

        def read(get: AtomContext, services: Context[Any]) -> object:
            value = create(get)
            if isinstance(value, Effect):
                eff = cast("Effect[Any, Any, Any]", value)
                return effect_result(get, eff, initial_value, uninterruptible, services)
            if isinstance(value, Stream):
                src = cast("Stream[Any, Any, Any]", value)
                return stream_result(get, src, initial_value, services)
            return value

        return read
    return state(arg)
