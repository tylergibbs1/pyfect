"""``atom.make``: an atom from a value, a function, an effect or a stream."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload
from warnings import deprecated

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.errors import NoSuchElementException
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._effect import MISSING, initial_option, make_read
from pyfect.reactivity.atom._types import Atom, AtomContext, Writable, readable
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.scope import Scope
from pyfect.stream import Stream

_EMPTY: Context[Never] = Context.empty()


@overload
def make[A, E = Never](
    effect: Effect[A, E, Scope | AtomRegistry],
    /,
    *,
    initial_value: A = ...,
    uninterruptible: bool = False,
) -> Atom[AsyncResult[A, E]]: ...
@overload
def make[A, E = Never](
    stream: Stream[A, E, AtomRegistry], /, *, initial_value: A = ...
) -> Atom[AsyncResult[A, E | NoSuchElementException]]: ...
@overload
def make[A, E = Never](
    create: Callable[[AtomContext], Effect[A, E, Scope | AtomRegistry]],
    /,
    *,
    initial_value: A = ...,
    uninterruptible: bool = False,
) -> Atom[AsyncResult[A, E]]: ...
@overload
def make[A, E = Never](
    create: Callable[[AtomContext], Stream[A, E, AtomRegistry]],
    /,
    *,
    initial_value: A = ...,
) -> Atom[AsyncResult[A, E | NoSuchElementException]]: ...
@overload
def make[A](create: Callable[[AtomContext], A], /) -> Atom[A]: ...  # pyright: ignore[reportOverlappingOverload]
@overload
@deprecated("it needs services an atom cannot provide: build it with a runtime's atom()")
def make(
    effect: Effect[Any, Any, Any] | Stream[Any, Any, Any],
    /,
    *,
    initial_value: Any = ...,
    uninterruptible: bool = False,
) -> Never: ...
@overload
def make[A](initial: A, /) -> Writable[A, A]: ...
def make(arg: object, /, *, initial_value: object = MISSING, uninterruptible: bool = False) -> Any:
    """An atom of ``arg``:

    - an ``Effect`` (needing at most ``Scope`` and ``AtomRegistry``): an
      ``AsyncResult`` of it, run when the atom is built (``initial_value``
      is shown, as a success, until it finishes);
    - a ``Stream``: an ``AsyncResult`` of its latest item, waiting until it
      ends (an empty one fails with ``NoSuchElementException``);
    - a function of an ``AtomContext``: a derived atom, rebuilt when what
      it read changes (an effect or stream it returns is run as above);
    - anything else: a writable atom holding that value.
    """
    read = make_read(arg, initial_option(initial_value), uninterruptible)
    if not callable(read):
        return read
    return readable(lambda get: read(get, _EMPTY))


__all__ = ["make"]
