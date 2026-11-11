"""``AtomRef``: a plain observable value outside any registry (Effect's
``effect/reactivity/AtomRef``).

``make(value)`` is a ref you ``set`` and ``subscribe`` to; ``prop(key)``
focuses on one field (a mapping key, a sequence index or a dataclass
field), ``map(f)`` derives a read-only ref, and ``collection(items)`` is a
list of refs that hears of changes to any of them. Setting an equal value
(``Equal``) notifies nobody.
"""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Self, cast

from pyfect import _equal
from pyfect._public import publish

_keys = itertools.count()


def _new_key() -> str:
    return f"AtomRef-{next(_keys)}"


class _Listener[A]:
    __slots__ = ("f", "next", "prev")

    def __init__(self, f: Callable[[A], None], next_: _Listener[A] | None) -> None:
        self.f = f
        self.prev: _Listener[A] | None = None
        self.next = next_


class ReadonlyRef[A]:
    """A value that can be read and subscribed to."""

    key: str

    @property
    def value(self) -> A:
        raise NotImplementedError

    def subscribe(self, f: Callable[[A], None]) -> Callable[[], None]:
        """Call ``f`` with each new value; returns the unsubscribe."""
        raise NotImplementedError

    def map[B](self, f: Callable[[A], B]) -> ReadonlyRef[B]:
        """A ref of ``f`` of this one's value, notifying when it changes."""
        return _MapRef(self, f)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ReadonlyRef) and _equal.equals(
            self.value, cast("ReadonlyRef[Any]", other).value
        )

    def __hash__(self) -> int:
        return hash(_equal.equal_key(self.value))


class _SourceRef[A](ReadonlyRef[A]):
    """A ref holding its value, with a linked list of listeners: a listener
    that unsubscribes and resubscribes itself while notified goes to the
    front and is not called again."""

    def __init__(self, value: A) -> None:
        self.key = _new_key()
        self._value = value
        self._listeners: _Listener[A] | None = None

    @property
    def value(self) -> A:
        return self._value

    def notify(self, value: A) -> None:
        listener = self._listeners
        while listener is not None:
            listener.f(value)
            listener = listener.next

    def subscribe(self, f: Callable[[A], None]) -> Callable[[], None]:
        listener = _Listener(f, self._listeners)
        if self._listeners is not None:
            self._listeners.prev = listener
        self._listeners = listener

        def unsubscribe() -> None:
            if self._listeners is listener:
                self._listeners = listener.next
            if listener.prev is not None:
                listener.prev.next = listener.next
            if listener.next is not None:
                listener.next.prev = listener.prev

        return unsubscribe


class AtomRef[A](ReadonlyRef[A]):
    """A ref that can be set."""

    def set(self, value: A) -> Self:
        raise NotImplementedError

    def update(self, f: Callable[[A], A]) -> Self:
        return self.set(f(self.value))

    def prop(self, key: Any) -> AtomRef[Any]:
        """A ref of one field of this ref's value; setting it sets this
        ref to a copy with that field replaced."""
        return _PropRef(self, key)


class _ValueRef[A](_SourceRef[A], AtomRef[A]):
    def __init__(self, value: A, on_notify: Callable[[A], None] | None = None) -> None:
        super().__init__(value)
        self._on_notify = on_notify

    def set(self, value: A) -> Self:
        if _equal.equals(value, self._value):
            return self
        self._value = value
        self.notify(value)
        if self._on_notify is not None:
            self._on_notify(value)
        return self


class _MapRef[A, B](ReadonlyRef[B]):
    def __init__(self, parent: ReadonlyRef[A], transform: Callable[[A], B]) -> None:
        self.key = _new_key()
        self._parent = parent
        self._transform = transform

    @property
    def value(self) -> B:
        return self._transform(self._parent.value)

    def subscribe(self, f: Callable[[B], None]) -> Callable[[], None]:
        previous = [self._transform(self._parent.value)]

        def on_change(a: A) -> None:
            next_value = self._transform(a)
            if _equal.equals(next_value, previous[0]):
                return
            previous[0] = next_value
            f(next_value)

        return self._parent.subscribe(on_change)


_ABSENT = object()


def _field(value: object, key: Any) -> object:
    if isinstance(value, Mapping):
        return cast("Mapping[Any, Any]", value).get(key, _ABSENT)
    if isinstance(value, (list, tuple)):
        items = cast("list[Any] | tuple[Any, ...]", value)
        return items[key] if isinstance(key, int) and -len(items) <= key < len(items) else _ABSENT
    if dataclasses.is_dataclass(value) and isinstance(key, str):
        return getattr(value, key, _ABSENT)
    return _ABSENT


def _replaced(value: object, key: Any, field: object) -> object:
    if isinstance(value, list):
        items = list(cast("list[Any]", value))
        items[key] = field
        return items
    if isinstance(value, tuple):
        items = list(cast("tuple[Any, ...]", value))
        items[key] = field
        return tuple(items)
    if isinstance(value, Mapping):
        return {**cast("Mapping[Any, Any]", value), key: field}
    return dataclasses.replace(cast("Any", value), **{key: field})


class _PropRef(AtomRef[Any]):
    def __init__(self, parent: AtomRef[Any], key: Any) -> None:
        self.key = _new_key()
        self._parent = parent
        self._prop = key
        self._previous = _field(parent.value, key)

    @property
    def value(self) -> Any:
        found = _field(self._parent.value, self._prop)
        if found is not _ABSENT:
            self._previous = found
        return self._previous

    def subscribe(self, f: Callable[[Any], None]) -> Callable[[], None]:
        previous = [self.value]

        def on_change(a: Any) -> None:
            next_value = _field(a, self._prop)
            if next_value is _ABSENT or _equal.equals(next_value, previous[0]):
                return
            previous[0] = next_value
            f(next_value)

        return self._parent.subscribe(on_change)

    def set(self, value: Any) -> Self:
        self._parent.set(_replaced(self._parent.value, self._prop, value))
        return self

    def update(self, f: Callable[[Any], Any]) -> Self:
        current = _field(self._parent.value, self._prop)
        return self.set(f(current))


class Collection[A](_SourceRef[list[AtomRef[A]]]):
    """A list of refs; changing one, or the list, notifies the collection."""

    def __init__(self, items: Iterable[A]) -> None:
        super().__init__([])
        for item in items:
            self._value.append(self._make_ref(item))

    def _make_ref(self, value: A) -> AtomRef[A]:
        return _ValueRef(value, lambda _: self.notify(self._value))

    def push(self, item: A) -> Self:
        self._value.append(self._make_ref(item))
        self.notify(self._value)
        return self

    def insert_at(self, index: int, item: A) -> Self:
        self._value.insert(index, self._make_ref(item))
        self.notify(self._value)
        return self

    def remove(self, ref: AtomRef[A]) -> Self:
        for index, candidate in enumerate(self._value):
            if candidate is ref:
                del self._value[index]
                self.notify(self._value)
                break
        return self

    def to_list(self) -> list[A]:
        return [ref.value for ref in self._value]


def make[A](value: A) -> AtomRef[A]:
    """A ref holding ``value``."""
    return _ValueRef(value)


def collection[A](items: Iterable[A]) -> Collection[A]:
    """A collection of refs of ``items``."""
    return Collection(items)


__all__ = ["AtomRef", "Collection", "ReadonlyRef", "collection", "make"]
publish(globals())
