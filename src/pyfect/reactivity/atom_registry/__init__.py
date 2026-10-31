"""``AtomRegistry``: where atoms' values live (Effect's
``effect/reactivity/AtomRegistry``).

``make()`` creates a registry (``AtomRegistryService``); ``layer``
provides one as the ``AtomRegistry`` service and disposes it with the
layer's scope. ``r.get(atom)``, ``r.set(atom, value)``,
``r.subscribe(atom, f)`` and ``r.mount(atom)`` work on it directly; the
effect-returning ``to_stream``, ``get_result`` and ``mount`` take the
registry as their first argument.

A registry runs node removals, idle timeouts and the fibers of atoms
backed by effects on one ``Scheduler``: the one given, else the running
fiber's, else the running asyncio loop's.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect._core import Effect, _Callback, _Sync, _WithFiber
from pyfect._public import publish
from pyfect.context import Tag
from pyfect.duration import Duration
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.reactivity import async_result
from pyfect.reactivity._result_effect import result_effect
from pyfect.reactivity.async_result import AsyncResult, Initial
from pyfect.reactivity.atom_registry._batch import batch
from pyfect.reactivity.atom_registry._node import Node, NodeState
from pyfect.reactivity.atom_registry._registry import (
    AtomRegistryService,
    InitialValue,
    RegistryDisposedError,
)
from pyfect.scheduler import Scheduler
from pyfect.scope import CloseableScope, Scope, acquire_release

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.errors import Done
    from pyfect.queue import Queue
    from pyfect.reactivity.atom._types import Atom, AtomContext
    from pyfect.stream import Stream


class AtomRegistry(Tag[AtomRegistryService], key="~effect/reactivity/AtomRegistry"):
    """The ``AtomRegistry`` service."""


def is_atom_registry(u: object) -> bool:
    return isinstance(u, AtomRegistryService)


def make(
    *,
    initial_values: Iterable[InitialValue[Any]] | None = None,
    scheduler: Scheduler | None = None,
    timeout_resolution: Duration | None = None,
    default_idle_ttl: Duration | None = None,
) -> AtomRegistryService:
    """A new registry. ``initial_values`` seed atoms (``atom.initial_value``);
    ``default_idle_ttl`` keeps unused atoms that long, checked every
    ``timeout_resolution`` (half the TTL by default, else a second).
    Without ``scheduler`` it runs on the running fiber's scheduler, else
    the running asyncio loop's (``NoRunError`` with neither)."""
    return AtomRegistryService(
        initial_values=initial_values,
        scheduler=scheduler,
        timeout_resolution=timeout_resolution,
        default_idle_ttl=default_idle_ttl,
    )


def layer_options(
    *,
    initial_values: Iterable[InitialValue[Any]] | None = None,
    scheduler: Scheduler | None = None,
    timeout_resolution: Duration | None = None,
    default_idle_ttl: Duration | None = None,
) -> Layer[AtomRegistry]:
    """A layer providing a registry made with these options (on the
    building fiber's scheduler by default), disposed with its scope."""

    def build(scope: CloseableScope) -> Effect[AtomRegistryService]:
        def create() -> AtomRegistryService:
            registry = make(
                initial_values=initial_values,
                scheduler=scheduler,
                timeout_resolution=timeout_resolution,
                default_idle_ttl=default_idle_ttl,
            )
            return registry

        def register(registry: AtomRegistryService) -> Effect[AtomRegistryService]:
            return scope.add_finalizer(lambda _exit: _Sync(registry.dispose)).as_(registry)

        return _Sync(create).flat_map(register)

    return layer_effect(AtomRegistry, Scope().flat_map(build))


layer: Layer[AtomRegistry] = layer_options()
"""Provides a registry with the default options."""


# --- conversions ------------------------------------------------------------


def to_stream[A](self: AtomRegistryService, atom: Atom[A]) -> Stream[A]:
    """The atom's current value, then each new one."""
    from pyfect import stream

    def start(queue: Queue[A, Done]) -> Effect[None, Never, Scope]:
        def offer(value: A) -> None:
            queue.offer_unsafe(value)

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            scope = fiber._context.get_unsafe(Scope)
            cancel = self.subscribe(atom, offer, immediate=True)
            return scope.add_finalizer(lambda _: _Sync(cancel))

        return _WithFiber(body)

    return stream.callback(start)


def to_stream_result[A, E](
    self: AtomRegistryService, atom: Atom[AsyncResult[A, E]]
) -> Stream[A, E]:
    """The values of an atom holding a result: initial results are skipped,
    a failure fails the stream, and repeated values are dropped."""
    return (
        to_stream(self, atom)
        .filter(async_result.is_not_initial)
        .map_effect(result_effect)
        .changes()
    )


def get_result[A, E](
    self: AtomRegistryService,
    atom: Atom[AsyncResult[A, E]],
    *,
    suspend_on_waiting: bool = False,
) -> Effect[A, E]:
    """The atom's success or failure, once it is not ``Initial`` (nor
    waiting, with ``suspend_on_waiting``)."""

    def ready(result: AsyncResult[A, E]) -> bool:
        return not isinstance(result, Initial) and not (suspend_on_waiting and result.waiting)

    def register(resume: Callable[[Effect[A, E]], None]) -> Effect[None] | None:
        result = self.get(atom)
        if ready(result):
            resume(result_effect(result))
            return None

        def on_change(value: AsyncResult[A, E]) -> None:
            if ready(value):
                resume(result_effect(value))
                cancel()

        cancel = self.subscribe(atom, on_change)
        return _Sync(cancel)

    return _Callback(register)


def mount(self: AtomRegistryService, atom: Atom[Any]) -> Effect[None, Never, Scope]:
    """Keep ``atom`` mounted until the current scope closes."""
    return acquire_release(_Sync(lambda: self.mount(atom)), lambda release, _: _Sync(release)).as_(
        None
    )


def consume_skip_initial_run(ctx: AtomContext) -> bool:
    """Whether this build keeps the node's seeded value instead of running
    its effect (an ``initial_value`` with ``skip_initial_run``): once per
    seed, and only while the parents it was seeded under are unchanged."""
    from pyfect.reactivity.atom_registry._lifetime import Lifetime

    lifetime = cast("Lifetime[Any]", ctx)
    node = lifetime.node
    if not node.skip_initial_run:
        return False
    kept = node.kept_parents
    node.skip_initial_run = False
    node.kept_parents = None
    return (
        not lifetime.is_fn
        and not isinstance(node._value, Initial)
        and (kept is None or all(parent.lifetime is life for parent, life in kept))
    )


__all__ = [
    "AtomRegistry",
    "AtomRegistryService",
    "InitialValue",
    "Node",
    "NodeState",
    "RegistryDisposedError",
    "batch",
    "consume_skip_initial_run",
    "get_result",
    "is_atom_registry",
    "layer",
    "layer_options",
    "make",
    "mount",
    "to_stream",
    "to_stream_result",
]
publish(globals())
