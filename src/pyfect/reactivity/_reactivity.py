"""The ``Reactivity`` service (Effect's ``effect/reactivity/Reactivity``):
queries that run again when the keys they read are invalidated.

Keys are a list of values, or a mapping from a name to ids: invalidating
``{"users": [1]}`` wakes the queries registered on ``["users"]`` and on
``{"users": [1]}``, not those on ``{"users": [2]}``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect._core import Effect, _Locally, _Succeed, _Suspend, _Sync, _WithFiber
from pyfect._effect_args import require_effect
from pyfect.context import Context, Tag
from pyfect.errors import Done
from pyfect.exit import Exit, Failure
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.queue import Dequeue, Queue
from pyfect.reactivity._live import live_keys
from pyfect.run import run_fork
from pyfect.scope import CloseableScope, Scope

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.stream import Stream

type Keys = Sequence[object] | Mapping[str, Sequence[object]]
"""What a query reads or a mutation changes: values, or ids by name."""

type _Hash = str | int


def _noop() -> None:
    pass


class _Query[A, E]:
    """One ``query``: runs its effect again after each invalidation. The
    service's handlers hold ``run`` and ``cancel`` holds that handler, so
    ``unregister`` drops ``cancel`` to end the cycle."""

    __slots__ = (
        "cancel",
        "effect",
        "pending",
        "results",
        "running",
        "scope",
        "services",
        "stopped",
    )

    def __init__(
        self, effect: Effect[A, E, Any], services: Context[Any], scope: CloseableScope
    ) -> None:
        self.effect = effect
        self.services = services
        self.scope = scope
        self.results: Queue[A, E | Done] = Queue()
        self.running = False
        self.pending = False
        self.stopped = False
        self.cancel: Callable[[], None] = _noop

    def unregister(self) -> None:
        cancel, self.cancel = self.cancel, _noop
        cancel()

    def run(self) -> None:
        if self.stopped:
            return
        if self.running:
            self.pending = True
            return
        self.running = True
        self._fork()

    def _fork(self) -> None:
        child = run_fork(self.effect, context=self.services)
        child.run_in(self.scope)
        child.add_observer_unsafe(self._handle_exit)

    def _handle_exit(self, exit_: Exit[A, E]) -> None:
        if isinstance(exit_, Failure):
            self.stopped = True
            self.pending = False
            self.running = False
            self.unregister()
            self.results.fail_cause_unsafe(exit_.cause)
            return
        self.results.offer_unsafe(exit_.value)
        if self.pending:
            self.pending = False
            self._fork()
        else:
            self.running = False


class _PendingInvalidation(
    Tag[dict[_Hash, None]], key="effect/reactivity/Reactivity/PendingInvalidation"
):
    """The invalidations ``with_batch`` collects."""


def _string_or_hash(u: object) -> _Hash:
    match u:
        case bool():
            return "true" if u else "false"
        case float() if u.is_integer():
            return str(int(u))
        case str() | int() | float():
            return str(u)
        case _:
            return hash(u)


def _keys_to_hashes(keys: Keys) -> Iterable[_Hash]:
    if isinstance(keys, Mapping):
        for name, ids in keys.items():
            yield name
            for id_ in ids:
                yield f"{name}:{_string_or_hash(id_)}"
    else:
        for key in keys:
            yield _string_or_hash(key)


class ReactivityService:
    """Registers handlers on keys and runs them when the keys are
    invalidated."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[_Hash, dict[Callable[[], None], None]] = {}

    def _run_handlers(self, hashes: Iterable[_Hash]) -> None:
        ran: dict[Callable[[], None], None] = {}
        for hash_ in hashes:
            handlers = self._handlers.get(hash_)
            if handlers is None:
                continue
            for handler in live_keys(handlers):
                if handler not in ran:
                    ran[handler] = None
                    handler()

    def invalidate_unsafe(self, keys: Keys) -> None:
        """Run the handlers of ``keys`` now, each once."""
        self._run_handlers(dict.fromkeys(_keys_to_hashes(keys)))

    def register_unsafe(self, keys: Keys, handler: Callable[[], None]) -> Callable[[], None]:
        """Run ``handler`` whenever one of ``keys`` is invalidated; returns
        the function that unregisters it."""
        resolved = list(_keys_to_hashes(keys))
        for hash_ in resolved:
            self._handlers.setdefault(hash_, {})[handler] = None

        def unregister() -> None:
            for hash_ in resolved:
                handlers = self._handlers.get(hash_)
                if handlers is None:
                    continue
                handlers.pop(handler, None)
                if not handlers:
                    del self._handlers[hash_]

        return unregister

    def invalidate(self, keys: Keys) -> Effect[None]:
        """Invalidate ``keys``: now, or when the enclosing ``with_batch``
        ends."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            found, pending = fiber._context.lookup(_PendingInvalidation)
            if found:
                pending.update(dict.fromkeys(_keys_to_hashes(keys)))
            else:
                self.invalidate_unsafe(keys)
            return _Succeed(None)

        return _WithFiber(body)

    def mutation[A, E, R](self, keys: Keys, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``effect``, then invalidate ``keys`` if it succeeded."""
        require_effect(effect, "effect")
        return effect.tap(lambda _: self.invalidate(keys))

    def query[A, E, R](
        self, keys: Keys, effect: Effect[A, E, R]
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]:
        """A queue of ``effect``'s results: it runs now, and again after each
        invalidation of ``keys`` (once more if invalidated while running),
        until the scope closes. A failure fails the queue and stops it."""
        require_effect(effect, "effect")

        def body(fiber: Fiber[Any, Any]) -> Effect[Dequeue[A, E | Done], Never, R | Scope]:
            services: Context[Any] = fiber._context
            scope: CloseableScope = services.get_unsafe(Scope)
            query = _Query[A, E](effect, services, scope)
            query.cancel = self.register_unsafe(keys, query.run)

            def start() -> Dequeue[A, E | Done]:
                query.run()
                return query.results

            return scope.add_finalizer(lambda _: _Sync(query.unregister)).and_then(_Sync(start))

        return _WithFiber(body)

    def stream[A, E, R](self, keys: Keys, effect: Effect[A, E, R]) -> Stream[A, E, R]:
        """``query``'s results as a stream."""
        from pyfect import stream

        require_effect(effect, "effect")

        streams = self.query(keys, effect).map(stream.from_queue)
        return stream.unwrap(cast("Effect[Stream[A, E, R], E, Scope | R]", streams))

    def with_batch[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        """Run ``effect``, collecting its invalidations, and run their
        handlers once when it ends."""
        require_effect(effect, "effect")

        def body() -> Effect[A, E, R]:
            # ordered: handlers run in the order keys were invalidated
            pending: dict[_Hash, None] = {}
            batched: Effect[A, E, R] = _Locally(
                effect, lambda ctx: ctx.add(_PendingInvalidation, pending)
            )
            return batched.on_exit(lambda _: _Sync(lambda: self._run_handlers(pending)))

        return _Suspend(body)


class Reactivity(Tag[ReactivityService], key="effect/reactivity/Reactivity"):
    """The ``Reactivity`` service."""


make: Effect[ReactivityService] = _Sync(ReactivityService)
"""A new ``ReactivityService``."""

layer: Layer[Reactivity] = layer_effect(Reactivity, make)
"""Provides a new ``ReactivityService``."""


def mutation[A, E, R](effect: Effect[A, E, R], keys: Keys) -> Effect[A, E, R | Reactivity]:
    """Run ``effect``, then invalidate ``keys`` if it succeeded."""
    require_effect(effect, "effect")
    return Reactivity().flat_map(lambda r: r.mutation(keys, effect))


def query[A, E, R](
    effect: Effect[A, E, R], keys: Keys
) -> Effect[Dequeue[A, E | Done], Never, R | Scope | Reactivity]:
    """A queue of ``effect``'s results, refreshed when ``keys`` are
    invalidated (see ``ReactivityService.query``)."""
    require_effect(effect, "effect")
    return Reactivity().flat_map(lambda r: r.query(keys, effect))


def stream[A, E, R](effect: Effect[A, E, R], keys: Keys) -> Stream[A, E, R | Reactivity]:
    """``query``'s results as a stream."""
    from pyfect import stream as stream_

    require_effect(effect, "effect")

    streams = query(effect, keys).map(stream_.from_queue)
    return stream_.unwrap(
        cast("Effect[Stream[A, E, R | Reactivity], E, Scope | R | Reactivity]", streams)
    )


def invalidate(keys: Keys) -> Effect[None, Never, Reactivity]:
    """Invalidate ``keys``."""
    return Reactivity().flat_map(lambda r: r.invalidate(keys))


__all__ = [
    "Keys",
    "Reactivity",
    "ReactivityService",
    "invalidate",
    "layer",
    "make",
    "mutation",
    "query",
    "stream",
]
