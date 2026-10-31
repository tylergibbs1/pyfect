"""Effects and streams reading atoms from the ``AtomRegistry`` service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect
from pyfect.reactivity import atom_registry
from pyfect.reactivity.async_result import AsyncResult
from pyfect.reactivity.atom._types import Atom, Writable
from pyfect.reactivity.atom_registry import AtomRegistry
from pyfect.scope import Scope
from pyfect.stream import Stream


def _registry() -> Effect[atom_registry.AtomRegistryService, Never, AtomRegistry]:
    return AtomRegistry()


def get[A](atom: Atom[A]) -> Effect[A, Never, AtomRegistry]:
    return _registry().map(lambda r: r.get(atom))


def set[W](atom: Writable[Any, W], value: W) -> Effect[None, Never, AtomRegistry]:
    return _registry().map(lambda r: r.set(atom, value))


def update[R, W](atom: Writable[R, W], f: Callable[[R], W]) -> Effect[None, Never, AtomRegistry]:
    return _registry().map(lambda r: r.update(atom, f))


def modify[R, W, A](
    atom: Writable[R, W], f: Callable[[R], tuple[A, W]]
) -> Effect[A, Never, AtomRegistry]:
    return _registry().map(lambda r: r.modify(atom, f))


def refresh(atom: Atom[Any]) -> Effect[None, Never, AtomRegistry]:
    return _registry().map(lambda r: r.refresh(atom))


def get_result[A, E](
    atom: Atom[AsyncResult[A, E]], *, suspend_on_waiting: bool = False
) -> Effect[A, E, AtomRegistry]:
    """The atom's success or failure, once it has one."""
    return _registry().flat_map(
        lambda r: atom_registry.get_result(r, atom, suspend_on_waiting=suspend_on_waiting)
    )


def mount(atom: Atom[Any]) -> Effect[None, Never, AtomRegistry | Scope]:
    """Keep ``atom`` mounted until the current scope closes."""
    return _registry().flat_map(lambda r: atom_registry.mount(r, atom))


def to_stream[A](atom: Atom[A]) -> Stream[A, Never, AtomRegistry]:
    from pyfect import stream

    return stream.unwrap(_registry().map(lambda r: atom_registry.to_stream(r, atom)))


def to_stream_result[A, E](atom: Atom[AsyncResult[A, E]]) -> Stream[A, E, AtomRegistry]:
    from pyfect import stream

    return stream.unwrap(_registry().map(lambda r: atom_registry.to_stream_result(r, atom)))


__all__ = [
    "get",
    "get_result",
    "modify",
    "mount",
    "refresh",
    "set",
    "to_stream",
    "to_stream_result",
    "update",
]
