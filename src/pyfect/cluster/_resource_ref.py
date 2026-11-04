"""A resource that can be rebuilt in place (Effect's
``internal/resourceRef``): SQL runner storage keeps its reserved lock
connection in one, replacing it when a statement on it fails.

``await_`` waits for the current resource; ``rebuild_unsafe`` releases it
(in the background, so a stalled release cannot block) and acquires a new
one; a failed acquisition leaves the ref ``Failed`` until the next
rebuild. Closing the parent scope closes the ref and wakes its waiters
with an interruption.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any, overload

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._unsubscripted import Unsubscripted
from pyfect.cluster._interruptors import around_entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.deferred import Deferred
from pyfect.effect import gen, interrupt, succeed, suspend, sync, void
from pyfect.exit import Exit, Failure, Success
from pyfect.exit import interrupt as interrupt_exit
from pyfect.scope import CloseableScope, fork_in


@dataclass(eq=False, slots=True)
class _Pending[A]:
    scope: CloseableScope
    releases: CloseableScope | Fiber[None, Any] | None
    ready: Deferred[A]
    releasing: bool = False
    value: A | None = None
    work: Fiber[None, Any] | None = None


@dataclass(frozen=True, slots=True)
class _Ready[A]:
    scope: CloseableScope
    value: A


@dataclass(frozen=True, slots=True)
class _Failed[A]:
    ready: Deferred[A]
    releasing: Fiber[None, Any] | None


@dataclass(frozen=True, slots=True)
class _Closed:
    pass


type _State[A] = _Closed | _Ready[A] | _Pending[A] | _Failed[A]

_INTERRUPTED: Exit[Any, Any] = interrupt_exit()


@dataclass(eq=False, slots=True)
class ResourceRef[A = Unsubscripted]:
    _release_scope: CloseableScope
    _acquire: Callable[[CloseableScope], Effect[A]]
    _teardown_address: EntityAddress | None
    _state: _State[A] = field(default_factory=_Closed)

    @overload
    @classmethod
    def make[B](
        cls: type[ResourceRef[Unsubscripted]],
        parent: CloseableScope,
        acquire: Callable[[CloseableScope], Effect[B]],
        teardown_address: EntityAddress | None = None,
    ) -> Effect[ResourceRef[B]]: ...
    @overload
    @classmethod
    def make(
        cls,
        parent: CloseableScope,
        acquire: Callable[[CloseableScope], Effect[A]],
        teardown_address: EntityAddress | None = None,
    ) -> Effect[ResourceRef[A]]: ...
    @classmethod
    def make[B](
        cls,
        parent: CloseableScope,
        acquire: Callable[[CloseableScope], Effect[B]],
        teardown_address: EntityAddress | None = None,
    ) -> Effect[ResourceRef[B]]:
        """A ref holding what ``acquire`` gives (it gets the resource's own
        scope), closed with ``parent``."""

        def body() -> Generator[Effect[Any, Any, Any], Any, ResourceRef[B]]:
            release_scope = yield from parent.fork()
            ref = ResourceRef[B](release_scope, acquire, teardown_address)
            yield from parent.add_finalizer(ref._close)
            pending = ref._pending(None, Deferred[B]())
            value = yield from acquire(pending.scope)
            if ref._state is pending:
                ref._publish(pending, value)
            return ref

        return gen(body)

    def get_unsafe(self) -> A | None:
        """The resource, when one is ready."""
        state = self._state
        return state.value if isinstance(state, _Ready) else None

    @property
    def await_(self) -> Effect[A]:
        """The resource, once ready (interrupted when the ref is closed)."""

        def run() -> Effect[A]:
            state = self._state
            match state:
                case _Closed():
                    return interrupt()
                case _Ready():
                    return succeed(state.value)
                case _Pending() | _Failed():
                    return state.ready.wait()

        return suspend(run)

    def rebuild_unsafe(
        self,
        *,
        from_: A | None = None,
        prepare: Callable[[A], Effect[None]] | None = None,
    ) -> Effect[None] | None:
        """Replace the resource, unless it is no longer ``from_`` (the same
        object, when given) or the ref is closed; ``None`` when nothing is
        rebuilt."""
        state = self._state
        match state:
            case _Closed():
                return None
            case _Ready():
                if from_ is not None and from_ is not state.value:
                    return None
                pending = self._pending(state.scope, Deferred[A]())
            case _Failed():
                if from_ is not None:
                    return None
                pending = self._pending(state.releasing, state.ready)
            case _Pending():
                if from_ is None or state.value is not from_:
                    return None
                if state.work is not None:
                    state.work.interrupt_as_unsafe(None)
                pending = self._pending(state.scope, state.ready)
        return self._run(pending, prepare)

    def _pending(
        self, releases: CloseableScope | Fiber[None, Any] | None, ready: Deferred[A]
    ) -> _Pending[A]:
        pending = _Pending(CloseableScope(), releases, ready)
        self._state = pending
        return pending

    def _publish(self, pending: _Pending[A], value: A) -> None:
        self._state = _Ready(pending.scope, value)
        pending.ready.done_unsafe(Success(value))

    def _run(
        self, pending: _Pending[A], prepare: Callable[[A], Effect[None]] | None
    ) -> Effect[None]:
        def release_previous() -> Effect[None]:
            if self._state is not pending:
                return interrupt()
            releases = pending.releases
            if releases is None:
                return void
            pending.releasing = True
            waited = (
                releases.join()
                if isinstance(releases, Fiber)
                else self._release(releases).flat_map(lambda fiber: fiber.join())
            )

            def released(_: None) -> None:
                pending.releasing = False

            return waited.map(released)

        def acquired(value: A) -> Effect[None]:
            if self._state is not pending:
                return interrupt()
            pending.value = value
            prepared = void if prepare is None else prepare(value)

            def publish(_: None) -> Effect[None]:
                if self._state is not pending:
                    return interrupt()
                self._publish(pending, value)
                return void

            return prepared.flat_map(publish)

        def ended(exit: Exit[None, Any]) -> Effect[None]:
            if isinstance(exit, Success) or self._state is not pending:
                return void
            if pending.releasing:
                # Nothing was acquired: carry the waiters on without
                # rejoining the stalled release.
                self._state = _Failed(pending.ready, None)
                return void
            cause = exit.cause

            def failed(releasing: Fiber[None, Any]) -> None:
                if self._state is not pending:
                    return
                self._state = _Failed(Deferred[A](), releasing)
                pending.ready.done_unsafe(Failure(cause))

            return self._release(pending.scope).map(failed)

        work = (
            suspend(release_previous)
            .flat_map(lambda _: suspend(lambda: self._acquire(pending.scope)))
            .flat_map(acquired)
            .on_exit(ended)
        )

        def started(fiber: Fiber[None, Any]) -> Effect[None]:
            pending.work = fiber
            # Replaced or closed before the fiber existed.
            if self._state is not pending:
                fiber.interrupt_as_unsafe(None)
            return fiber.join()

        return work.fork(start_immediately=True).flat_map(started)

    def _release(self, scope: CloseableScope) -> Effect[Fiber[None, Any]]:
        """Close ``scope`` in the background (a stalled release must not
        block a rebuild)."""
        close = scope.close(Success(None))
        if self._teardown_address is not None:
            close = around_entity(self._teardown_address, close)
        return fork_in(close, self._release_scope, start_immediately=True)

    def _close(self, exit: Exit[Any, Any]) -> Effect[None]:
        state = self._state
        self._state = _Closed()
        match state:
            case _Closed():
                return void
            case _Ready():
                return state.scope.close(exit)
            case _Failed():
                return sync(lambda: state.ready.done_unsafe(_INTERRUPTED)).as_void()
            case _Pending():
                state.ready.done_unsafe(_INTERRUPTED)
                if state.work is not None:
                    state.work.interrupt_as_unsafe(None)
                close = state.scope.close(exit)
                releases = state.releases
                if isinstance(releases, CloseableScope):
                    return releases.close(exit).flat_map(lambda _: close)
                return close


__all__ = ["ResourceRef"]
