"""``Cache[K, A, E, R]``: effectful lookups shared by key."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from typing import Any, Final, Literal, Never, overload

from pyfect._core import (
    Effect,
    Frame,
    Step,
    _FlatMap,
    _FromExit,
    _SetInterruptible,
    _Succeed,
    _Sync,
    _WithFiber,
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
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.duration import Duration, zero
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some

_VOID: Final[Effect[None]] = _Succeed(None)


class Cache[K: Hashable = Unsubscripted, A = Unsubscripted, E = Never, R = Never]:
    """Make one with ``Cache.make(lookup, capacity=...)``."""

    __slots__ = ("_capacity", "_context", "_entries", "_lock", "_lookup", "_time_to_live")

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
        # Least recently used first.
        self._entries: dict[K, _Entry[A, E]] = {}
        # Runs on other threads share a cache: the entries and their waiter
        # counts change holding this; no lookup starts while it is held.
        self._lock = threading.Lock()

    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, RR = Never](
        cls: type[Cache[Unsubscripted, Unsubscripted, Any, Any]],
        lookup: Callable[[K2], Effect[T, X, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K2, T, X] | None = None,
        require_services_at: Literal["construction"] = "construction",
    ) -> Effect[Cache[K2, T, X], Never, RR]: ...
    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, RR = Never](
        cls: type[Cache[Unsubscripted, Unsubscripted, Any, Any]],
        lookup: Callable[[K2], Effect[T, X, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K2, T, X] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[Cache[K2, T, X, RR]]: ...
    @overload
    @classmethod
    def make[RR = Never](
        cls,
        lookup: Callable[[K], Effect[A, E, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["construction"] = "construction",
    ) -> Effect[Cache[K, A, E], Never, RR]: ...
    @overload
    @classmethod
    def make[RR](
        cls: type[Cache[K, A, E, RR]],
        lookup: Callable[[K], Effect[A, E, RR]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[Cache[K, A, E, RR]]: ...
    @classmethod
    def make(
        cls,
        lookup: Callable[[Any], Effect[Any, Any, Any]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[Any, Any, Any] | None = None,
        require_services_at: RequireServicesAt = "construction",
    ) -> Effect[Cache[Any, Any, Any, Any], Never, Any]:
        """A cache that looks keys up with ``lookup``, keeping at most
        ``capacity`` entries (``None``: no limit). ``time_to_live`` is a
        duration, or a function of the lookup's ``Exit`` and the key; the
        default is forever, and zero keeps nothing. Lookups see the
        services of the context made in, overridden by the caller's;
        ``require_services_at="lookup"`` makes ``get`` require them."""
        ttl = time_to_live_of(time_to_live)
        return _WithFiber(lambda fiber: _Succeed(Cache(lookup, fiber._context, capacity, ttl)))

    @property
    def capacity(self) -> int | None:
        """The most entries the cache keeps, or ``None`` for no limit."""
        return self._capacity

    def get(self, key: K) -> Effect[A, E, R]:
        """The value for ``key``: cached, joined while another caller looks
        it up, or looked up now. A lookup runs on a fiber of its own, so it
        lives on while anyone waits for it; when the last waiter leaves, it
        is interrupted and forgotten."""
        return _WithFiber(lambda fiber: self._get(fiber, key))

    def get_option(self, key: K) -> Effect[Option[A], E]:
        """``Some`` value for a cached key (waiting for a lookup in
        progress), ``None`` for a missing or expired one. Never looks up."""

        def body(fiber: Fiber[Any, Any]) -> Effect[Option[A], E]:
            with self._lock:
                entry = self._find(fiber, key, touch=True)
            return _Succeed(None) if entry is None else entry.await_from(fiber).map(Some)

        return _WithFiber(body)

    def get_success(self, key: K) -> Effect[Option[A]]:
        """``Some`` value for a key whose lookup has succeeded, else
        ``None``. Never waits."""

        def body(fiber: Fiber[Any, Any]) -> Effect[Option[A]]:
            with self._lock:
                entry = self._find(fiber, key, touch=True)
            ex = None if entry is None else entry.fiber.poll_unsafe()
            return _Succeed(Some(ex.value) if isinstance(ex, Success) else None)

        return _WithFiber(body)

    def set(self, key: K, value: A) -> Effect[None]:
        """Cache ``value`` for ``key`` with the time to live of a successful
        lookup."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            ex: Exit[A, E] = Success(value)
            ttl = self._time_to_live(ex, key)
            if ttl.is_zero():
                self._discard(key)
                return _VOID
            entry = _Entry[A, E](_finished(fiber, ex), self._lock)
            entry.expires_at = deadline(clock_of(fiber), ttl)
            with self._lock:
                self._entries[key] = entry
                self._evict_overflow()
            return _VOID

        return _WithFiber(body)

    def has(self, key: K) -> Effect[bool]:
        """Whether ``key`` is cached and unexpired (a lookup in progress
        counts). Does not count as a use."""

        def body(fiber: Fiber[Any, Any]) -> Effect[bool]:
            with self._lock:
                return _Succeed(self._find(fiber, key, touch=False) is not None)

        return _WithFiber(body)

    def invalidate(self, key: K) -> Effect[None]:
        """Forget ``key``. A lookup in progress goes on for its waiters."""
        return _Sync(lambda: self._discard(key))

    def invalidate_when(self, key: K, predicate: Callable[[A], bool]) -> Effect[bool]:
        """Forget ``key`` if its value (waited for if still being looked up)
        passes ``predicate``. ``False`` if it did not, if the lookup failed,
        or if the entry was replaced meanwhile."""

        def body(fiber: Fiber[Any, Any]) -> Effect[bool]:
            with self._lock:
                entry = self._find(fiber, key, touch=False)
            if entry is None:
                return _Succeed(False)

            def check(value: A) -> bool:
                if not predicate(value):
                    return False
                with self._lock:
                    if self._entries.get(key) is not entry:
                        return False
                    del self._entries[key]
                    return True

            return entry.await_from(fiber).map(check).catch_cause(lambda _: _Succeed(False))

        return _WithFiber(body)

    def refresh(self, key: K) -> Effect[A, E, R]:
        """Look ``key`` up again. A cached value keeps serving ``get`` until
        the new lookup succeeds or fails; a missing key is cached at once,
        as ``get`` would."""
        return _WithFiber(lambda fiber: self._refresh(fiber, key))

    def invalidate_all(self) -> Effect[None]:
        """Forget every key."""

        def clear() -> None:
            with self._lock:
                self._entries.clear()

        return _Sync(clear)

    def size(self) -> Effect[int]:
        """How many entries the cache holds, expired ones included until
        something reads them."""
        return _Sync(lambda: len(self._entries))

    def keys(self) -> Effect[list[K]]:
        """The unexpired keys, least recently used first. Drops the
        expired ones."""
        return _WithFiber(lambda fiber: _Succeed([key for key, _ in self._live(fiber)]))

    def values(self) -> Effect[list[A]]:
        """The values of the unexpired, successful lookups."""
        return self.entries().map(lambda pairs: [value for _, value in pairs])

    def entries(self) -> Effect[list[tuple[K, A]]]:
        """The keys and values of the unexpired, successful lookups. Drops
        the expired entries."""

        def body(fiber: Fiber[Any, Any]) -> Effect[list[tuple[K, A]]]:
            pairs: list[tuple[K, A]] = []
            for key, entry in self._live(fiber):
                ex = entry.fiber.poll_unsafe()
                if isinstance(ex, Success):
                    pairs.append((key, ex.value))
            return _Succeed(pairs)

        return _WithFiber(body)

    def __repr__(self) -> str:
        return f"Cache(size={len(self._entries)}, capacity={self._capacity})"

    def _get(self, fiber: Fiber[Any, Any], key: K) -> Effect[A, E]:
        # The new entry goes in before its lookup starts, so a get from a
        # run on another thread joins it rather than looking up again; a
        # lookup that ends interrupted or with a zero time to live takes it
        # out as it ends, so it is never cached.
        found = self._touch_or_insert(fiber, key)
        if isinstance(found, _Entry):
            return found.await_from(fiber)
        entry, start = found
        clock = clock_of(fiber)

        def observe(ex: Exit[A, E]) -> None:
            with self._lock:
                entry.release = None  # no longer abandoned by its waiters leaving
                if _interrupted(ex) or entry.time_to_live.is_zero():
                    self._remove(key, entry)
                else:
                    entry.expires_at = deadline(clock, entry.time_to_live)

        entry.fiber.add_observer_unsafe(observe)
        start()
        return entry.await_from(fiber)

    def _touch_or_insert(
        self, fiber: Fiber[Any, Any], key: K
    ) -> _Entry[A, E] | tuple[_Entry[A, E], Callable[[], None]]:
        """The unexpired entry for ``key``, made the most recently used; or
        a new entry put in its place, with the call that starts its lookup."""
        with self._lock:
            entries = self._entries
            found = entries.pop(key, None)
            if found is not None and not is_expired(found.expires_at, _now(fiber)):
                entries[key] = found
                return found
            entry, start = self._entry(fiber, key)
            entries[key] = entry
            self._evict_overflow()
            return entry, start

    def _refresh(self, fiber: Fiber[Any, Any], key: K) -> Effect[A, E]:
        entry, start = self._entry(fiber, key)
        start()
        clock = clock_of(fiber)
        with self._lock:
            existing = self._find(fiber, key, touch=False) is not None
            if not existing:
                self._entries[key] = entry
                self._evict_overflow()

        def observe(ex: Exit[A, E]) -> None:
            with self._lock:
                entry.release = None
                if _interrupted(ex):
                    self._remove(key, entry)
                    return
                ttl = entry.time_to_live
                if ttl.is_zero():
                    if existing:
                        self._entries.pop(key, None)
                    else:
                        self._remove(key, entry)
                    return
                entry.expires_at = deadline(clock, ttl)
                if existing:
                    self._entries[key] = entry
                    self._evict_overflow()

        entry.fiber.add_observer_unsafe(observe)
        return entry.await_from(fiber)

    def _entry(self, fiber: Fiber[Any, Any], key: K) -> tuple[_Entry[A, E], Callable[[], None]]:
        """An entry and the call that starts its lookup: at once, up to its
        first wait (Effect's immediate fork), on a root fiber with this
        cache's services overridden by the caller's. A raising ``lookup``
        fails the caller with a defect, as in Effect. Start it without the
        lock: it runs the lookup.

        The time to live is decided inside the lookup fiber, so the fiber's
        observers call no user code: a raising ``time_to_live`` keeps
        nothing and becomes the lookup's defect, which ends every caller.
        (Effect calls it in an observer, where a raise hangs the callers.)"""
        lookup = self._lookup(key)
        lookup_fiber: Fiber[A, E] = new_root(
            fiber._run_scheduler, self._context.merge(fiber._context)
        )
        entry = _Entry[A, E](lookup_fiber, self._lock)
        entry.release = lambda: self._remove(key, entry)

        def decide_time_to_live(ex: Exit[A, E]) -> Effect[None]:
            if not _interrupted(ex):
                entry.time_to_live = self._time_to_live(ex, key)
            return _VOID

        return entry, lambda: start_root(lookup_fiber, lookup.on_exit(decide_time_to_live))

    def _find(self, fiber: Fiber[Any, Any], key: K, *, touch: bool) -> _Entry[A, E] | None:
        """The unexpired entry for ``key`` (an expired one is dropped);
        ``touch`` makes it the most recently used. Call holding the lock."""
        entries = self._entries
        entry = entries.get(key)
        if entry is None:
            return None
        if is_expired(entry.expires_at, _now(fiber)):
            del entries[key]
            return None
        if touch:
            del entries[key]
            entries[key] = entry
        return entry

    def _live(self, fiber: Fiber[Any, Any]) -> list[tuple[K, _Entry[A, E]]]:
        """The unexpired entries in use order. Drops the expired ones."""
        now = _now(fiber)
        live: list[tuple[K, _Entry[A, E]]] = []
        with self._lock:
            for key, entry in list(self._entries.items()):
                if is_expired(entry.expires_at, now):
                    del self._entries[key]
                else:
                    live.append((key, entry))
        return live

    def _discard(self, key: K) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _remove(self, key: K, entry: _Entry[A, E]) -> None:
        """Call holding the lock."""
        if self._entries.get(key) is entry:
            del self._entries[key]

    def _evict_overflow(self) -> None:
        """Call holding the lock."""
        for key in overflow(self._entries, self._capacity):
            del self._entries[key]


