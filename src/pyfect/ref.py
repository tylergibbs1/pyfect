"""``Ref[A]``: a mutable cell that fibers can share.

Every operation is atomic, also when runs on several threads share the
ref: a read-modify-write holds the ref's lock while it reads, calls ``f``
and writes, so ``f`` runs once and sees no other write in between. ``f``
should be pure, as in Effect. The ``*_some`` operations take a function
returning an ``Option``: ``None`` leaves the value as it is.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import overload

from pyfect._core import Effect, _Sync
from pyfect._unsubscripted import Unsubscripted
from pyfect.option import Option


class Ref[A = Unsubscripted]:
    """``Ref(value)`` is Effect's ``makeUnsafe``; ``Ref.make`` is the effect."""

    __slots__ = ("_lock", "_value")

    def __init__(self, value: A) -> None:
        self._value = value
        # Reentrant: an ``f`` that runs an effect on this ref (``run_sync``)
        # sees what JavaScript would, its write then replaced by ``f``'s result.
        self._lock = threading.RLock()

    @overload
    @classmethod
    def make[T](cls: type[Ref[Unsubscripted]], value: T) -> Effect[Ref[T]]: ...
    @overload
    @classmethod
    def make(cls, value: A) -> Effect[Ref[A]]: ...
    @classmethod
    def make[T](cls, value: T) -> Effect[Ref[T]]:
        return _Sync(lambda: Ref(value))

    def get_unsafe(self) -> A:
        return self._value

    def get(self) -> Effect[A]:
        return _Sync(lambda: self._value)

    def set(self, value: A) -> Effect[None]:
        def run() -> None:
            with self._lock:
                self._value = value

        return _Sync(run)

    def set_and_get(self, value: A) -> Effect[A]:
        def run() -> A:
            with self._lock:
                self._value = value
                return value

        return _Sync(run)

    def get_and_set(self, value: A) -> Effect[A]:
        def run() -> A:
            with self._lock:
                old, self._value = self._value, value
                return old

        return _Sync(run)

    def update(self, f: Callable[[A], A]) -> Effect[None]:
        def run() -> None:
            with self._lock:
                self._value = f(self._value)

        return _Sync(run)

    def update_and_get(self, f: Callable[[A], A]) -> Effect[A]:
        def run() -> A:
            with self._lock:
                self._value = f(self._value)
                return self._value

        return _Sync(run)

    def get_and_update(self, f: Callable[[A], A]) -> Effect[A]:
        def run() -> A:
            with self._lock:
                old = self._value
                self._value = f(old)
                return old

        return _Sync(run)

    def update_some(self, f: Callable[[A], Option[A]]) -> Effect[None]:
        def run() -> None:
            with self._lock:
                if (new := f(self._value)) is not None:
                    self._value = new.value

        return _Sync(run)

    def update_some_and_get(self, f: Callable[[A], Option[A]]) -> Effect[A]:
        def run() -> A:
            with self._lock:
                if (new := f(self._value)) is not None:
                    self._value = new.value
                return self._value

        return _Sync(run)

    def get_and_update_some(self, f: Callable[[A], Option[A]]) -> Effect[A]:
        def run() -> A:
            with self._lock:
                old = self._value
                if (new := f(old)) is not None:
                    self._value = new.value
                return old

        return _Sync(run)

    def modify[B](self, f: Callable[[A], tuple[B, A]]) -> Effect[B]:
        """Compute a result and a new value from the current one, atomically."""

        def run() -> B:
            with self._lock:
                result, self._value = f(self._value)
                return result

        return _Sync(run)

    def modify_some[B](self, f: Callable[[A], tuple[B, Option[A]]]) -> Effect[B]:
        """``modify`` whose new value is optional: ``None`` keeps the current one."""

        def run() -> B:
            with self._lock:
                result, new = f(self._value)
                if new is not None:
                    self._value = new.value
                return result

        return _Sync(run)


__all__ = ["Ref"]
