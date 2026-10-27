"""``Semaphore``: limit how many fibers do something at once."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from pyfect._core import Effect, Restore, _Succeed, _Suspend, _Sync, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect._waiters import WaitList
from pyfect.option import Option, Some


def _check_permits(permits: int) -> int:
    if permits < 0:
        raise ValueError(f"permits must be >= 0, got {permits}")
    return permits


class Semaphore:
    __slots__ = ("_permits", "_taken", "_waiters")

    def __init__(self, permits: int) -> None:
        self._permits = _check_permits(permits)
        self._taken = 0
        self._waiters = WaitList()

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

        def attempt() -> Effect[int]:
            if self._free >= n:
                self._taken += n
                return _Succeed(n)
            return self._waiters.wait(lambda: self._free >= n).and_then(_Suspend(attempt))

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
            if self._free > 0:
                self._waiters.notify_all()

        return _Sync(run)

    def with_permits[A, E, R](self, eff: Effect[A, E, R], n: int = 1) -> Effect[A, E, R]:
        """Run ``eff`` holding ``n`` permits, releasing them however it ends.
        Only the wait is interruptible: once taken, the permits are guarded
        in the same step."""
        require_effect(eff, "eff")

        def body(restore: Restore) -> Effect[A, E, R]:
            def acquire() -> Effect[A, E, R]:
                if self._free < n:
                    wait = self._waiters.wait(lambda: self._free >= n)
                    return restore(wait).and_then(_Suspend(acquire))
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
        if self._free > 0:
            self._waiters.notify_all()
        return self._free
