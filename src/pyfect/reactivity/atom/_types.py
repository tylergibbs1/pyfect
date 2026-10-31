"""The atom types: ``Atom``, ``Writable`` and the contexts their read and
write functions get.

An atom is a recipe; an ``AtomRegistry`` holds its value. ``read`` gets an
``AtomContext`` (a getter: ``get(other)`` reads another atom and makes this
one depend on it) and ``write`` a ``WriteContext``. Combinators that keep
an atom's kind (``keep_alive``, ``map``, ``with_fallback``, ...) are
methods, and a writable atom's return writable atoms.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, Protocol, Self, TypeVar, cast

from pyfect.duration import Duration, Seconds
from pyfect.option import Option

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.reactivity._reactivity import Keys
    from pyfect.reactivity.async_result import AsyncResult
    from pyfect.reactivity.atom._serializable import SerializableInfo
    from pyfect.reactivity.atom_registry import AtomRegistryService
    from pyfect.schema import Codec
    from pyfect.stream import Stream

A_co = TypeVar("A_co", covariant=True)
W_contra = TypeVar("W_contra", contravariant=True)

type Refresh = Callable[[Callable[[Atom[Any]], None]], None]
"""How an atom refreshes: it gets the registry's refresh, and refreshes the
atoms it stands for (``withFallback`` refreshes its primary)."""


def _same_value(a: object, b: object) -> bool:
    """JavaScript's ``Object.is``: numbers and strings by value (``NaN`` is
    ``NaN``, ``0.0`` is not ``-0.0``), anything else by identity."""
    if a is b:
        return True
    kind = type(a)
    if kind is not type(b) or kind not in _VALUE_TYPES:
        return False
    if kind is float:
        x, y = float(a), float(b)  # pyright: ignore[reportArgumentType]
        if math.isnan(x):
            return math.isnan(y)
        return x == y and (x != 0.0 or str(x) == str(y))
    return a == b


_VALUE_TYPES: tuple[type, ...] = (int, float, str, bytes, bool, complex)


class Atom(Generic[A_co]):
    """A value an ``AtomRegistry`` computes with ``read`` and keeps while it
    is used. ``kept_alive`` atoms stay when unused; ``lazy`` ones are
    rebuilt only when read (or observed); ``idle_ttl`` keeps an unused
    atom that long."""

    __slots__ = (
        "__weakref__",
        "equals",
        "idle_ttl",
        "initial_value_target",
        "kept_alive",
        "label",
        "lazy",
        "read",
        "refresh",
        "serializable_info",
        "server_value",
    )

    def __init__(self, read: Callable[[AtomContext], A_co], refresh: Refresh | None = None) -> None:
        self.read: Callable[[AtomContext], A_co] = read
        self.refresh: Refresh | None = refresh
        self.kept_alive = False
        self.lazy = True
        self.equals: Callable[[Any, Any], bool] = _same_value
        self.label: tuple[str, str] | None = None
        self.idle_ttl: Seconds | None = None
        self.initial_value_target: Atom[Any] | None = None
        self.serializable_info: SerializableInfo | None = None
        self.server_value: Callable[[Callable[[Atom[Any]], Any]], Any] | None = None

    def __repr__(self) -> str:
        name = "Atom" if self.label is None else f"Atom({self.label[0]!r})"
        return f"<{name} kept_alive={self.kept_alive} lazy={self.lazy}>"

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def _with(self, **changes: object) -> Self:
        changed = copy.copy(self)
        for name, value in changes.items():
            setattr(changed, name, value)
        return changed

    # --- kind-preserving combinators -------------------------------------

    def keep_alive(self) -> Self:
        """This atom, kept when nothing uses it."""
        return self._with(kept_alive=True)

    def auto_dispose(self) -> Self:
        """This atom, removed when nothing uses it."""
        return self._with(kept_alive=False)

    def set_lazy(self, lazy: bool) -> Self:
        """``False``: rebuilt as soon as a dependency changes, not when next
        read."""
        return self._with(lazy=lazy)

    def set_idle_ttl(self, duration: Duration) -> Self:
        """Keep this atom ``duration`` after it is last used; an infinite
        duration keeps it alive."""
        from pyfect.reactivity.atom._combinators import set_idle_ttl

        return set_idle_ttl(self, duration)

    def with_equality(self, equals: Callable[[A_co, A_co], bool]) -> Self:
        """Values ``equals`` calls equal are not a change: no notification,
        no rebuild of dependents."""
        return self._with(equals=equals)

    def with_label(self, name: str) -> Self:
        """Name this atom (with where the label was set)."""
        from pyfect.reactivity.atom._combinators import label_site

        return self._with(label=(name, label_site(2)))

    def with_reactivity(self, keys: Keys) -> Self:
        """Refresh this atom when ``keys`` are invalidated through the
        registry's ``Reactivity`` (the default runtime's)."""
        from pyfect.reactivity.atom._runtime import runtime

        return runtime.with_reactivity(keys)(self)

    def serializable(
        self, *, key: str, schema: Codec[Any, Any, Never, Never], skip_initial_run: bool = False
    ) -> Self:
        """Mark this atom for ``Hydration``: its value is encoded with
        ``schema`` (as JSON) under ``key``, which also identifies its node."""
        from pyfect.reactivity.atom._serializable import serializable

        return serializable(self, key=key, schema=schema, skip_initial_run=skip_initial_run)

    def with_server_value(self, read: Callable[[Callable[[Atom[Any]], Any]], A_co]) -> Self:
        """The value ``get_server_value`` reports for this atom."""
        return self._with(server_value=read)

    # --- derived atoms ---------------------------------------------------

    def map[B](self, f: Callable[[A_co], B]) -> Atom[B]:
        """An atom of ``f`` of this one's value."""
        from pyfect.reactivity.atom._combinators import transform

        return transform(self, lambda get, atom: f(get(atom)))

    def transform[B](
        self,
        f: Callable[[AtomContext, Self], B],
        *,
        initial_value_target: Atom[B] | None = None,
    ) -> Atom[B]:
        """An atom read by ``f``, which gets this atom; writes go to this
        atom, and refreshing it refreshes this one."""
        from pyfect.reactivity.atom._combinators import transform

        return transform(self, f, initial_value_target=initial_value_target)

    def map_result[A, E, B](
        self: Atom[AsyncResult[A, E]], f: Callable[[A], B]
    ) -> Atom[AsyncResult[B, E]]:
        """``map`` over the value of an ``AsyncResult``."""
        from pyfect.reactivity import async_result

        return self.map(lambda result: async_result.map(result, f))

    def with_fallback[A, E, A2, E2](
        self: Atom[AsyncResult[A, E]], fallback: Atom[AsyncResult[A2, E2]]
    ) -> Atom[AsyncResult[A | A2, E | E2]]:
        """While this atom is ``Initial``, ``fallback``'s result, marked
        waiting."""
        from pyfect.reactivity.atom._combinators import with_fallback

        return with_fallback(self, fallback)

    def debounce(self, duration: Duration) -> Atom[A_co]:
        """Changes reach this atom ``duration`` after the last one."""
        from pyfect.reactivity.atom._combinators import debounce

        return debounce(self, duration)

    def with_refresh(self, duration: Duration) -> Atom[A_co]:
        """Refresh this atom ``duration`` after each build."""
        from pyfect.reactivity.atom._combinators import with_refresh

        return with_refresh(self, duration)

    def refresh_on_signal(self, signal: Atom[object]) -> Atom[A_co]:
        """Refresh this atom whenever ``signal`` changes (Effect's
        ``makeRefreshOnSignal(signal)(self)``)."""
        from pyfect.reactivity.atom._combinators import make_refresh_on_signal

        return make_refresh_on_signal(signal)(self)

    def refresh_on_window_focus(self) -> Atom[A_co]:
        """``refresh_on_signal(window_focus_signal)``: with no browser
        window, the signal never changes."""
        from pyfect.reactivity.atom._combinators import window_focus_signal

        return self.refresh_on_signal(window_focus_signal)

    def swr[A, E](
        self: Atom[AsyncResult[A, E]],
        *,
        stale_time: Duration,
        revalidate_on_mount: bool = True,
        revalidate_on_focus: bool | Literal["always"] = False,
        focus_signal: Atom[object] | None = None,
    ) -> Atom[AsyncResult[A, E]]:
        """Stale-while-revalidate: a value older than ``stale_time`` is
        shown while a refresh runs (on mount, and on ``focus_signal`` with
        ``revalidate_on_focus``; ``"always"`` refreshes on every focus)."""
        from pyfect.reactivity.atom._swr import swr

        return swr(
            self,
            stale_time=stale_time,
            revalidate_on_mount=revalidate_on_mount,
            revalidate_on_focus=revalidate_on_focus,
            focus_signal=focus_signal,
        )

    def optimistic(self) -> Writable[A_co, Atom[AsyncResult[A_co, object]]]:
        """An atom showing optimistic values while the transitions written
        to it run, then this atom's value (refreshed after a success)."""
        from pyfect.reactivity.atom._optimistic import optimistic

        return optimistic(self)


