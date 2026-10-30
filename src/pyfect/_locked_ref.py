"""``LockedRef[A]``: the operations ``SynchronizedRef`` and
``SubscriptionRef`` share.

Every update holds a one-permit semaphore, so an effectful update (the
``*_effect`` methods) sees no other update between reading the value and
storing its result. ``get`` takes no permit: it reads the last stored
value. A subclass decides what storing does by overriding ``_store``.

Each operation is written as a transition from the current value to a
result and an optional new value (``None`` keeps the current one), which
``_locked`` / ``_locked_effect`` run under the semaphore.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Never

from pyfect._core import Effect, _Suspend, _Sync
from pyfect.option import Option, Some
from pyfect.semaphore import Semaphore

type _Transition[A, B] = tuple[B, Option[A]]


class LockedRef[A]:
    __slots__ = ("_lock", "_value")

    def __init__(self, value: A) -> None:
        self._value = value
        self._lock = Semaphore(1)

    def _store(self, value: A) -> None:
        self._value = value

    def _commit[B](self, transition: _Transition[A, B]) -> B:
        result, new = transition
        if new is not None:
            self._store(new.value)
        return result

    def _locked[B](self, f: Callable[[A], _Transition[A, B]]) -> Effect[B]:
        return self._lock.with_permits(_Sync(lambda: self._commit(f(self._value))))

    def _locked_effect[B, E, R](
        self, f: Callable[[A], Effect[_Transition[A, B], E, R]]
    ) -> Effect[B, E, R]:
        return self._lock.with_permits(_Suspend(lambda: f(self._value).map(self._commit)))

    # --- reading ----------------------------------------------------------

    def get_unsafe(self) -> A:
        return self._value

    def get(self) -> Effect[A]:
        return _Sync(lambda: self._value)

    # --- plain updates ----------------------------------------------------

    def set(self, value: A) -> Effect[None]:
        return self._locked(lambda _: (None, Some(value)))

    def set_and_get(self, value: A) -> Effect[A]:
        return self._locked(lambda _: (value, Some(value)))

    def get_and_set(self, value: A) -> Effect[A]:
        return self._locked(lambda old: (old, Some(value)))

    def update(self, f: Callable[[A], A]) -> Effect[None]:
        return self._locked(lambda old: (None, Some(f(old))))

    def update_and_get(self, f: Callable[[A], A]) -> Effect[A]:
        return self._locked(lambda old: _new_and_get(f(old)))

    def get_and_update(self, f: Callable[[A], A]) -> Effect[A]:
        return self._locked(lambda old: (old, Some(f(old))))

    def update_some(self, f: Callable[[A], Option[A]]) -> Effect[None]:
        return self._locked(lambda old: (None, f(old)))

    def update_some_and_get(self, f: Callable[[A], Option[A]]) -> Effect[A]:
        return self._locked(lambda old: _some_and_get(old, f(old)))

    def get_and_update_some(self, f: Callable[[A], Option[A]]) -> Effect[A]:
        return self._locked(lambda old: (old, f(old)))

    def modify[B](self, f: Callable[[A], tuple[B, A]]) -> Effect[B]:
        return self._locked(lambda old: _modified(f(old)))

    def modify_some[B](self, f: Callable[[A], tuple[B, Option[A]]]) -> Effect[B]:
        return self._locked(f)

    # --- effectful updates ------------------------------------------------

    def update_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[A, E, R]]
    ) -> Effect[None, E, R]:
        return self._locked_effect(lambda old: f(old).map(lambda new: (None, Some(new))))

    def update_and_get_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[A, E, R]]
    ) -> Effect[A, E, R]:
        return self._locked_effect(lambda old: f(old).map(_new_and_get))

    def get_and_update_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[A, E, R]]
    ) -> Effect[A, E, R]:
        return self._locked_effect(lambda old: f(old).map(lambda new: (old, Some(new))))

    def update_some_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[Option[A], E, R]]
    ) -> Effect[None, E, R]:
        return self._locked_effect(lambda old: f(old).map(lambda new: (None, new)))

    def update_some_and_get_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[Option[A], E, R]]
    ) -> Effect[A, E, R]:
        return self._locked_effect(lambda old: f(old).map(lambda new: _some_and_get(old, new)))

    def get_and_update_some_effect[E = Never, R = Never](
        self, f: Callable[[A], Effect[Option[A], E, R]]
    ) -> Effect[A, E, R]:
        return self._locked_effect(lambda old: f(old).map(lambda new: (old, new)))

    def modify_effect[B, E = Never, R = Never](
        self, f: Callable[[A], Effect[tuple[B, A], E, R]]
    ) -> Effect[B, E, R]:
        return self._locked_effect(lambda old: f(old).map(_modified))

    def modify_some_effect[B, E = Never, R = Never](
        self, f: Callable[[A], Effect[tuple[B, Option[A]], E, R]]
    ) -> Effect[B, E, R]:
        return self._locked_effect(f)


def _new_and_get[A](new: A) -> _Transition[A, A]:
    return new, Some(new)


def _some_and_get[A](old: A, new: Option[A]) -> _Transition[A, A]:
    return (old if new is None else new.value), new


def _modified[A, B](pair: tuple[B, A]) -> _Transition[A, B]:
    result, new = pair
    return result, Some(new)
