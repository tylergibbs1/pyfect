"""``SynchronizedRef[A]``: a ``Ref`` whose updates can run effects.

Updates take turns: each holds the ref's one-permit lock from reading the
value to storing the new one, so ``update_effect(f)`` never loses a
concurrent update while ``f``'s effect runs. If the effect fails or is
interrupted, the value is unchanged. ``get`` never waits. An update
started from inside another update's effect waits forever, as in Effect.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from pyfect._core import Effect, _Sync
from pyfect._locked_ref import LockedRef


class SynchronizedRef[A](LockedRef[A]):
    """``SynchronizedRef(value)`` is Effect's ``makeUnsafe``."""

    __slots__ = ()

    @staticmethod
    def make[T](value: T) -> Effect[SynchronizedRef[T]]:
        return _Sync(lambda: SynchronizedRef(value))


__all__ = ["SynchronizedRef"]
