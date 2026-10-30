"""A map of resources built on first ``get`` (Effect's
``internal/resourceMap``). Each entry gets its own scope, closed on
``remove`` or when the map's scope closes. Concurrent ``get``s of a key
share one lookup; when every one of them is interrupted before it ends,
the lookup is interrupted and the next ``get`` starts afresh."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any, Never

from pyfect._concurrency import for_each
from pyfect._core import (
    Effect,
    Restore,
    _Locally,
    _Succeed,
    _Suspend,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._fiber import Fiber
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.effect import interrupt
from pyfect.exit import Exit, Success
from pyfect.scope import CloseableScope, Scope


class _Entry[A, E]:
    __slots__ = ("awaiters", "deferred", "fiber", "scope")

    def __init__(self) -> None:
        self.scope = CloseableScope()
        self.deferred: Deferred[A, E] = Deferred()
        self.fiber: Fiber[Any, Any] | None = None
        self.awaiters = 0


class ResourceMap[K: Hashable, A, E]:
    __slots__ = ("_closed", "_entries", "_lookup")

    def __init__(self, lookup: Callable[[K, CloseableScope], Effect[A, E]]) -> None:
        self._lookup = lookup
        self._entries: dict[K, _Entry[A, E]] = {}
        self._closed = False

    @staticmethod
    def make[K2: Hashable, A2, E2, R = Never](
        lookup: Callable[[K2], Effect[A2, E2, R | Scope]],
    ) -> Effect[ResourceMap[K2, A2, E2], Never, R | Scope]:
        """A map whose entries are built by ``lookup`` (with their own
        ``Scope``, and the services of the fiber making the map); closing
        the current scope interrupts pending lookups and closes every
        entry's scope."""

        def body(fiber: Fiber[Any, Any]) -> Effect[ResourceMap[K2, A2, E2], Never, Any]:
            services: Context = fiber._context
            scope: CloseableScope = services.get(Scope)

            def run(key: K2, entry_scope: CloseableScope) -> Effect[A2, E2]:
                return _Locally(
                    lookup(key), lambda current: current.merge(services).add(Scope, entry_scope)
                )

            resource_map = ResourceMap[K2, A2, E2](run)
            return scope.add_finalizer(resource_map._close).as_(resource_map)

        return _WithFiber(body)

    def _close(self, ex: Exit[Any, Any]) -> Effect[None]:
        def body() -> Effect[None]:
            self._closed = True
            entries = list(self._entries.items())
            self._entries.clear()

            def close(entry: _Entry[A, E]) -> Effect[object]:
                interrupting = _Succeed(None) if entry.fiber is None else entry.fiber.interrupt()
                return interrupting.and_then(entry.scope.close(ex)).exit()

            return for_each(
                [entry for _, entry in entries], close, concurrency="unbounded"
            ).as_void()

        return _Suspend(body)

    def unsafe_has(self, key: K) -> bool:
        return key in self._entries

    def unsafe_keys(self) -> list[K]:
        return list(self._entries)

    def get(self, key: K) -> Effect[A, E]:
        """The resource under ``key``, looked up if it is not there yet.
        A failed lookup leaves no entry and closes its scope. A closed map
        interrupts the caller."""

        def body(restore: Restore) -> Effect[A, E]:
            if self._closed:
                return interrupt()
            existing = self._entries.get(key)
            if existing is not None:
                return self._await_entry(key, existing, restore)
            entry = _Entry[A, E]()
            self._entries[key] = entry

            def on_exit(ex: Exit[A, E]) -> Effect[object]:
                if isinstance(ex, Success):
                    return entry.deferred.done(ex)
                self._delete_entry(key, entry)
                return entry.deferred.done(ex).and_then(entry.scope.close(ex))

            def start(fiber: Fiber[Any, Any]) -> Effect[A, E]:
                entry.fiber = fiber._fork(
                    self._lookup(key, entry.scope).on_exit(on_exit), daemon=True
                )
                return self._await_entry(key, entry, restore)

            return _WithFiber(start)

        return uninterruptible_mask(body)

    def _await_entry(self, key: K, entry: _Entry[A, E], restore: Restore) -> Effect[A, E]:
        if entry.deferred.unsafe_is_done():
            return entry.deferred.wait()
        entry.awaiters += 1

        def on_exit(_: Exit[A, E]) -> Effect[None]:
            entry.awaiters -= 1
            if entry.awaiters > 0 or entry.deferred.unsafe_is_done() or entry.fiber is None:
                return _Succeed(None)
            self._delete_entry(key, entry)
            return entry.fiber.interrupt()

        return restore(entry.deferred.wait()).on_exit(on_exit)

    def _delete_entry(self, key: K, entry: _Entry[A, E]) -> None:
        if self._entries.get(key) is entry:
            del self._entries[key]

    def remove(self, key: K) -> Effect[None]:
        """Drop the entry under ``key`` and close its scope."""

        def body() -> Effect[None]:
            entry = self._entries.pop(key, None)
            if entry is None:
                return _Succeed(None)
            return entry.scope.close(Success(None))

        return _Suspend(body)
