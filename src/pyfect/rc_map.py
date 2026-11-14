"""``RcMap[K, A, E]``: scoped resources shared by key.

``get(key)`` runs ``lookup(key)`` the first time a key is asked for,
shares the resource (or the lookup in progress) with every other caller for
that key, and holds a reference until the caller's ``Scope`` closes. When
the last reference to a key goes, its resource is released at once, or
kept for ``idle_time_to_live`` (``touch`` restarts that wait). ``invalidate``
drops a key so the next ``get`` looks it up afresh.

``capacity`` bounds the number of keys, idle ones included; nothing is
evicted, so a new key fails with ``ExceededCapacityError`` while the map is
full. Closing the scope that made the map releases every entry.

Runs on other threads share a map. Its entries and their reference counts
change holding its lock, and nothing runs under it: lookups start, timers
start and scopes close once it is let go. Idle timers run on the run that
made the map, which lives as long as the map's scope; the run of the caller
that let go last may end first.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from typing import Any, Final, Never, overload

from pyfect._concurrency import for_each
from pyfect._core import (
    Effect,
    Restore,
    _call_user,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._fiber import Fiber
from pyfect._root import new_root, start_root
from pyfect._unsubscripted import Unsubscripted
from pyfect.clock import Clock, ClockService
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import (
    Duration,
    from_input_unsafe,
    from_nanos_or_infinite,
    nanos_or_infinite,
    zero,
)
from pyfect.duration import (
    Input as DurationInput,
)
from pyfect.effect import fail, from_exit, interrupt
from pyfect.errors import ExceededCapacityError
from pyfect.exit import Exit, Failure, Success, as_void_all
from pyfect.logger._log import log_unhandled
from pyfect.option import Option, Some
from pyfect.scheduler import Scheduler
from pyfect.scope import CloseableScope, Scope

_VOID: Final[Effect[None]] = _Succeed(None)
_DONE: Final[Exit[None, Never]] = Success(None)

type IdleTimeToLive[K] = DurationInput | Callable[[K], DurationInput]
"""A duration for every key, or one per key."""


class _Entry[A, E]:
    __slots__ = (
        "deferred",
        "expires_at",
        "fiber",
        "finalizer",
        "idle_time_to_live",
        "ref_count",
        "scope",
    )

    def __init__(self, idle_time_to_live: Duration) -> None:
        self.deferred: Deferred[A, E] = Deferred()
        self.scope = CloseableScope()
        self.idle_time_to_live = idle_time_to_live
        self.finalizer: Effect[None] = _VOID  # set once the entry's key is known
        self.fiber: Fiber[None, Never] | None = None  # the idle timer
        self.expires_at: int | float = 0  # monotonic nanoseconds
        self.ref_count = 1


class _Releasing:
    """A key whose last reference went and whose resource is being released.
    In Effect a release that does not suspend ends before any other fiber
    runs, so a get from another run waits for it; one from the run releasing
    it looks the key up afresh, as in Effect."""

    __slots__ = ("done", "run")

    def __init__(self, run: Scheduler) -> None:
        self.run = run
        self.done: Deferred[None] = Deferred()


class RcMap[K: Hashable = Unsubscripted, A = Unsubscripted, E = Never]:
    """Make one with ``RcMap.make(lookup)`` inside a scope."""

    __slots__ = (
        "_capacity",
        "_context",
        "_entries",
        "_idle_time_to_live",
        "_lock",
        "_lookup",
        "_owner",
        "_releasing",
        "_scope",
    )

    def __init__(
        self,
        lookup: Callable[[K], Effect[A, E, Any]],
        context: Context,
        scope: CloseableScope,
        idle_time_to_live: Callable[[K], Duration],
        capacity: int | None,
        *,
        owner: Scheduler,
    ) -> None:
        self._lookup = lookup
        self._context = context
        self._scope = scope
        self._idle_time_to_live = idle_time_to_live
        self._capacity = capacity
        self._entries: dict[K, _Entry[A, E]] | None = {}  # None once closed
        self._releasing: dict[K, _Releasing] = {}
        # The run that made the map: idle timers run on it.
        self._owner = owner
        self._lock = threading.Lock()

    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, R = Never](
        cls: type[RcMap[Unsubscripted, Unsubscripted, Any]],
        lookup: Callable[[K2], Effect[T, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        capacity: None = None,
    ) -> Effect[RcMap[K2, T, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[K2: Hashable, T, X = Never, R = Never](
        cls: type[RcMap[Unsubscripted, Unsubscripted, Any]],
        lookup: Callable[[K2], Effect[T, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K2] | None = None,
        capacity: int,
    ) -> Effect[RcMap[K2, T, X | ExceededCapacityError], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[R = Never](
        cls,
        lookup: Callable[[K], Effect[A, E, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        capacity: None = None,
    ) -> Effect[RcMap[K, A, E], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[X = Never, R = Never](
        cls,
        lookup: Callable[[K], Effect[A, X, R]],
        *,
        idle_time_to_live: IdleTimeToLive[K] | None = None,
        capacity: int,
    ) -> Effect[RcMap[K, A, X | ExceededCapacityError], Never, Scope | R]: ...
    @classmethod
    def make(
        cls,
        lookup: Callable[[Any], Effect[Any, Any, Any]],
        *,
        idle_time_to_live: IdleTimeToLive[Any] | None = None,
        capacity: int | None = None,
    ) -> Effect[RcMap[Any, Any, Any], Never, Any]:
        """A map that looks keys up with ``lookup`` (with the services in
        scope now and of the caller, and a scope per key), released when
        the current scope closes. ``idle_time_to_live`` defaults to 0:
        release as soon as the last reference goes."""
        ttl = _idle_time_to_live(idle_time_to_live)
        bound = None if capacity is None else max(capacity, 0)

        def body(fiber: Fiber[Any, Any]) -> Effect[RcMap[Any, Any, Any]]:
            context = fiber._context
            scope = context.get_unsafe(Scope)
            rc_map = RcMap(lookup, context, scope, ttl, bound, owner=fiber._run_scheduler)
            return scope.add_finalizer(lambda _: rc_map._close()).as_(rc_map)

        return _WithFiber(body)

    @property
    def capacity(self) -> int | None:
        """The most keys the map holds, or ``None`` for no limit."""
        return self._capacity

    def get(self, key: K) -> Effect[A, E, Scope]:
        """The resource for ``key``, looked up if needed and held until the
        current scope closes. Interrupted once the map is closed."""

        def body(restore: Restore) -> Effect[A, E, Scope]:
            return _WithFiber(lambda parent: self._get(parent, key, restore))

        return uninterruptible_mask(body)

    def get_option(self, key: K) -> Effect[Option[A], E, Scope]:
        """``get`` for a key the map already holds (``Some``), without a
        lookup: ``None`` for a missing key or a closed map. An entry still
        being looked up is waited for; a failed one fails the same way."""

        def body(restore: Restore) -> Effect[Option[A], E, Scope]:
            def run(fiber: Fiber[Any, Any]) -> Effect[Option[A], E]:
                with self._lock:
                    entry = None if self._entries is None else self._entries.get(key)
                    if entry is None:
                        return _Succeed(None)
                    entry.ref_count += 1
                return self._retain(fiber, entry, restore(entry.deferred.wait().map(Some)))

            return _WithFiber(run)

        return uninterruptible_mask(body)

    def keys(self) -> Effect[list[K]]:
        """The keys held now. Interrupted once the map is closed."""

        def body() -> Effect[list[K]]:
            with self._lock:
                entries = self._entries
                return interrupt() if entries is None else _Succeed(list(entries))

        return _Suspend(body)

    def has(self, key: K) -> Effect[bool]:
        """Whether the map holds ``key``; ``False`` once it is closed."""

        def body() -> bool:
            with self._lock:
                return self._entries is not None and key in self._entries

        return _Sync(body)

    def invalidate(self, key: K) -> Effect[None]:
        """Drop ``key``, so the next ``get`` looks it up afresh. Its resource
        is released now if nobody holds it, else when the last holder lets
        go."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            with self._lock:
                entries = self._entries
                entry = None if entries is None else entries.get(key)
                if entries is None or entry is None:
                    return _VOID
                if entry.ref_count > 0:
                    del entries[key]
                    return _VOID
                return self._released(entries, key, entry, fiber._run_scheduler, _close_entry)

        return _WithFiber(body).uninterruptible()

    def touch(self, key: K) -> Effect[None]:
        """Restart ``key``'s idle time to live."""

        def body(fiber: Fiber[Any, Any]) -> Effect[None]:
            self.touch_unsafe(key, fiber)
            return _VOID

        return _WithFiber(body)

    def touch_unsafe(self, key: K, fiber: Fiber[Any, Any]) -> None:
        """``touch`` in ``fiber``'s step, on the clock of its context."""
        clock: ClockService = fiber._context.lookup(Clock)[1]
        with self._lock:
            entry = None if self._entries is None else self._entries.get(key)
            if entry is not None and not entry.idle_time_to_live.is_zero():
                entry.expires_at = clock.monotonic_nanos_unsafe() + nanos_or_infinite(
                    entry.idle_time_to_live
                )

    def __repr__(self) -> str:
        entries = self._entries
        if entries is None:
            return "RcMap(closed)"
        return f"RcMap(size={len(entries)})"

    def _get(self, parent: Fiber[Any, Any], key: K, restore: Restore) -> Effect[A, E]:
        # Read outside the lock: it is the user's function.
        new = _Entry[A, E](self._idle_time_to_live(key))
        new.finalizer = self._release(key, new)
        with self._lock:
            entries = self._entries
            if entries is None:
                return interrupt()
            entry = entries.get(key)
            releasing = self._releasing.get(key)
            if (
                entry is None
                and releasing is not None
                and releasing.run is not parent._run_scheduler
            ):
                again = _WithFiber(lambda current: self._get(current, key, restore))
                return restore(releasing.done.wait()).and_then(again)
            if entry is not None:
                entry.ref_count += 1
            elif self._capacity is not None and len(entries) >= self._capacity:
                # ``make`` puts the error in E whenever there is a capacity.
                full: Any = ExceededCapacityError(
                    f"RcMap attempted to exceed capacity of {self._capacity}"
                )
                return fail(full)
            else:
                entry = entries[key] = new
        if entry is new:
            self._start_lookup(parent, key, entry)
        return self._retain(parent, entry, restore(entry.deferred.wait()))

    def _retain[B](
        self, fiber: Fiber[Any, Any], entry: _Entry[A, E], then: Effect[B, E]
    ) -> Effect[B, E]:
        """Hold ``entry``, counted already, until the caller's scope closes,
        then run ``then``."""
        scope = fiber._context.get_unsafe(Scope)
        return scope.add_finalizer(lambda _: entry.finalizer).and_then(then)

    def _start_lookup(self, parent: Fiber[Any, Any], key: K, entry: _Entry[A, E]) -> None:
        context = self._context.merge(parent._context).add(Scope, entry.scope)
        fiber: Fiber[A, E] = new_root(parent._run_scheduler, context)

        def observe(ex: Exit[A, E]) -> None:
            # An interrupted lookup was abandoned: drop it, so the next get
            # looks the key up afresh.
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                self._remove_interrupted(fiber, key, entry)
            entry.deferred.done_unsafe(ex)

        start_root(fiber, _call_user(self._lookup, key))
        fiber.run_in(entry.scope)
        fiber.add_observer_unsafe(observe)

    def _remove_interrupted(self, lookup: Fiber[Any, Any], key: K, entry: _Entry[A, E]) -> None:
        with self._lock:
            entries = self._entries
            if entries is None or entries.get(key) is not entry:
                return
            del entries[key]
            if entry.ref_count > 0:  # the borrowers close it as they let go
                return
        closer: Fiber[None, Never] = new_root(self._owner, lookup._context)
        start_root(closer, _report_unhandled(_close_entry(entry)))
        closer.run_in(self._scope)

    def _release(self, key: K, entry: _Entry[A, E]) -> Effect[None]:
        return _WithFiber(lambda fiber: self._release_now(fiber, key, entry))

    def _release_now(self, fiber: Fiber[Any, Any], key: K, entry: _Entry[A, E]) -> Effect[None]:
        ttl = entry.idle_time_to_live
        clock: ClockService = fiber._context.lookup(Clock)[1]
        with self._lock:
            entry.ref_count -= 1
            if entry.ref_count > 0:
                return _VOID
            entries = self._entries
            if entries is None or entries.get(key) is not entry:
                return _close_entry(entry)
            if ttl.is_zero():
                return self._released(entries, key, entry, fiber._run_scheduler, _close_entry)
            if not ttl.is_finite():
                return _VOID
            entry.expires_at = clock.monotonic_nanos_unsafe() + ttl.to_nanos_unsafe()
            if entry.fiber is not None:
                return _VOID

        def expire_when_due(restore: Restore) -> Effect[None]:
            def check() -> Effect[None]:
                remaining = entry.expires_at - clock.monotonic_nanos_unsafe()
                if remaining > 0:
                    return restore(clock.sleep(from_nanos_or_infinite(remaining))).and_then(
                        _Suspend(check)
                    )
                with self._lock:
                    current = self._entries
                    if current is None or entry.ref_count > 0 or current.get(key) is not entry:
                        return _VOID
                    return self._released(current, key, entry, self._owner, _close_idle)

            return _Suspend(check)

        finished = [False]

        def forget() -> None:
            with self._lock:
                finished[0] = True
                if entry.fiber is timer:
                    entry.fiber = None

        # Started before it is published: closing the map interrupts the
        # published timer, which must have started by then.
        timer: Fiber[None, Never] = new_root(self._owner, fiber._context)
        start_root(timer, uninterruptible_mask(expire_when_due).ensuring(_Sync(forget)))
        timer.run_in(self._scope)
        with self._lock:
            # Done already, another release started one meanwhile, or the
            # map closed.
            spare = finished[0] or entry.fiber is not None or self._entries is None
            if not spare:
                entry.fiber = timer
        if spare:
            timer.interrupt_as_unsafe(None)
        return _VOID

    def _released(
        self,
        entries: dict[K, _Entry[A, E]],
        key: K,
        entry: _Entry[A, E],
        run: Scheduler,
        close: Callable[[_Entry[A, E]], Effect[None]],
    ) -> Effect[None]:
        """Drop ``key``, which nobody holds, and release its resource with
        ``close`` from ``run``. Call holding the lock."""
        del entries[key]
        releasing = self._releasing[key] = _Releasing(run)

        def finish() -> None:
            with self._lock:
                if self._releasing.get(key) is releasing:
                    del self._releasing[key]
            releasing.done.done_unsafe(_DONE)

        return close(entry).ensuring(_Sync(finish))

    def _close(self) -> Effect[None]:
        with self._lock:
            entries = self._entries
            if entries is None:
                return _VOID
            self._entries = None

        def finish(exits: list[Exit[None, Never]]) -> Effect[None]:
            entries.clear()
            return from_exit(as_void_all(exits))

        closing = for_each(list(entries.values()), lambda entry: _close_entry(entry).exit())
        return closing.flat_map(finish)


def _report_unhandled(closing: Effect[None]) -> Effect[None]:
    """A release nobody waits for: its failure is logged at the
    ``UnhandledLogLevel``, as Effect 4.1.2 does."""
    return closing.catch_cause(
        lambda cause: log_unhandled("Unhandled error in RcMap finalizer", cause)
    )


def _close_idle(entry: _Entry[Any, Any]) -> Effect[None]:
    return _report_unhandled(entry.scope.close(_DONE))


def _close_entry(entry: _Entry[Any, Any]) -> Effect[None]:
    closing = entry.scope.close(_DONE)
    return closing if entry.fiber is None else entry.fiber.interrupt().and_then(closing)


def _idle_time_to_live[K](ttl: IdleTimeToLive[K] | None) -> Callable[[K], Duration]:
    if callable(ttl):
        pick = ttl
        return lambda key: from_input_unsafe(pick(key))
    fixed = zero if ttl is None else from_input_unsafe(ttl)
    return lambda _: fixed


__all__ = ["IdleTimeToLive", "RcMap"]
