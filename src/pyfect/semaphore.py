"""``Semaphore``: limit how many fibers do something at once."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import (
    Effect,
    Restore,
    _Callback,
    _Succeed,
    _Suspend,
    _Sync,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._effect_base import Frame, Step
from pyfect.option import Option, Some

if TYPE_CHECKING:
    from pyfect._fiber import Fiber


def _check_permits(permits: int) -> int:
    if permits < 0:
        raise ValueError(f"permits must be >= 0, got {permits}")
    return permits


class _Waiter:
    """A fiber parked for ``n`` permits; ``woken`` once a release counted
    permits for it."""

    __slots__ = ("n", "resume", "woken")

    def __init__(self, n: int) -> None:
        self.n = n
        self.woken = False
        self.resume: Callable[[Effect[None]], None] = _no_resume


def _no_resume(_: Effect[None]) -> None:
    return None


def _as_is[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return effect


_CHECKPOINT: Effect[None] = _Succeed(None)


class _Turn(Frame):
    """Settles a wait for permits. Once woken, it stays on the stack for one
    more step (where an interrupt can land, if the caller is interruptible
    there), then retries; a waiter interrupted after its wake-up passes the
    wake-up on, so the permits counted for it are never stranded."""

    __slots__ = ("checked", "semaphore", "then", "waiter")

    def __init__(
        self, semaphore: Semaphore, waiter: _Waiter, then: Callable[[], Effect[Any, Any, Any]]
    ) -> None:
        self.semaphore = semaphore
        self.waiter = waiter
        self.then = then
        self.checked = False

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        if not self.checked:
            self.checked = True
            fiber._push(self)
            return _CHECKPOINT
        self.semaphore._settle(self.waiter)
        return self.then()

    def _on_failure(self, cause: Any, fiber: Fiber[Any, Any]) -> Step:
        if self.waiter.woken:
            self.semaphore._settle(self.waiter)
            self.semaphore._wake()
        return super()._on_failure(cause, fiber)


class _WaitTurn(Effect[Any, Any, Any]):
    """Park until a release wakes this waiter (``restore`` makes only the
    park interruptible), then retry under ``_Turn``."""

    __slots__ = ("restore", "semaphore", "then", "waiter")

    def __init__(
        self,
        semaphore: Semaphore,
        n: int,
        restore: Restore,
        then: Callable[[], Effect[Any, Any, Any]],
    ) -> None:
        self.semaphore = semaphore
        self.waiter = _Waiter(n)
        self.restore = restore
        self.then = then

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        fiber._push(_Turn(self.semaphore, self.waiter, self.then))
        return self.restore(_Callback(self.semaphore._park(self.waiter)))


class Semaphore:
    """Permits shared by fibers. A release wakes only the waiters its free
    permits can serve (a woken waiter retries; Effect resumes the first one
    at once, so the rest stay parked), so contention costs O(1) per
    release rather than a wake-up of every waiter."""

    __slots__ = ("_permits", "_taken", "_waiters", "_waking")

    def __init__(self, permits: int) -> None:
        self._permits = _check_permits(permits)
        self._taken = 0
        self._waiters: deque[_Waiter] = deque()
        # Permits counted for woken waiters that have not retried yet.
        self._waking = 0

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

        # Interruptible throughout, as Effect's ``take``: a waiter
        # interrupted after its wake-up passes it on (``_Turn``).
        def attempt() -> Effect[int]:
            if self._free >= n:
                self._taken += n
                return _Succeed(n)
            return _WaitTurn(self, n, _as_is, attempt)

        return _Suspend(attempt)

    def take_if_available(self, n: int = 1) -> Effect[bool]:
        """Take ``n`` permits if they are free now; never waits."""

        def attempt() -> bool:
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
        return _Sync(lambda: self._release(self._taken))

    def resize(self, permits: int) -> Effect[None]:
        """Change the total number of permits. Shrinking below what is taken
        makes takers wait until enough are given back."""
        _check_permits(permits)

        def run() -> None:
            self._permits = permits
            self._wake()

        return _Sync(run)

    def with_permits[A, E, R](self, eff: Effect[A, E, R], n: int = 1) -> Effect[A, E, R]:
        """Run ``eff`` holding ``n`` permits, releasing them however it ends.
        Only the wait is interruptible: once taken, the permits are guarded
        in the same step."""
        require_effect(eff, "eff")

        def body(restore: Restore) -> Effect[A, E, R]:
            def acquire() -> Effect[A, E, R]:
                if self._free < n:
                    return _WaitTurn(self, n, restore, acquire)
                self._taken += n
                return restore(eff).ensuring(self.release(n))

            return _Suspend(acquire)

        return uninterruptible_mask(body)

    def with_permits_if_available[A, E, R](
        self, eff: Effect[A, E, R], n: int = 1
    ) -> Effect[Option[A], E, R]:
        """Run ``eff`` holding ``n`` permits if they are free now (``Some``
        of its result); otherwise ``None`` without running it."""
        require_effect(eff, "eff")

        def body(restore: Restore) -> Effect[Option[A], E, R]:
            def acquire() -> Effect[Option[A], E, R]:
                if self._free < n:
                    return _Succeed(None)
                self._taken += n
                return restore(eff.map(Some)).ensuring(self.release(n))

            return _Suspend(acquire)

        return uninterruptible_mask(body)

    def _release(self, n: int) -> int:
        self._taken -= n
        self._wake()
        return self._free

    # --- waiting ---------------------------------------------------------------

    def _park(self, waiter: _Waiter) -> Callable[[Callable[[Effect[None]], None]], Effect[None]]:
        def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
            waiter.resume = resume
            self._waiters.append(waiter)
            # A release can land between the caller's check and this park.
            self._wake()
            return _Sync(lambda: self._discard(waiter))

        return register

    def _wake(self) -> None:
        """Wake, in order, the waiters the free permits not yet counted for
        a woken waiter can serve."""
        spare = self._free - self._waking
        waiters = self._waiters
        woken: list[_Waiter] = []
        too_large: list[_Waiter] = []
        while spare > 0 and waiters:
            waiter = waiters.popleft()
            if waiter.n <= spare:
                spare -= waiter.n
                woken.append(waiter)
            else:
                too_large.append(waiter)
        waiters.extendleft(reversed(too_large))
        for waiter in woken:
            waiter.woken = True
            self._waking += waiter.n
        for waiter in woken:
            waiter.resume(_Succeed(None))

    def _settle(self, waiter: _Waiter) -> None:
        """A woken waiter retries (or gives up): its permits are no longer
        counted for it."""
        waiter.woken = False
        self._waking -= waiter.n

    def _discard(self, waiter: _Waiter) -> None:
        with contextlib.suppress(ValueError):
            self._waiters.remove(waiter)