class _Entry[A, E]:
    """A lookup and the callers waiting on it."""

    __slots__ = ("awaiters", "expires_at", "fiber", "lock", "release", "time_to_live")

    def __init__(self, fiber: Fiber[A, E], lock: threading.Lock) -> None:
        self.fiber = fiber
        # The cache's.
        self.lock = lock
        self.awaiters = 0
        self.expires_at: int | None = None
        # Set as the lookup ends; stays zero if ``time_to_live`` raised.
        self.time_to_live: Duration = zero
        # Drops the entry from the cache when its waiters abandon it; call
        # holding the lock.
        self.release: Callable[[], None] | None = None

    def wait(self) -> Effect[A, E]:
        """Wait for the lookup as one more caller (Effect's ``entry.await``)."""
        return _WithFiber(self.await_from)

    def await_from(self, fiber: Fiber[Any, Any]) -> Effect[A, E]:
        """``fiber`` waits for the lookup. It is counted in the same step,
        so it leaves however its wait ends, even interrupted before
        starting."""
        ex = self.fiber.poll_unsafe()
        if ex is not None:
            return _FromExit(ex)
        with self.lock:
            self.awaiters += 1
        fiber._push(_Leave(self))
        return self.fiber.join()

    def leave(self) -> Effect[None] | None:
        """A caller stopped waiting. Gives the effect that abandons the
        lookup if that caller was the last one."""
        with self.lock:
            self.awaiters -= 1
            if self.awaiters > 0 or self.fiber.poll_unsafe() is not None:
                return None
            # Detached first, so a get made while the lookup's finalizers run
            # starts a new lookup.
            if self.release is not None:
                self.release()
        return self.fiber.interrupt()