class Writable(Atom[A_co], Generic[A_co, W_contra]):
    """An atom that takes writes of ``W``: ``registry.set(atom, value)``
    calls ``write``."""

    __slots__ = ("write",)

    def __init__(
        self,
        read: Callable[[AtomContext], A_co],
        write: Callable[[WriteContext[Any], W_contra], None],
        refresh: Refresh | None = None,
    ) -> None:
        super().__init__(read, refresh)
        self.write: Callable[[WriteContext[Any], W_contra], None] = write

    def map[B](self, f: Callable[[A_co], B]) -> Writable[B, W_contra]:
        from pyfect.reactivity.atom._combinators import transform

        return transform(self, lambda get, atom: f(get(atom)))

    def transform[B](
        self,
        f: Callable[[AtomContext, Self], B],
        *,
        initial_value_target: Atom[B] | None = None,
    ) -> Writable[B, W_contra]:
        from pyfect.reactivity.atom._combinators import transform

        return transform(self, f, initial_value_target=initial_value_target)

    def map_result[A, E, B, W](
        self: Writable[AsyncResult[A, E], W], f: Callable[[A], B]
    ) -> Writable[AsyncResult[B, E], W]:
        from pyfect.reactivity import async_result

        return self.map(lambda result: async_result.map(result, f))

    def with_fallback[A, E, A2, E2, W](
        self: Writable[AsyncResult[A, E], W], fallback: Atom[AsyncResult[A2, E2]]
    ) -> Writable[AsyncResult[A | A2, E | E2], W]:
        from pyfect.reactivity.atom._combinators import with_fallback

        return with_fallback(self, fallback)

    # Derived through ``transform``, these stay writable (writes go to
    # this atom).

    def debounce(self, duration: Duration) -> Writable[A_co, W_contra]:
        return cast("Writable[A_co, W_contra]", super().debounce(duration))

    def with_refresh(self, duration: Duration) -> Writable[A_co, W_contra]:
        return cast("Writable[A_co, W_contra]", super().with_refresh(duration))

    def refresh_on_signal(self, signal: Atom[object]) -> Writable[A_co, W_contra]:
        return cast("Writable[A_co, W_contra]", super().refresh_on_signal(signal))

    def refresh_on_window_focus(self) -> Writable[A_co, W_contra]:
        return cast("Writable[A_co, W_contra]", super().refresh_on_window_focus())

    def swr[A, E, W](
        self: Writable[AsyncResult[A, E], W],
        *,
        stale_time: Duration,
        revalidate_on_mount: bool = True,
        revalidate_on_focus: bool | Literal["always"] = False,
        focus_signal: Atom[object] | None = None,
    ) -> Writable[AsyncResult[A, E], W]:
        from pyfect.reactivity.atom._swr import swr

        derived = swr(
            self,
            stale_time=stale_time,
            revalidate_on_mount=revalidate_on_mount,
            revalidate_on_focus=revalidate_on_focus,
            focus_signal=focus_signal,
        )
        return cast("Writable[AsyncResult[A, E], W]", derived)


