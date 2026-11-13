"""``Semaphore``: limit how many fibers do something at once."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never

from pyfect._core import (
    WOKEN,
    Effect,
    Restore,
    _Callback,
    _Succeed,
    _Suspend,
    _Sync,
    run_known,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._effect_base import Frame, Step
from pyfect._fiber import current_fiber
from pyfect._waiters import of_this_run, wake_soon
from pyfect.option import Option, Some
from pyfect.scope import CloseableScope, Scope

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


class _Waiter:
    """A queued request for ``n`` permits. It keeps its place until it takes
    them or leaves; a wake only resumes it to check again (Effect 4.1.2)."""

    __slots__ = ("fiber", "n", "resume")

    def __init__(self, n: int) -> None:
        self.n = n
        self.resume: Callable[[Effect[None]], None] | None = None
        # The parked fiber, once ``resume`` is set.
        self.fiber: Fiber[Any, Any] | None = None


class _Turn(Frame):
    """Below a parked request. When resumed, the request takes its permits
    if it is now the first queued request that fits, in this same step
    (``claims``), else it parks again; however the wait ends otherwise
    (an interrupt), the request leaves the queue."""

    __slots__ = ("restore", "semaphore", "then", "waiter")
    # The take happens here and its result goes straight on.
    claims = True

    def __init__(
        self,
        semaphore: Semaphore,
        waiter: _Waiter,
        restore: Restore,
        then: Callable[[], Effect[Any, Any, Any]],
    ) -> None:
        self.semaphore = semaphore
        self.waiter = waiter
        self.restore = restore
        self.then = then

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        semaphore = self.semaphore
        with semaphore._lock:
            if semaphore._first_available() is not self.waiter:
                fiber._push(self)
                return self.restore(_Callback(semaphore._park(self.waiter)))
            semaphore._taken += self.waiter.n
            woken = semaphore._leave(self.waiter)
        _resume_all(woken)
        return run_known(self.then())

    def _on_failure(self, cause: Any, fiber: Fiber[Any, Any]) -> Step:
        semaphore = self.semaphore
        with semaphore._lock:
            woken = semaphore._leave(self.waiter)
        _resume_all(woken)
        return super()._on_failure(cause, fiber)


class _Take(Effect[Any, Any, Any]):
    """Take ``n`` permits and continue with ``then()`` in the same step, or
    queue a request, install its ``_Turn`` and park, also in one step, so no
    interrupt can leave a request queued with nobody waiting on it.
    ``restore`` makes only the park interruptible."""

    __slots__ = ("n", "restore", "semaphore", "then")

    def __init__(
        self,
        semaphore: Semaphore,
        n: int,
        restore: Restore,
        then: Callable[[], Effect[Any, Any, Any]],
    ) -> None:
        self.semaphore = semaphore
        self.n = n
        self.restore = restore
        self.then = then

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        semaphore = self.semaphore
        n = self.n
        with semaphore._lock:
            if semaphore._free >= n and semaphore._first_available() is None:
                semaphore._taken += n
                waiter = None
            else:
                waiter = _Waiter(n)
                semaphore._waiters[waiter] = None
        if waiter is None:
            return run_known(self.then())
        fiber._push(_Turn(semaphore, waiter, self.restore, self.then))
        return self.restore(_Callback(semaphore._park(waiter)))


def _as_is[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return effect


_ABSENT = object()


class Semaphore:
    """Permits shared by fibers. Requests queue in arrival order: a request
    takes permits at once only when they are free and no queued request
    fits in them, so a holder that releases and takes again goes behind
    those already waiting. A queued request larger than the free permits
    keeps its place but is overtaken by smaller ones behind it. A release
    resumes, in one scheduled task, the queued requests its free permits
    cover; each then checks again."""

    __slots__ = ("_lock", "_permits", "_taken", "_waiters")

    def __init__(self, permits: int) -> None:
        self._permits = permits
        self._taken = 0
        # Runs on other threads share a semaphore: its counts and queue change
        # holding this; nobody is resumed while it is held.
        self._lock = threading.Lock()
        # A dict as an insertion-ordered set: a request leaves from anywhere.
        self._waiters: dict[_Waiter, None] = {}

    @classmethod
    def make(cls, permits: int) -> Effect[Semaphore]:
        return _Sync(lambda: cls(permits))

    @property
    def available(self) -> Effect[int]:
        return _Sync(lambda: self._free)

    @property
    def _free(self) -> int:
        return self._permits - self._taken

    def take(self, n: int = 1) -> Effect[int]:
        """Wait for ``n`` permits and take them; succeeds with ``n``. Prefer
        ``with_permits``, which also gives them back."""

        # Interruptible throughout, as Effect's ``take``.
        return self._take_then(n, _as_is, lambda: _Succeed(n))

    def take_scoped(self, n: int = 1) -> Effect[None, Never, Scope]:
        """Wait for ``n`` permits and hold them until the current scope
        closes. Only the wait is interruptible: once taken, the release is
        registered on the scope before anything can interrupt, so the
        permits always come back."""

        def body(restore: Restore) -> Effect[None, Never, Scope]:
            def with_scope(scope: CloseableScope) -> Effect[None]:
                return self._take_then(
                    n, restore, lambda: scope.add_finalizer(lambda _exit: self.release(n))
                )

            return Scope().flat_map(with_scope)

        return uninterruptible_mask(body)

    def take_if_available(self, n: int = 1) -> Effect[bool]:
        """Take ``n`` permits if they are free now; never waits."""

        def attempt() -> bool:
            with self._lock:
                if self._free < n:
                    return False
                self._taken += n
                return True

        return _Sync(attempt)

    def release(self, n: int = 1) -> Effect[int]:
        """Give back ``n`` permits; succeeds with the number now free."""
        return _Sync(lambda: self._release(n))

    def release_all(self) -> Effect[int]:
        """Give back every taken permit; succeeds with the number now free."""
        return _Sync(lambda: self._release(None))

    def resize(self, permits: int) -> Effect[None]:
        """Change the total number of permits. Shrinking below what is taken
        makes takers wait until enough are given back."""

        def run() -> None:
            with self._lock:
                self._permits = permits
                woken = self._wake_soon()
            _resume_all(woken)

        return _Sync(run)

    def with_permits[A, E, R](self, eff: Effect[A, E, R], n: int = 1) -> Effect[A, E, R]:
        """Run ``eff`` holding ``n`` permits, releasing them however it ends.
        Only the wait is interruptible: once taken, the permits are guarded
        in the same step."""
        require_effect(eff, "eff")

        def body(restore: Restore) -> Effect[A, E, R]:
            return self._take_then(n, restore, lambda: restore(eff).ensuring(self.release(n)))

        return uninterruptible_mask(body)

    def with_permits_if_available[A, E, R](
        self, eff: Effect[A, E, R], n: int = 1
    ) -> Effect[Option[A], E, R]:
        """Run ``eff`` holding ``n`` permits if they are free now (``Some``
        of its result); otherwise ``None`` without running it."""
        require_effect(eff, "eff")

        def body(restore: Restore) -> Effect[Option[A], E, R]:
            def acquire() -> Effect[Option[A], E, R]:
                with self._lock:
                    if self._free < n:
                        return _Succeed(None)
                    self._taken += n
                return restore(eff.map(Some)).ensuring(self.release(n))

            return _Suspend(acquire)

        return uninterruptible_mask(body)

    def _release(self, n: int | None) -> int:
        """Give back ``n`` permits, or all taken ones for ``None``."""
        with self._lock:
            self._taken -= self._taken if n is None else n
            woken = self._wake_soon()
            free = self._free
        _resume_all(woken)
        return free

    # --- waiting ---------------------------------------------------------------

    def _take_then[A, E, R](
        self, n: int, restore: Restore, then: Callable[[], Effect[A, E, R]]
    ) -> Effect[A, E, R]:
        """Take ``n`` permits, then continue with ``then()`` in the same
        step; only the wait is wrapped in ``restore``."""

        return _Take(self, n, restore, then)

    def _first_available(self) -> _Waiter | None:
        """The first queued request that fits in the free permits."""
        free = self._free
        return next((w for w in self._waiters if w.n <= free), None)

    def _park(self, waiter: _Waiter) -> Callable[[Callable[[Effect[None]], None]], None]:
        def register(resume: Callable[[Effect[None]], None]) -> None:
            # The fiber may have yielded since the last check, missing a wake.
            with self._lock:
                ready = self._first_available() is waiter
                if not ready:
                    waiter.resume = resume
                    waiter.fiber = current_fiber()
            if ready:
                resume(WOKEN)

        return register

    def _leave(self, waiter: _Waiter) -> list[_Resume]:
        """Take ``waiter`` out of the queue; the requests behind it may fit
        now. Call holding the lock; resume what it returns after."""
        waiter.resume = None
        if self._waiters.pop(waiter, _ABSENT) is not _ABSENT:
            return self._wake_soon()
        return []

    def _covered(self, pick: Callable[[_Waiter], bool]) -> list[_Resume]:
        """Take the resumes of the queued requests the free permits cover that
        ``pick`` picks. A request already woken still counts against them,
        since it keeps its place until it takes its permits."""
        remaining = self._free
        found: list[_Resume] = []
        for waiter in self._waiters:
            if waiter.n > remaining:
                continue
            remaining -= waiter.n
            resume = waiter.resume
            if resume is not None and pick(waiter):
                waiter.resume = None
                found.append(resume)
        return found

    def _wake_soon(self) -> list[_Resume]:
        """Resume, in one scheduled task, every queued request of this run
        the free permits cover. Call holding the lock. Returns those of other
        runs, to resume once it is let go: their resumes go through their own
        runs, and this run may end before its task runs."""
        if not self._waiters:
            return []
        if current_fiber() is None:
            # No fiber runs here to wait for, as ``wake_soon``: now.
            return self._covered(lambda _: True)

        def wake() -> None:
            with self._lock:
                woken = self._covered(lambda _: True)
            _resume_all(woken)

        wake_soon(wake)
        return self._covered(lambda waiter: not of_this_run(waiter.fiber))


type _Resume = Callable[[Effect[None]], None]


def _resume_all(resumes: list[_Resume]) -> None:
    for resume in resumes:
        resume(WOKEN)


__all__ = ["Semaphore"]
