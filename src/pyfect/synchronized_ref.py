"""``SynchronizedRef[A]``: a ``Ref`` whose updates can run effects.

Updates take turns: each holds the ref's one-permit lock from reading the
value to storing the new one, so ``update_effect(f)`` never loses a
concurrent update while ``f``'s effect runs. If the effect fails or is
interrupted, the value is unchanged. ``get`` never waits. An update
started from inside another update's effect waits forever, as in Effect.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import overload

from pyfect._core import Effect, _Sync
from pyfect._locked_ref import LockedRef
from pyfect._unsubscripted import Unsubscripted


class SynchronizedRef[A = Unsubscripted](LockedRef[A]):
    """``SynchronizedRef(value)`` is Effect's ``makeUnsafe``."""

    __slots__ = ()

    @overload
    @classmethod
    def make[T](
        cls: type[SynchronizedRef[Unsubscripted]], value: T
    ) -> Effect[SynchronizedRef[T]]: ...
    @overload
    @classmethod
    def make(cls, value: A) -> Effect[SynchronizedRef[A]]: ...
    @classmethod
    def make[T](cls, value: T) -> Effect[SynchronizedRef[T]]:
        return _Sync(lambda: SynchronizedRef(value))


__all__ = ["SynchronizedRef"]