class _Leave(Frame):
    """Pushed by a caller waiting on an entry. Abandoning the lookup
    happens uninterruptibly; then the caller ends as its wait did."""

    __slots__ = ("entry",)

    def __init__(self, entry: _Entry[Any, Any]) -> None:
        self.entry = entry

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        return self._leave(Success(value), fiber)

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        return self._leave(Failure(cause), fiber)

    def _leave(self, ex: Exit[Any, Any], fiber: Fiber[Any, Any]) -> Step:
        abandon = self.entry.leave()
        if abandon is None:
            return ex
        # Stepped here, not returned: an interrupted fiber would turn a
        # returned effect into a failure before it could run.
        return _SetInterruptible(_FlatMap(abandon, lambda _: _FromExit(ex)), False)._step(fiber)


def _finished[A, E](fiber: Fiber[Any, Any], ex: Exit[A, E]) -> Fiber[A, E]:
    done: Fiber[A, E] = new_root(fiber._run_scheduler, fiber._context)
    start_root(done, _FromExit(ex))
    return done


def _interrupted(ex: Exit[Any, Any]) -> bool:
    return isinstance(ex, Failure) and ex.cause.has_interrupts


def _now(fiber: Fiber[Any, Any]) -> int:
    return clock_of(fiber).now_nanos_unsafe()
