"""Atoms derived from other atoms: ``transform`` and what is built on it
(``with_fallback``, ``debounce``, ``with_refresh``, refreshing on a
signal), plus ``set_idle_ttl``, ``family`` and ``initial_value``."""

from __future__ import annotations

import math
import traceback
import weakref
from collections.abc import Callable, Hashable
from typing import Any, cast, overload

from pyfect._equal import equal_key
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.reactivity import async_result
from pyfect.reactivity.async_result import AsyncResult, Initial
from pyfect.reactivity.atom._types import Atom, AtomContext, Writable, WriteContext, readable
from pyfect.reactivity.atom_registry import InitialValue


def set_idle_ttl[T: Atom[Any]](atom: T, duration: Duration) -> T:
    """``atom`` kept ``duration`` after it is last used (an infinite
    duration keeps it alive)."""
    seconds = to_seconds(duration)
    finite = not math.isinf(seconds)
    return atom._with(kept_alive=not finite, idle_ttl=seconds if finite else None)  # pyright: ignore[reportPrivateUsage]


def remove_ttl[T: Atom[Any]](atom: T) -> T:
    return set_idle_ttl(atom, 0)


def label_site(depth: int) -> str:
    """Where a label was set: the frame ``depth`` calls above this one."""
    frames = traceback.extract_stack(limit=depth + 1)
    frame = frames[0]
    return f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'


def _target(atom: Atom[Any]) -> Atom[Any]:
    while atom.initial_value_target is not None:
        atom = atom.initial_value_target
    return atom


def _refresh_of(atom: Atom[Any]) -> Callable[[Callable[[Atom[Any]], None]], None]:
    if atom.refresh is not None:
        return atom.refresh
    return lambda refresh: refresh(atom)


@overload
def transform[A, W, B](
    atom: Writable[A, W],
    f: Callable[[AtomContext, Any], B],
    *,
    initial_value_target: Atom[B] | None = None,
) -> Writable[B, W]: ...
@overload
def transform[B](
    atom: Atom[Any],
    f: Callable[[AtomContext, Any], B],
    *,
    initial_value_target: Atom[B] | None = None,
) -> Atom[B]: ...
def transform(
    atom: Atom[Any],
    f: Callable[[AtomContext, Any], Any],
    *,
    initial_value_target: Atom[Any] | None = None,
) -> Atom[Any]:
    """An atom read by ``f(get, atom)``; a writable ``atom``'s writes go
    to it, and refreshing the result refreshes ``atom``. Unused, it is
    removed at once (no idle TTL)."""

    def read(get: AtomContext) -> Any:
        return f(get, atom)

    derived: Atom[Any]
    if isinstance(atom, Writable):
        source = cast("Writable[Any, Any]", atom)

        def write(ctx: WriteContext[Any], value: Any) -> None:
            ctx.set(source, value)

        derived = Writable(read, write, _refresh_of(source))
    else:
        derived = readable(read, _refresh_of(atom))
    derived = remove_ttl(derived)
    if initial_value_target is not None:
        derived.initial_value_target = _target(initial_value_target)
    return derived


def with_fallback(atom: Atom[AsyncResult[Any, Any]], fallback: Atom[AsyncResult[Any, Any]]) -> Any:
    """While ``atom`` is ``Initial``, ``fallback``'s result, waiting."""

    def read(get: AtomContext) -> AsyncResult[Any, Any]:
        result = get(atom)
        if isinstance(result, Initial):
            return async_result.waiting(get(fallback))
        return result

    if isinstance(atom, Writable):
        source = cast("Writable[Any, Any]", atom)

        def write(ctx: WriteContext[Any], value: Any) -> None:
            ctx.set(source, value)

        return Writable(read, write, _refresh_of(source))
    return readable(read, _refresh_of(atom))


def debounce[A](atom: Atom[A], duration: Duration) -> Atom[A]:
    delay = Seconds(to_seconds(duration))

    def read(get: AtomContext, source: Atom[A]) -> A:
        cancel: list[Callable[[], None]] = []
        value = [get.once(source)]

        def fire() -> None:
            cancel.clear()
            get.set_self(value[0])

        def stop() -> None:
            if cancel:
                cancel.pop()()

        def on_change(next_value: A) -> None:
            value[0] = next_value
            stop()
            cancel.append(get.registry.scheduler.call_later(delay, fire))

        get.add_finalizer(stop)
        get.subscribe(source, on_change)
        return value[0]

    return transform(atom, read, initial_value_target=atom)


def with_refresh[A](atom: Atom[A], duration: Duration) -> Atom[A]:
    delay = Seconds(to_seconds(duration))

    def read(get: AtomContext, source: Atom[A]) -> A:
        cancel = get.registry.scheduler.call_later(delay, lambda: get.refresh(source))
        get.add_finalizer(cancel)
        return get(source)

    return transform(atom, read, initial_value_target=atom)


def make_refresh_on_signal(signal: Atom[object]) -> Callable[[Atom[Any]], Atom[Any]]:
    """Refresh an atom whenever ``signal`` changes."""

    def apply(atom: Atom[Any]) -> Atom[Any]:
        def read(get: AtomContext, source: Atom[Any]) -> Any:
            get.once(signal)
            get.subscribe(signal, lambda _: get.refresh(source))
            get.subscribe(source, get.set_self)
            return get.once(source)

        return transform(atom, read, initial_value_target=atom)

    return apply


window_focus_signal: Atom[int] = readable(lambda _get: 0)
"""Counts the times a browser window regained focus: with no window
(Python has none), it stays 0, as Effect's does without one."""


def refresh_on_window_focus(atom: Atom[Any]) -> Atom[Any]:
    return make_refresh_on_signal(window_focus_signal)(atom)


def initial_value[A](atom: Atom[A], value: A, *, skip_initial_run: bool = False) -> InitialValue[A]:
    """A value to start a registry with (``atom_registry.make(
    initial_values=[...])``); with ``skip_initial_run`` an effect atom
    keeps it instead of running its effect, until refreshed."""
    return InitialValue(atom, value, skip_initial_run)


def family[K, T](f: Callable[[K], T]) -> Callable[[K], T]:
    """``f`` memoized by argument (compared with ``Equal``, so ``True`` is
    not ``1`` and lists compare by their items); an atom nothing references
    any more is dropped, and made again if asked for."""
    atoms: dict[Hashable, Callable[[], T | None]] = {}

    def get(key: K) -> T:
        slot = equal_key(key)
        ref = atoms.get(slot)
        found = None if ref is None else ref()
        if found is not None:
            return found
        made = f(key)
        try:
            atoms[slot] = weakref.ref(made, lambda _: _drop(slot))
        except TypeError:
            atoms[slot] = lambda: made
        return made

    def _drop(slot: Hashable) -> None:
        ref = atoms.get(slot)
        if ref is not None and ref() is None:
            del atoms[slot]

    return get


__all__ = [
    "debounce",
    "family",
    "initial_value",
    "label_site",
    "make_refresh_on_signal",
    "refresh_on_window_focus",
    "remove_ttl",
    "set_idle_ttl",
    "transform",
    "window_focus_signal",
    "with_fallback",
    "with_refresh",
]
