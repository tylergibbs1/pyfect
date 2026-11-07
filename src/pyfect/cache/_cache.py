"""``Cache[K, A, E, R]``: effectful lookups shared by key."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

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
from pyfect.duration import ZERO, Seconds
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some

_VOID: Final[Effect[None]] = _Succeed(None)


class Cache[K: Hashable = Unsubscripted, A = Unsubscripted, E = Never, R = Never]:
    """Make one with ``Cache.make(lookup, capacity=...)``."""

    __slots__ = ("_capacity", "_context", "_entries", "_lookup", "_time_to_live")

    def __init__(
        self,
        lookup: Callable[[K], Effect[A, E, Any]],
        context: Context,
        capacity: int | None,
        time_to_live: Callable[[Exit[A, E], K], Seconds],
    ) -> None:
        self._lookup = lookup
        self._context = context
        self._capacity = capacity
        self._time_to_live = time_to_live
        # Least recently used first.
        self._entries: dict[K, _Entry[A, E]] = {}

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
    def make(
        cls,
        lookup: Callable[[K], Effect[A, E, R]],
        *,
        capacity: int | None,
        time_to_live: TimeToLive[K, A, E] | None = None,
        require_services_at: Literal["lookup"],
    ) -> Effect[Cache[K, A, E, R]]: ...
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
            entry = self._find(fiber, key, touch=True)
            return _Succeed(None) if entry is None else entry.await_from(fiber).map(Some)

        return _WithFiber(body)

    def get_success(self, key: K) -> Effect[Option[A]]:
        """``Some`` value for a key whose lookup has succeeded, else
        ``None``. Never waits."""

        def body(fiber: Fiber[Any, Any]) -> Effect[Option[A]]:
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
            if ttl == 0:
                self._discard(key)
                return _VOID
            entry = _Entry[A, E](_finished(fiber, ex))
            entry.expires_at = deadline(clock_of(fiber), ttl)
            self._entries[key] = entry
            self._evict_overflow()
            return _VOID

        return _WithFiber(body)

    def has(self, key: K) -> Effect[bool]:
        """Whether ``key`` is cached and unexpired (a lookup in progress
        counts). Does not count as a use."""
        return _WithFiber(lambda fiber: _Succeed(self._find(fiber, key, touch=False) is not None))

    def invalidate(self, key: K) -> Effect[None]:
        """Forget ``key``. A lookup in progress goes on for its waiters."""
        return _Sync(lambda: self._discard(key))

    def invalidate_when(self, key: K, predicate: Callable[[A], bool]) -> Effect[bool]:
        """Forget ``key`` if its value (waited for if still being looked up)
        passes ``predicate``. ``False`` if it did not, if the lookup failed,
        or if the entry was replaced meanwhile."""

        def body(fiber: Fiber[Any, Any]) -> Effect[bool]:
            entry = self._find(fiber, key, touch=False)
            if entry is None:
                return _Succeed(False)

            def check(value: A) -> bool:
                if not predicate(value) or self._entries.get(key) is not entry:
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
        return _Sync(self._entries.clear)

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
        entries = self._entries
        found = entries.pop(key, None)
        if found is not None and not is_expired(found.expires_at, _now(fiber)):
            entries[key] = found  # the most recently used now
            return found.await_from(fiber)
        entry = self._start(fiber, key)
        clock = clock_of(fiber)
        skip = False

        def observe(ex: Exit[A, E]) -> None:
            nonlocal skip
            entry.release = None  # no longer abandoned by its waiters leaving
            if _interrupted(ex):
                self._remove(key, entry)
                return
            ttl = entry.time_to_live
            if ttl == 0:
                skip = True
                self._remove(key, entry)
            else:
                entry.expires_at = deadline(clock, ttl)

        entry.fiber.add_observer_unsafe(observe)
        # The lookup has run up to its first wait: a lookup that finished
        # interrupted or with a zero time to live is never cached.
        ex = entry.fiber.poll_unsafe()
        if not skip and (ex is None or not _interrupted(ex)):
            entries[key] = entry
        self._evict_overflow()
        return entry.await_from(fiber)

    def _refresh(self, fiber: Fiber[Any, Any], key: K) -> Effect[A, E]:
        entry = self._start(fiber, key)
        clock = clock_of(fiber)
        existing = self._find(fiber, key, touch=False) is not None
        if not existing:
            self._entries[key] = entry
            self._evict_overflow()

        def observe(ex: Exit[A, E]) -> None:
            entry.release = None
            if _interrupted(ex):
                self._remove(key, entry)
                return
            ttl = entry.time_to_live
            if ttl == 0:
                if existing:
                    self._discard(key)
                else:
                    self._remove(key, entry)
                return
            entry.expires_at = deadline(clock, ttl)
            if existing:
                self._entries[key] = entry
                self._evict_overflow()

        entry.fiber.add_observer_unsafe(observe)
        return entry.await_from(fiber)

    def _start(self, fiber: Fiber[Any, Any], key: K) -> _Entry[A, E]:
        """An entry whose lookup has run up to its first wait (Effect's
        immediate fork), on a root fiber with this cache's services
        overridden by the caller's. A raising ``lookup`` fails the caller
        with a defect, as in Effect.

        The time to live is decided inside the lookup fiber, so the fiber's
        observers call no user code: a raising ``time_to_live`` keeps
        nothing and becomes the lookup's defect, which ends every caller.
        (Effect calls it in an observer, where a raise hangs the callers.)"""
        lookup = self._lookup(key)
        lookup_fiber: Fiber[A, E] = new_root(
            fiber._run_scheduler, self._context.merge(fiber._context)
        )
        entry = _Entry[A, E](lookup_fiber)
        entry.release = lambda: self._remove(key, entry)

        def decide_time_to_live(ex: Exit[A, E]) -> Effect[None]:
            if not _interrupted(ex):
                entry.time_to_live = self._time_to_live(ex, key)
            return _VOID

        start_root(lookup_fiber, lookup.on_exit(decide_time_to_live))
        return entry

    def _find(self, fiber: Fiber[Any, Any], key: K, *, touch: bool) -> _Entry[A, E] | None:
        """The unexpired entry for ``key`` (an expired one is dropped);
        ``touch`` makes it the most recently used."""
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
        for key, entry in list(self._entries.items()):
            if is_expired(entry.expires_at, now):
                del self._entries[key]
            else:
                live.append((key, entry))
        return live

    def _discard(self, key: K) -> None:
        self._entries.pop(key, None)

    def _remove(self, key: K, entry: _Entry[A, E]) -> None:
        if self._entries.get(key) is entry:
            del self._entries[key]

    def _evict_overflow(self) -> None:
        for key in overflow(self._entries, self._capacity):
            del self._entries[key]


class _Entry[A, E]:
    """A lookup and the callers waiting on it."""

    __slots__ = ("awaiters", "expires_at", "fiber", "release", "time_to_live")

    def __init__(self, fiber: Fiber[A, E]) -> None:
        self.fiber = fiber
        self.awaiters = 0
        self.expires_at: int | None = None
        # Set as the lookup ends; stays zero if ``time_to_live`` raised.
        self.time_to_live: Seconds = ZERO
        # Drops the entry from the cache when its waiters abandon it.
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
        self.awaiters += 1
        fiber._push(_Leave(self))
        return self.fiber.join()

    def leave(self) -> Effect[None] | None:
        """A caller stopped waiting. Gives the effect that abandons the
        lookup if that caller was the last one."""
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
