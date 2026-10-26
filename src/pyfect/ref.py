"""``Ref[A]``: a mutable cell that fibers can share.

Every operation runs in a single fiber step, and a scheduler runs one step
at a time, so each operation is atomic.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable

from pyfect._core import Effect, _Sync


class Ref[A]:
    __slots__ = ("_value",)

    def __init__(self, value: A) -> None:
        self._value = value

    @staticmethod
    def make[T](value: T) -> Effect[Ref[T]]:
        return _Sync(lambda: Ref(value))

    def get(self) -> Effect[A]:
        return _Sync(lambda: self._value)

    def set(self, value: A) -> Effect[None]:
        def run() -> None:
            self._value = value

        return _Sync(run)

    def update(self, f: Callable[[A], A]) -> Effect[None]:
        def run() -> None:
            self._value = f(self._value)

        return _Sync(run)

    def update_and_get(self, f: Callable[[A], A]) -> Effect[A]:
        def run() -> A:
            self._value = f(self._value)
            return self._value

        return _Sync(run)

    def get_and_set(self, value: A) -> Effect[A]:
        def run() -> A:
            old, self._value = self._value, value
            return old

        return _Sync(run)

    def modify[B](self, f: Callable[[A], tuple[B, A]]) -> Effect[B]:
        """Compute a result and a new value from the current one, atomically."""

        def run() -> B:
            result, self._value = f(self._value)
            return result

        return _Sync(run)
