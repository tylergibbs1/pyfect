"""``Semaphore``: limit how many fibers do something at once."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from pyfect._core import Effect, Restore, _Succeed, _Suspend, _Sync, uninterruptible_mask
from pyfect._waiters import WaitList


class Semaphore:
    __slots__ = ("_available", "_waiters")

    def __init__(self, permits: int) -> None:
        if permits < 0:
            raise ValueError(f"permits must be >= 0, got {permits}")
        self._available = permits
        self._waiters = WaitList()

    @classmethod
    def make(cls, permits: int) -> Effect[Semaphore]:
        return _Sync(lambda: cls(permits))

    @property
    def available(self) -> Effect[int]:
        return _Sync(lambda: self._available)

    def take(self, n: int = 1) -> Effect[int]:
        """Wait for ``n`` permits and take them; succeeds with ``n``. Prefer
        ``with_permits``, which also gives them back."""

        def attempt() -> Effect[int]:
            if self._available >= n:
                self._available -= n
                return _Succeed(n)
            return self._waiters.wait().and_then(_Suspend(attempt))

        return _Suspend(attempt)

    def release(self, n: int = 1) -> Effect[int]:
        """Give back ``n`` permits; succeeds with the number now free."""

        def run() -> int:
            self._available += n
            self._waiters.notify_all()
            return self._available

        return _Sync(run)

    def with_permits[A, E, R](self, eff: Effect[A, E, R], n: int = 1) -> Effect[A, E, R]:
        """Run ``eff`` holding ``n`` permits, releasing them however it ends.
        Only the wait is interruptible: once taken, the permits are guarded
        in the same step."""

        def body(restore: Restore) -> Effect[A, E, R]:
            def acquire() -> Effect[A, E, R]:
                if self._available < n:
                    return restore(self._waiters.wait()).and_then(_Suspend(acquire))
                self._available -= n
                return restore(eff).ensuring(self.release(n))

            return _Suspend(acquire)

        return uninterruptible_mask(body)
