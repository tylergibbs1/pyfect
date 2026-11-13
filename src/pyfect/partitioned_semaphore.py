"""``PartitionedSemaphore[K]``: one pool of permits shared fairly by keys.

Waiters are grouped by key and served round-robin across keys, so a key with
many waiters cannot starve the others. Each turn completes the waiter's
request before moving to the next key (Effect 4.1.2); a waiter that needs
more permits than are free keeps the turn and collects them as they come,
and is woken once it has them all. Only the wait is interruptible: an interrupt at any
point before the permits are guarded gives back what the waiter collected.

A request for more permits than the capacity never completes, as in Effect.

Runs on other threads share a semaphore: its counts and queues change
holding its lock, which is let go to wake a waiter (a woken fiber of the run
on this thread runs at once and may release again).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any

from pyfect._core import (
    WOKEN,
    Effect,
    Frame,
    Restore,
    Step,
    _Callback,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._round_robin import RoundRobin
from pyfect._waiters import Lock, unlocked
from pyfect.cause import Cause
from pyfect.effect import never
from pyfect.exit import Failure
from pyfect.option import Option, Some

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

_VOID: Effect[None] = _Succeed(None)


class _Waiter:
    __slots__ = ("lock", "missing", "resume")

    def __init__(self, missing: int, lock: Lock) -> None:
        self.missing = missing
        self.lock = lock
        self.resume: Callable[[Effect[None]], None] | None = None

    def register(self, resume: Callable[[Effect[None]], None]) -> None:
        with self.lock:
            handed = self.missing == 0  # handed its permits before it parked
            if not handed:
                self.resume = resume
        if handed:
            resume(_VOID)

    def wake(self) -> None:
        # Its permits are granted, but an interrupt reaching it before it
        # runs still wins, and ``_give_up`` gives them back.
        if self.resume is not None:
            self.resume(WOKEN)


class _GiveBackOnFailure(Frame):
    """Below a standalone ``take``: once it has taken its permits, give
    them back if the take still fails (an interrupt landing as it returns),
    as Effect's ``take`` does."""

    __slots__ = ("armed", "release")
    # Right below the claim: the permits reach the caller with no pause.
    claims = True

    def __init__(self, release: Callable[[], object]) -> None:
        self.release = release
        self.armed = False

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        if self.armed:
            self.release()
        return Failure(cause)


class PartitionedSemaphore[K: Hashable = Hashable]:
    __slots__ = (
        "_lock",
        "_partial",
        "_pending",
        "_releasing",
        "_total",
        "_waiters",
        "_waiting",
        "capacity",
    )

    def __init__(self, permits: int) -> None:
        self.capacity = max(0, permits)
        self._total = self.capacity  # free permits nobody is waiting for
        self._waiting = 0  # permits waiters still miss
        self._pending = 0  # released permits not yet handed out
        self._releasing = False
        # The waiter whose turn it is while it still misses permits.
        self._partial: tuple[Hashable, _Waiter] | None = None
        # Typed by Hashable, not K, so K only goes in (contravariant, as in Effect).
        self._waiters: RoundRobin[Hashable, _Waiter] = RoundRobin()
        self._lock = threading.Lock()

    @classmethod
    def make(cls, permits: int) -> Effect[PartitionedSemaphore[K]]:
        """``PartitionedSemaphore[str].make(4)``"""
        return _Sync(lambda: cls(permits))

    @property
    def available(self) -> Effect[int]:
        return _Sync(lambda: self._total)

    def take(self, key: K, n: int = 1) -> Effect[None]:
        """Wait in ``key``'s queue for ``n`` permits and take them. Prefer
        ``with_permits``, which also gives them back."""
        if n <= 0:
            return _VOID
        if self.capacity < n:
            return never

        def run(fiber: Fiber[Any, Any]) -> Effect[None]:
            guard = _GiveBackOnFailure(lambda: self._release(n))
            fiber._push(guard)

            def arm(_: None) -> None:
                guard.armed = True

            return uninterruptible_mask(lambda restore: self._acquire(key, n, restore).map(arm))

        return _WithFiber(run)

    def release(self, n: int = 1) -> Effect[int]:
        """Give back ``n`` permits; succeeds with the number now free."""
        return _Sync(lambda: self._release(n))

    def with_permits[A, E, R](self, key: K, eff: Effect[A, E, R], n: int = 1) -> Effect[A, E, R]:
        """Run ``eff`` holding ``n`` permits taken in ``key``'s queue,
        releasing them however it ends."""
        require_effect(eff, "eff")
        if n <= 0:
            return eff
        if self.capacity < n:
            return never
        release = self.release(n)
        return uninterruptible_mask(
            lambda restore: self._acquire(key, n, restore).and_then(restore(eff).ensuring(release))
        )

    def with_permits_if_available[A, E, R](
        self, eff: Effect[A, E, R], n: int = 1
    ) -> Effect[Option[A], E, R]:
        """Run ``eff`` holding ``n`` permits if they are free now (``Some``
        of its result); otherwise ``None`` without running it."""
        require_effect(eff, "eff")
        if n <= 0:
            return eff.map(Some)

        def body(restore: Restore) -> Effect[Option[A], E, R]:
            def run() -> Effect[Option[A], E, R]:
                with self._lock:
                    if self._total < n:
                        return _Succeed(None)
                    self._total -= n
                return restore(eff.map(Some)).ensuring(self.release(n))

            return _Suspend(run)

        return uninterruptible_mask(body)

    def _acquire(self, key: K, n: int, restore: Restore) -> Effect[None]:
        """Take ``n`` permits; runs uninterruptibly, with only the wait
        restored. Once it succeeds the caller holds them."""

        def run() -> Effect[None]:
            with self._lock:
                if self._total >= n:
                    self._total -= n
                    return _VOID
                waiter = _Waiter(n - self._total, self._lock)
                self._total = 0
                self._waiting += waiter.missing
                self._waiters.add(key, waiter)
            return restore(_Callback(waiter.register)).on_error(
                lambda _: _Sync(lambda: self._give_up(key, n, waiter))
            )

        return _Suspend(run)

    def _give_up(self, key: K, n: int, waiter: _Waiter) -> None:
        with self._lock:
            if self._partial is not None and self._partial[1] is waiter:
                self._partial = None
            self._waiters.remove(key, waiter)
            self._waiting -= waiter.missing
            self._release_locked(n - waiter.missing)

    def _release(self, n: int) -> int:
        with self._lock:
            return self._release_locked(n)

    def _release_locked(self, n: int) -> int:
        if n > 0:
            self._pending += n
        # A woken waiter can release again from inside this loop, and other
        # runs can while the lock is let go to wake it; the running loop
        # hands those permits out instead of recursing.
        if not self._releasing:
            self._releasing = True
            try:
                self._hand_out()
            finally:
                self._releasing = False
        # Free permits must be visible before a reentrant release returns.
        if self._waiting == 0:
            self._total = min(self.capacity, self._total + self._pending)
            self._pending = 0
        return self._total

    def _hand_out(self) -> None:
        while self._pending > 0 and self._waiting > 0:
            found = self._partial or self._waiters.next()
            if found is None:
                return
            key, waiter = found
            granted = min(waiter.missing, self._pending)
            waiter.missing -= granted
            self._waiting -= granted
            self._pending -= granted
            if waiter.missing == 0:
                self._partial = None
                self._waiters.remove(key, waiter)
                unlocked(self._lock, [waiter.wake])
            else:
                self._partial = found


__all__ = ["PartitionedSemaphore"]
