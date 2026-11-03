"""``MutableHashSet[A]``: a mutable set whose members compare as Effect's
``Equal.equals`` does (Effect's ``MutableHashSet``): ``True`` apart from
``1``, NaN one member, lists, tuples, dicts and sets members by their items.
Iteration follows insertion order; being mutable, it is unhashable."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator
from typing import cast, overload

from pyfect._equal import equal_key
from pyfect._unsubscripted import Unsubscripted


class MutableHashSet[A = Unsubscripted]:
    """Build one with ``MutableHashSet.empty()``, ``make(*values)`` or
    ``from_iterable(values)``. Updates return the set itself."""

    __slots__ = ("_members",)

    _members: dict[Hashable, A]

    def __init__(self) -> None:
        self._members = {}

    @classmethod
    def empty(cls) -> MutableHashSet[A]:
        """Spelled ``MutableHashSet[str].empty()``."""
        return MutableHashSet()

    @overload
    @classmethod
    def make[B](cls: type[MutableHashSet[Unsubscripted]], *values: B) -> MutableHashSet[B]: ...
    @overload
    @classmethod
    def make(cls, *values: A) -> MutableHashSet[A]: ...
    @classmethod
    def make[B](cls, *values: B) -> MutableHashSet[B]:
        return MutableHashSet.from_iterable(values)

    @overload
    @classmethod
    def from_iterable[B](
        cls: type[MutableHashSet[Unsubscripted]], values: Iterable[B]
    ) -> MutableHashSet[B]: ...
    @overload
    @classmethod
    def from_iterable(cls, values: Iterable[A]) -> MutableHashSet[A]: ...
    @classmethod
    def from_iterable[B](cls, values: Iterable[B]) -> MutableHashSet[B]:
        out = MutableHashSet[B]()
        for value in values:
            out.add(value)
        return out

    def __len__(self) -> int:
        return len(self._members)

    def __bool__(self) -> bool:
        return bool(self._members)

    def __iter__(self) -> Iterator[A]:
        return iter(list(self._members.values()))

    def __contains__(self, value: object) -> bool:
        return self.has(value)

    def has(self, value: object) -> bool:
        return equal_key(value) in self._members

    def add(self, value: A) -> MutableHashSet[A]:
        self._members.setdefault(equal_key(value), value)
        return self

    def remove(self, value: A) -> MutableHashSet[A]:
        self._members.pop(equal_key(value), None)
        return self

    def clear(self) -> MutableHashSet[A]:
        self._members.clear()
        return self

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MutableHashSet):
            return NotImplemented
        theirs = cast("MutableHashSet[object]", other)._members
        return self._members.keys() == theirs.keys()

    __hash__ = None  # pyright: ignore[reportAssignmentType]

    def __repr__(self) -> str:
        return f"MutableHashSet({list(self._members.values())!r})"


__all__ = ["MutableHashSet"]