class AtomContext(Protocol):
    """What an atom's ``read`` gets. Calling it (``get(atom)``) or
    ``get.get(atom)`` reads ``atom`` and makes the reader depend on it;
    ``once`` reads without depending. Once the build it belongs to is
    replaced, the context only reads (updates and subscriptions are
    ignored)."""

    def __call__[A](self, atom: Atom[A], /) -> A: ...
    def get[A](self, atom: Atom[A], /) -> A: ...
    def once[A](self, atom: Atom[A], /) -> A: ...
    def result[A, E](
        self, atom: Atom[AsyncResult[A, E]], /, *, suspend_on_waiting: bool = False
    ) -> Effect[A, E]:
        """The atom's value as an effect (depending on it): its success or
        failure, waiting while it is ``Initial`` (or waiting, with
        ``suspend_on_waiting``)."""
        ...

    def result_once[A, E](
        self, atom: Atom[AsyncResult[A, E]], /, *, suspend_on_waiting: bool = False
    ) -> Effect[A, E]: ...
    def some[A](self, atom: Atom[Option[A]], /) -> Effect[A]: ...
    def some_once[A](self, atom: Atom[Option[A]], /) -> Effect[A]: ...
    def add_finalizer(self, f: Callable[[], None], /) -> None:
        """Run ``f`` when this build is replaced or the atom removed."""
        ...

    def mount(self, atom: Atom[Any], /) -> None:
        """Keep ``atom`` mounted while this build lasts."""
        ...

    def refresh(self, atom: Atom[Any], /) -> None: ...
    def refresh_self(self) -> None: ...
    def self(self) -> Option[Any]:
        """This atom's current value, if it has one."""
        ...

    def set_self(self, value: Any, /) -> None:
        """Replace this atom's value (from a callback or a fiber)."""
        ...

    def set[W](self, atom: Writable[Any, W], value: W, /) -> None: ...
    def set_result[A, E, W](
        self, atom: Writable[AsyncResult[A, E], W], value: W, /
    ) -> Effect[A, E]: ...
    def stream[A](self, atom: Atom[A], /, *, without_initial_value: bool = False) -> Stream[A]: ...
    def stream_result[A, E](
        self, atom: Atom[AsyncResult[A, E]], /, *, without_initial_value: bool = False
    ) -> Stream[A, E]: ...
    def subscribe[A](
        self, atom: Atom[A], f: Callable[[A], None], /, *, immediate: bool = False
    ) -> None: ...
    @property
    def registry(self) -> AtomRegistryService: ...


