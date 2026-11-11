"""What scenarios share: slots handing values to threads and checks, simulated
threads that interrupt or act on a primitive from outside any fiber, and
counted resources."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import scope

from ._harness import Guard, Problems, ThreadBody, World

type AnyFiber = fx.Fiber[Any, Any]


class Slot[T]:
    """A value a fiber hands to a simulated thread (or to a check)."""

    def __init__(self) -> None:
        self.value: T | None = None

    def set(self, value: T) -> T:
        self.value = value
        return value

    def get(self) -> T:
        assert self.value is not None, "read before it was set"
        return self.value

    def is_set(self) -> bool:
        return self.value is not None


def interrupt_from_thread(w: World, name: str, target: Slot[AnyFiber]) -> None:
    """A simulated thread that interrupts ``target`` once it exists."""

    def body() -> ThreadBody:
        yield target.is_set
        target.get().interrupt_as_unsafe(None)

    w.thread(name, body)


def from_thread(w: World, name: str, act: Callable[[], object], *, when: Guard) -> None:
    """A simulated thread that runs ``act`` (an ``*_unsafe`` call, a resume)
    once ``when`` holds, outside any fiber: what it wakes is resumed through
    the scheduler, as from another real thread."""

    def body() -> ThreadBody:
        yield when
        act()

    w.thread(name, body)


def resource(w: World, name: str) -> fx.Effect[None, Never, scope.Scope]:
    """Counts ``acquire <name>`` and, once released, ``release <name>``."""
    return scope.acquire_release(w.bump(f"acquire {name}"), lambda _, __: w.bump(f"release {name}"))


def balanced(w: World, *names: str) -> Callable[[], Problems]:
    """Each named resource was released exactly as often as acquired, at
    most once."""

    def check() -> Problems:
        problems: list[str] = []
        for name in names:
            acquired, released = w.counts[f"acquire {name}"], w.counts[f"release {name}"]
            if acquired > 1 or released != acquired:
                problems.append(f"{name}: acquired {acquired}, released {released}")
        return problems

    return check


def released_once(w: World, prefix: str = "") -> Callable[[], Problems]:
    """Every counted ``acquire <name>`` (names starting with ``prefix``) was
    released exactly once; for resources made in numbers the run decides."""

    def check() -> Problems:
        problems: list[str] = []
        for key, acquired in w.counts.items():
            if not key.startswith(f"acquire {prefix}"):
                continue
            name = key.removeprefix("acquire ")
            released = w.counts[f"release {name}"]
            if acquired != 1 or released != 1:
                problems.append(f"{name}: acquired {acquired}, released {released}")
        return problems

    return check
