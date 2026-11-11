"""``ScopedCache[K, A, E, R]``: a ``Cache`` of scoped resources.

Each entry owns a scope that its lookup's resources live in. The scope
closes when the entry leaves the cache: evicted, expired, replaced,
invalidated, or the cache's own scope closing. A closed cache interrupts
every operation that needs its entries.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any, Final, Literal, Never, overload

from pyfect._core import (
    Effect,
    Restore,
    _FailCause,
    _Locally,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._fiber import Fiber
from pyfect._root import new_root, start_root
from pyfect._unsubscripted import Unsubscripted
from pyfect.cache._expiry import (
    RequireServicesAt,
    TimeToLive,
    clock_of,
    deadline,
    is_expired,
    overflow,
    time_to_live_of,
)
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Duration
from pyfect.effect import from_exit, interrupt
from pyfect.exit import Exit, Failure, Success, as_void_all
from pyfect.logger._log import log_unhandled
from pyfect.option import Option, Some
from pyfect.scope import CloseableScope, Scope

_VOID: Final[Effect[None]] = _Succeed(None)
_DONE: Final[Exit[None, Never]] = Success(None)


class ScopedCache[K: Hashable = Unsubscripted, A = Unsubscripted, E = Never, R = Never]:
    """Make one with ``ScopedCache.make(lookup, capacity=...)`` inside a
    scope."""

    __slots__ = ("_capacity", "_context", "_entries", "_lookup", "_time_to_live")

    def __init__(
        self,
        lookup: Callable[[K], Effect[A, E, Any]],
        context: Context,
        capacity: int | None,
        time_to_live: Callable[[Exit[A, E], K], Duration],
    ) -> None:
        self._lookup = lookup
        self._context = context
        self._capacity = capacity
        self._time_to_live = time_to_live
        # Least recently used first; None once the cache's scope closed.
        self._entries: dict[K, _Entry[A, E]] | None = {}

    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, RR = Never](
        cls: type[ScopedCache[Unsubscripted, Unsubscripted, Any, Any]],
        lookup: Callable[[K2], Effect[T, X, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K2, T, X] | None = None,
        require_services_at: Literal["construction"] = "construction",
    ) -> Effect[ScopedCache[K2, T, X], Never, RR | Scope]: ...
    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never](
        cls: type[ScopedCache[Unsubscripted, Unsubscripted, Any, Any]],
        lookup: Callable[[K2], Effect[T, X, Scope]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K2, T, X] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[ScopedCache[K2, T, X], Never, Scope]: ...
    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, RR = Never](
        cls: type[ScopedCache[Unsubscripted, Unsubscripted, Any, Any]],
        lookup: Callable[[K2], Effect[T, X, Scope | RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K2, T, X] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[ScopedCache[K2, T, X, RR], Never, Scope]: ...
    @overload
    @classmethod
    def make[RR = Never](
        cls,
        lookup: Callable[[K], Effect[A, E, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["construction"] = "construction",
    ) -> Effect[ScopedCache[K, A, E], Never, RR | Scope]: ...
    @overload
    @classmethod
    def make(
        cls,
        lookup: Callable[[K], Effect[A, E, Scope]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[ScopedCache[K, A, E], Never, Scope]: ...
    @overload
    @classmethod
    def make[RR](
        cls: type[ScopedCache[K, A, E, RR]],
        lookup: Callable[[K], Effect[A, E, Scope | RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[ScopedCache[K, A, E, RR], Never, Scope]: ...
    @classmethod
    def make(
        cls,
        lookup: Callable[[Any], Effect[Any, Any, Any]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[Any, Any, Any] | None = None,
        require_services_at: RequireServicesAt = "construction",
    ) -> Effect[ScopedCache[Any, Any, Any, Any], Never, Any]:
        """A cache that looks keys up with ``lookup``, each in a scope of
        its own, closed when the entry leaves the cache, and all of them
        when the current scope closes. Options as ``Cache.make``; the
        lookup's ``Scope`` is the entry's, never a requirement."""
        ttl = time_to_live_of(time_to_live)

        def body(fiber: Fiber[Any, Any]) -> Effect[ScopedCache[Any, Any, Any, Any]]:
            context = fiber._context
            cache = ScopedCache(lookup, context, capacity, ttl)
            closing = context.get_unsafe(Scope).add_finalizer(lambda _: _WithFiber(cache._close))
            return closing.as_(cache)

        return _WithFiber(body)

    @property
    def capacity(self) -> int | None:
        """The most entries the cache keeps, or ``None`` for no limit."""
        return self._capacity

    @property
    def is_closed(self) -> bool:
        """Whether the scope the cache was made in has closed."""
        return self._entries is None

    def get(self, key: K) -> Effect[A, E, R]:
        """The value for ``key``: cached, joined while another caller looks
        it up, or looked up now. The resource stays open while the entry
        is cached. When the last waiter leaves a lookup in progress, the
        lookup is interrupted and forgotten."""

        def body(restore: Restore) -> Effect[A, E]:
            return _WithFiber(lambda fiber: self._get(fiber, key, restore))

        return uninterruptible_mask(body)

    def get_option(self, key: K) -> Effect[Option[A], E]:
        """``Some`` value for a cached key (waiting for a lookup in
        progress), ``None`` for a missing or expired one. Never looks up."""

        def body(restore: Restore) -> Effect[Option[A], E]:
            def run(fiber: Fiber[Any, Any]) -> Effect[Option[A], E]:
                def then(entry: _Entry[A, E] | None) -> Effect[Option[A], E]:
                    if entry is None:
                        return _Succeed(None)
                    return self._await(key, entry, restore).map(Some)

                return self._find(fiber, key, touch=True).flat_map(then)

            return _WithFiber(run)

        return uninterruptible_mask(body)

    def get_success(self, key: K) -> Effect[Option[A]]:
        """``Some`` value for a key whose lookup has succeeded, else
        ``None``. Never waits."""

        def success(entry: _Entry[A, E] | None) -> Option[A]:
            ex = None if entry is None else entry.exit
            return Some(ex.value) if isinstance(ex, Success) else None

        return _WithFiber(
            lambda fiber: self._find(fiber, key, touch=True).map(success)
        ).uninterruptible()

    def set(self, key: K, value: A) -> Effect[None]:
        """Cache ``value`` for ``key`` with the time to live of a successful
        lookup, closing the scope of the entry it replaces."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            entries = self._entries
            if entries is None:
                return interrupt()
            replaced = entries.get(key)
            ex: Exit[A, E] = Success(value)
            entry = _Entry[A, E]()
            entry.complete(ex)
            entry.expires_at = deadline(clock_of(fiber), self._time_to_live(ex, key))
            entries[key] = entry
            evicting = self._evict_overflow(fiber, entries)
            if replaced is None:
                return evicting
            return replaced.scope.close(_DONE).and_then(evicting)

        return _WithFiber(body).uninterruptible()

    def has(self, key: K) -> Effect[bool]:
        """Whether ``key`` is cached and unexpired (a lookup in progress
        counts). Does not count as a use; closes an expired entry."""
        return _WithFiber(
            lambda fiber: self._find(fiber, key, touch=False).map(lambda e: e is not None)
        ).uninterruptible()

    def invalidate(self, key: K) -> Effect[None]:
        """Forget ``key`` and close its scope."""

        def body() -> Effect[None]:
            entries = self._entries
            if entries is None:
                return interrupt()
            entry = entries.pop(key, None)
            return _VOID if entry is None else entry.scope.close(_DONE)

        return _Suspend(body).uninterruptible()

    def invalidate_when(self, key: K, predicate: Callable[[A], bool]) -> Effect[bool]:
        """Forget ``key`` and close its scope if its value (waited for if
        still being looked up) passes ``predicate``. ``False`` if it did
        not, if the lookup failed, or if the entry was replaced meanwhile."""

        def body(restore: Restore) -> Effect[bool]:
            def run(fiber: Fiber[Any, Any]) -> Effect[bool]:
                def then(entry: _Entry[A, E] | None) -> Effect[bool]:
                    if entry is None:
                        return _Succeed(False)

                    def check(value: A) -> Effect[bool]:
                        entries = self._entries
                        if entries is None or not predicate(value):
                            return _Succeed(False)
                        if entries.get(key) is not entry:
                            return _Succeed(False)
                        del entries[key]
                        return entry.scope.close(_DONE).as_(True)

                    waited = self._await(key, entry, restore).flat_map(check)
                    return waited.catch_all(lambda _: _Succeed(False))

                return self._find(fiber, key, touch=False).flat_map(then)

            return _WithFiber(run)

        return uninterruptible_mask(body)

    def refresh(self, key: K) -> Effect[A, E, R]:
        """Look ``key`` up again in a new scope. The cached entry keeps
        serving ``get`` until the new lookup ends; then the new outcome
        replaces it and its scope closes. A missing key is looked up as
        ``get`` would. An interrupted refresh changes nothing."""

        def body(restore: Restore) -> Effect[A, E, R]:
            return _WithFiber(lambda fiber: self._refresh(fiber, key, restore))

        return uninterruptible_mask(body)

    def invalidate_all(self) -> Effect[None]:
        """Forget every key and close every entry's scope at once; fails
        with every release failure."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            entries = self._entries
            return interrupt() if entries is None else _release_all(fiber, entries)

        return _WithFiber(body)

    def size(self) -> Effect[int]:
        """How many entries the cache holds, expired ones included until
        something reads them; 0 once closed."""
        return _Sync(lambda: 0 if self._entries is None else len(self._entries))

    def keys(self) -> Effect[list[K]]:
        """The unexpired keys, least recently used first. Closes the
        expired entries."""
        return self._read(lambda key, _: key)

    def values(self) -> Effect[list[A]]:
        """The values of the unexpired, successful lookups."""
        return self.entries().map(lambda pairs: [value for _, value in pairs])

    def entries(self) -> Effect[list[tuple[K, A]]]:
        """The keys and values of the unexpired, successful lookups.
        Closes the expired entries."""

        def pair(key: K, entry: _Entry[A, E]) -> tuple[K, A] | None:
            ex = entry.exit
            return (key, ex.value) if isinstance(ex, Success) else None

        return self._read(pair)

    def __repr__(self) -> str:
        if self._entries is None:
            return "ScopedCache(closed)"
        return f"ScopedCache(size={len(self._entries)}, capacity={self._capacity})"

    def _get(self, fiber: Fiber[Any, Any], key: K, restore: Restore) -> Effect[A, E]:
        entries = self._entries
        if entries is None:
            return interrupt()
        found = entries.get(key)
        if found is not None and not is_expired(found.expires_at, _now(fiber)):
            del entries[key]
            entries[key] = found  # the most recently used now
            return self._await(key, found, restore)
        entry = _Entry[A, E]()
        entries[key] = entry  # an expired entry is replaced in place
        evicting = self._evict_overflow(fiber, entries)
        if found is not None:
            evicting = evicting.and_then(_close_evicted(found))
        return evicting.and_then(_Suspend(lambda: self._start(fiber, key, entry, restore)))

    def _start(
        self, fiber: Fiber[Any, Any], key: K, entry: _Entry[A, E], restore: Restore
    ) -> Effect[A, E]:
        """Run the lookup up to its first wait (Effect's immediate fork) on
        a root fiber, in the entry's scope, with this cache's services
        overridden by the caller's; then wait for it."""
        context = self._context.merge(fiber._context).add(Scope, entry.scope)
        lookup_fiber: Fiber[A, E] = new_root(fiber._run_scheduler, context)
        entry.fiber = lookup_fiber
        clock = clock_of(fiber)

        def settle(ex: Exit[A, E]) -> Effect[None]:
            if _interrupted(ex):
                self._remove(key, entry)
                entry.complete(ex)
                return entry.scope.close(ex)
            try:
                entry.expires_at = deadline(clock, self._time_to_live(ex, key))
            finally:
                entry.complete(ex)
            return _VOID

        start_root(lookup_fiber, _Suspend(lambda: self._lookup(key)).on_exit(settle))
        return self._await(key, entry, restore)

    def _await(self, key: K, entry: _Entry[A, E], restore: Restore) -> Effect[A, E]:
        """Wait for ``entry`` as one more caller. Counted before the wait
        starts, so it leaves however the wait ends; the last caller to
        leave a lookup in progress interrupts it."""
        if entry.exit is not None:
            return restore(entry.deferred.wait())
        entry.awaiters += 1

        def leave(_: Exit[A, E]) -> Effect[None]:
            entry.awaiters -= 1
            lookup = entry.fiber
            if entry.awaiters > 0 or lookup is None or entry.exit is not None:
                return _VOID
            # Detached first, so a get made while the lookup's finalizers
            # run starts a new lookup.
            self._remove(key, entry)

            def report(_: None) -> Effect[None]:
                ex = lookup.poll_unsafe()
                if isinstance(ex, Failure) and ex.cause.has_dies:
                    return _FailCause(ex.cause.without_failures())
                return _VOID

            return lookup.interrupt().flat_map(report)

        return restore(entry.deferred.wait()).on_exit(leave)

    def _refresh(self, fiber: Fiber[Any, Any], key: K, restore: Restore) -> Effect[A, E, R]:
        entries = self._entries
        if entries is None:
            return interrupt()
        if key not in entries:
            return restore(self.get(key))
        scope = CloseableScope()
        lookup = _Suspend(lambda: self._lookup(key))
        provided: Effect[A, E] = _Locally(
            lookup, lambda current: self._context.merge(current).add(Scope, scope)
        )
        clock = clock_of(fiber)

        def replace(ex: Exit[A, E]) -> Effect[A, E]:
            if _interrupted(ex):
                return scope.close(ex).and_then(from_exit(ex))
            entries = self._entries
            if entries is None:
                return scope.close(_DONE).and_then(interrupt())
            entry = _Entry[A, E](scope)
            entry.complete(ex)
            entry.expires_at = deadline(clock, self._time_to_live(ex, key))
            replaced = entries.get(key)
            entries[key] = entry
            done = self._evict_overflow(fiber, entries)
            if replaced is not None:
                done = done.and_then(replaced.scope.close(_DONE))
            return done.and_then(from_exit(ex))

        return restore(provided).exit().flat_map(replace)

    def _find(self, fiber: Fiber[Any, Any], key: K, *, touch: bool) -> Effect[_Entry[A, E] | None]:
        """The unexpired entry for ``key``; an expired one is dropped and
        closed. ``touch`` makes it the most recently used. Interrupted once
        closed."""
        entries = self._entries
        if entries is None:
            return interrupt()
        entry = entries.get(key)
        if entry is None:
            return _Succeed(None)
        if is_expired(entry.expires_at, _now(fiber)):
            del entries[key]
            return _close_evicted(entry).as_(None)
        if touch:
            del entries[key]
            entries[key] = entry
        return _Succeed(entry)

    def _read[B](self, pick: Callable[[K, _Entry[A, E]], B | None]) -> Effect[list[B]]:
        """``pick`` over the unexpired entries in use order, keeping what
        is not ``None``; the expired ones are dropped and closed."""

        def body(fiber: Fiber[Any, Any]) -> Effect[list[B]]:
            entries = self._entries
            if entries is None:
                return _Succeed([])
            now = _now(fiber)
            picked: list[B] = []
            expired: list[Effect[None]] = []
            for key, entry in list(entries.items()):
                if is_expired(entry.expires_at, now):
                    del entries[key]
                    expired.append(_close_evicted(entry))
                else:
                    item = pick(key, entry)
                    if item is not None:
                        picked.append(item)
            if not expired:
                return _Succeed(picked)
            return _await_forked(fiber, expired, daemon=True).as_(picked)

        return _WithFiber(body)

    def _evict_overflow(
        self, fiber: Fiber[Any, Any], entries: dict[K, _Entry[A, E]]
    ) -> Effect[None]:
        """Drop the least recently used entries beyond capacity and close
        their scopes at once, reporting no failure."""
        evicted = [_close_evicted(entries.pop(key)) for key in overflow(entries, self._capacity)]
        if not evicted:
            return _VOID
        return _await_forked(fiber, evicted, daemon=False).as_void()

    def _remove(self, key: K, entry: _Entry[A, E]) -> None:
        entries = self._entries
        if entries is not None and entries.get(key) is entry:
            del entries[key]

    def _close(self, fiber: Fiber[Any, Any]) -> Effect[None]:
        entries = self._entries
        if entries is None:
            return _VOID
        self._entries = None
        return _release_all(fiber, entries)


class _Entry[A, E]:
    """A lookup, its scope, and the callers waiting on it."""

    __slots__ = ("awaiters", "deferred", "exit", "expires_at", "fiber", "scope")

    def __init__(self, scope: CloseableScope | None = None) -> None:
        self.scope = CloseableScope() if scope is None else scope
        self.deferred: Deferred[A, E] = Deferred()
        self.exit: Exit[A, E] | None = None
        self.expires_at: int | None = None
        self.awaiters = 0
        # The running lookup; None for an entry that never ran one here.
        self.fiber: Fiber[A, E] | None = None

    def complete(self, ex: Exit[A, E]) -> None:
        self.exit = ex
        self.deferred.done_unsafe(ex)


def _release_all(fiber: Fiber[Any, Any], entries: dict[Any, _Entry[Any, Any]]) -> Effect[None]:
    """Empty ``entries`` and close every scope at once; fails with every
    release failure. Emptied before any finalizer runs, so finalizers that
    use the cache see it empty."""
    closing = [entry.scope.close(_DONE) for entry in entries.values()]
    entries.clear()
    exits = _await_forked(fiber, closing, daemon=True, uninterruptible=True)
    return exits.flat_map(lambda done: from_exit(as_void_all(done)))


def _close_evicted(entry: _Entry[Any, Any]) -> Effect[None]:
    """Close an entry the cache let go of. A failing finalizer must not
    fail the unrelated caller that triggered the eviction, so its failure
    is logged at the ``UnhandledLogLevel``."""
    return entry.scope.close(_DONE).catch_cause(
        lambda cause: log_unhandled("Unhandled error in ScopedCache finalizer", cause)
    )


def _await_forked(
    fiber: Fiber[Any, Any],
    effects: list[Effect[None]],
    *,
    daemon: bool,
    uninterruptible: bool = False,
) -> Effect[list[Exit[None, Never]]]:
    """Start every effect on its own fiber at once and wait for them all."""
    fibers: list[Fiber[None, Never]] = [
        fiber._fork(eff, daemon=daemon, start_immediately=True, uninterruptible=uninterruptible)
        for eff in effects
    ]
    return Fiber.await_all(fibers)


def _interrupted(ex: Exit[Any, Any]) -> bool:
    return isinstance(ex, Failure) and ex.cause.has_interrupts


def _now(fiber: Fiber[Any, Any]) -> int:
    return clock_of(fiber).now_nanos_unsafe()