class FnContext(Protocol):
    """What a function atom's function gets (Effect's ``FnContext``): its
    reads do not make the atom depend on anything."""

    def __call__[A](self, atom: Atom[A], /) -> A: ...
    def result[A, E](
        self, atom: Atom[AsyncResult[A, E]], /, *, suspend_on_waiting: bool = False
    ) -> Effect[A, E]: ...
    def add_finalizer(self, f: Callable[[], None], /) -> None: ...
    def mount(self, atom: Atom[Any], /) -> None: ...
    def refresh(self, atom: Atom[Any], /) -> None: ...
    def self(self) -> Option[Any]: ...
    def set_self(self, value: Any, /) -> None: ...
    def set[W](self, atom: Writable[Any, W], value: W, /) -> None: ...
    def set_result[A, E, W](
        self, atom: Writable[AsyncResult[A, E], W], value: W, /
    ) -> Effect[A, E]: ...
    def some[A](self, atom: Atom[Option[A]], /) -> Effect[A]: ...
    def stream[A](self, atom: Atom[A], /, *, without_initial_value: bool = False) -> Stream[A]: ...
    def stream_result[A, E](
        self, atom: Atom[AsyncResult[A, E]], /, *, without_initial_value: bool = False
    ) -> Stream[A, E]: ...
    def subscribe[A](
        self, atom: Atom[A], f: Callable[[A], None], /, *, immediate: bool = False
    ) -> None: ...
    @property
    def registry(self) -> AtomRegistryService: ...


class WriteContext[A](Protocol):
    """What a writable atom's ``write`` gets."""

    def get[T](self, atom: Atom[T], /) -> T: ...
    def refresh_self(self) -> None: ...
    def set_self(self, value: A, /) -> None: ...
    def set[W](self, atom: Writable[Any, W], value: W, /) -> None: ...


def readable[A](read: Callable[[AtomContext], A], refresh: Refresh | None = None) -> Atom[A]:
    """An atom computed by ``read``."""
    return Atom(read, refresh)


def writable[R, W](
    read: Callable[[AtomContext], R],
    write: Callable[[WriteContext[R], W], None],
    refresh: Refresh | None = None,
) -> Writable[R, W]:
    """An atom computed by ``read`` that takes writes through ``write``."""
    return Writable(read, write, refresh)


def is_atom(u: object) -> bool:
    return isinstance(u, Atom)


def is_writable(atom: Atom[Any]) -> bool:
    return isinstance(atom, Writable)


__all__ = [
    "Atom",
    "AtomContext",
    "FnContext",
    "Refresh",
    "Writable",
    "WriteContext",
    "is_atom",
    "is_writable",
    "readable",
    "writable",
]
