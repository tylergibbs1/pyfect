"""``Trie[V]``: an immutable map from strings to values, iterated in key
order, with prefix queries (Effect's ``Trie``)::

    t = Trie.make(("she", 0), ("shells", 1), ("sea", 2))
    list(t.keys_with_prefix("she"))  # ["she", "shells"]
    t.longest_prefix_of("shellsort")  # Some(("shells", 1))

Keys are ordered by their UTF-16 code units, as JavaScript compares strings
(so a character past U+FFFF sorts below U+E000, where Python's ``<`` puts it
above). The empty string is never a key: inserting it returns the same
trie. Every update returns a new trie and leaves this one as it was; like
Effect's, the trie is persistent, so an update copies only the nodes along
its key.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, TypeIs, overload

from pyfect._equal import equal_key, equals
from pyfect._js import js_sort_key
from pyfect._unsubscripted import Unsubscripted
from pyfect.option import Option, Some
from pyfect.result import Ok, Result


class _Node:
    """A node of the character trie; never changed once built. ``count``
    is the number of keys at or below it."""

    __slots__ = ("_order", "children", "count", "has", "value")

    def __init__(self, has: bool, value: object, children: dict[str, _Node]) -> None:
        self.has = has
        self.value = value
        self.children = children
        self.count = int(has) + sum(child.count for child in children.values())
        self._order: tuple[tuple[str, _Node], ...] | None = None

    def ordered(self) -> tuple[tuple[str, _Node], ...]:
        """The children in UTF-16 order, sorted once."""
        if self._order is None:
            self._order = tuple(sorted(self.children.items(), key=lambda kv: js_sort_key(kv[0])))
        return self._order


_EMPTY = _Node(False, None, {})


def _descend(node: _Node, key: str) -> _Node | None:
    for c in key:
        child = node.children.get(c)
        if child is None:
            return None
        node = child
    return node


def _walk(node: _Node, prefix: str) -> Iterator[tuple[str, object]]:
    """The entries at and below ``node`` in key order, without recursion."""
    stack: list[tuple[str, _Node]] = [(prefix, node)]
    while stack:
        key, n = stack.pop()
        if n.has:
            yield key, n.value
        stack.extend((key + c, child) for c, child in reversed(n.ordered()))


def _replace(root: _Node, key: str, leaf: _Node | None) -> _Node:
    """``root`` with the node at ``key`` (which exists up to its parent)
    replaced by ``leaf``; ``None`` drops it, and parents left empty."""
    if not key:
        return _EMPTY if leaf is None else leaf
    path = [root]
    for c in key[:-1]:
        path.append(path[-1].children[c])
    node = leaf
    for c, parent in zip(reversed(key), reversed(path), strict=True):
        children = dict(parent.children)
        if node is None:
            del children[c]
        else:
            children[c] = node
        node = (
            None
            if not children and not parent.has and parent is not root
            else (_Node(parent.has, parent.value, children))
        )
    return _EMPTY if node is None else node


class Trie[V = Unsubscripted]:
    """Build one with ``Trie.empty()``, ``Trie.make(*entries)`` or
    ``Trie.from_iterable(entries)``."""

    __slots__ = ("_root",)

    _root: _Node

    def __init__(self, root: _Node = _EMPTY) -> None:
        self._root = root

    @classmethod
    def empty(cls) -> Trie[V]:
        """Spelled ``Trie[int].empty()``."""
        return Trie()

    @overload
    @classmethod
    def make[V2](cls: type[Trie[Unsubscripted]], *entries: tuple[str, V2]) -> Trie[V2]: ...
    @overload
    @classmethod
    def make(cls, *entries: tuple[str, V]) -> Trie[V]: ...
    @classmethod
    def make[V2](cls, *entries: tuple[str, V2]) -> Trie[V2]:
        return Trie.from_iterable(entries)

    @overload
    @classmethod
    def from_iterable[V2](
        cls: type[Trie[Unsubscripted]], entries: Iterable[tuple[str, V2]]
    ) -> Trie[V2]: ...
    @overload
    @classmethod
    def from_iterable(cls, entries: Iterable[tuple[str, V]]) -> Trie[V]: ...
    @classmethod
    def from_iterable[V2](cls, entries: Iterable[tuple[str, V2]]) -> Trie[V2]:
        """The trie of ``entries``; a later value for a key wins."""
        return Trie[V2]().insert_many(entries)

    # --- reading ------------------------------------------------------------------

    def _node(self, key: str) -> _Node | None:
        node = _descend(self._root, key)
        return node if node is not None and node.has else None

    def __len__(self) -> int:
        return self._root.count

    def __bool__(self) -> bool:
        return self._root.count > 0

    def __iter__(self) -> Iterator[tuple[str, V]]:
        return self.entries()

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self.has(key)

    def is_empty(self) -> bool:
        return self._root.count == 0

    def get(self, key: str) -> Option[V]:
        node = self._node(key)
        return None if node is None else Some(self._value(node))

    def has(self, key: str) -> bool:
        return self._node(key) is not None

    def get_unsafe(self, key: str) -> V:
        """The value for ``key``; raises ``KeyError`` without one."""
        node = self._node(key)
        if node is None:
            raise KeyError("Expected trie to contain key")
        return self._value(node)

    def _value(self, node: _Node) -> V:
        return node.value  # pyright: ignore[reportReturnType]

    def keys(self) -> Iterator[str]:
        """The keys in order."""
        return (k for k, _ in self.entries())

    def values(self) -> Iterator[V]:
        """The values in key order."""
        return (v for _, v in self.entries())

    def entries(self) -> Iterator[tuple[str, V]]:
        """The ``(key, value)`` pairs in key order."""
        return self.entries_with_prefix("")

    def to_entries(self) -> list[tuple[str, V]]:
        return list(self.entries())

    def keys_with_prefix(self, prefix: str) -> Iterator[str]:
        """The keys starting with ``prefix``, in order."""
        return (k for k, _ in self.entries_with_prefix(prefix))

    def values_with_prefix(self, prefix: str) -> Iterator[V]:
        return (v for _, v in self.entries_with_prefix(prefix))

    def entries_with_prefix(self, prefix: str) -> Iterator[tuple[str, V]]:
        node = _descend(self._root, prefix)
        if node is None:
            return iter(())
        return _walk(node, prefix)  # pyright: ignore[reportReturnType]

    def to_entries_with_prefix(self, prefix: str) -> list[tuple[str, V]]:
        return list(self.entries_with_prefix(prefix))

    def longest_prefix_of(self, key: str) -> Option[tuple[str, V]]:
        """The entry whose key is the longest one that ``key`` starts with."""
        node = self._root
        found = (0, node) if node.has else None
        for end, c in enumerate(key, 1):
            child = node.children.get(c)
            if child is None:
                break
            node = child
            if node.has:
                found = (end, node)
        if found is None:
            return None
        return Some((key[: found[0]], self._value(found[1])))

    def reduce[Z](self, zero: Z, f: Callable[[Z, V, str], Z]) -> Z:
        """Fold the entries in key order."""
        out = zero
        for k, v in self.entries():
            out = f(out, v, k)
        return out

    def for_each(self, f: Callable[[V, str], object]) -> None:
        for k, v in self.entries():
            f(v, k)

    # --- updates --------------------------------------------------------------------

    def insert(self, key: str, value: V) -> Trie[V]:
        """The trie with ``key`` set to ``value``."""
        root, depth = self._root, 0
        node: _Node | None = root
        while depth < len(key) and node is not None:
            node = node.children.get(key[depth])
            depth += 1
        if node is not None:
            return Trie(_replace(root, key, _Node(True, value, node.children)))
        # ``key[:depth - 1]`` exists: grow the rest as a chain below it.
        leaf = _Node(True, value, {})
        for c in reversed(key[depth:]):
            leaf = _Node(False, None, {c: leaf})
        return Trie(_replace(root, key[:depth], leaf))

    def insert_many(self, entries: Iterable[tuple[str, V]]) -> Trie[V]:
        out = self
        for key, value in entries:
            out = out.insert(key, value)
        return out

    def remove(self, key: str) -> Trie[V]:
        """The trie without ``key``; the same trie when it has no ``key``."""
        node = self._node(key)
        if node is None:
            return self
        leaf = _Node(False, None, node.children) if node.children else None
        return Trie(_replace(self._root, key, leaf))

    def remove_many(self, keys: Iterable[str]) -> Trie[V]:
        out = self
        for key in keys:
            out = out.remove(key)
        return out

    def modify(self, key: str, f: Callable[[V], V]) -> Trie[V]:
        """The trie with ``key``'s value replaced by ``f(value)``; the same
        trie without ``key``."""
        node = self._node(key)
        if node is None:
            return self
        return self.insert(key, f(self._value(node)))

    def _rebuilt[A](self, entries: Iterable[tuple[str, A]]) -> Trie[A]:
        return Trie[A]().insert_many(list(entries))

    def map[A](self, f: Callable[[V, str], A]) -> Trie[A]:
        return self._rebuilt((k, f(v, k)) for k, v in self.entries())

    @overload
    def filter[B](self, predicate: Callable[[V, str], TypeIs[B]]) -> Trie[B]: ...
    @overload
    def filter(self, predicate: Callable[[V, str], bool]) -> Trie[V]: ...
    def filter(self, predicate: Callable[[V, str], bool]) -> Trie[Any]:
        return self._rebuilt((k, v) for k, v in self.entries() if predicate(v, k))

    def filter_map[A](self, f: Callable[[V, str], Result[A, object]]) -> Trie[A]:
        """The entries ``f(value, key)`` keeps (``Ok``), with its values."""

        def kept() -> Iterator[tuple[str, A]]:
            for k, v in self.entries():
                result = f(v, k)
                if isinstance(result, Ok):
                    yield k, result.value

        return self._rebuilt(kept())

    def compact[A](self: Trie[Option[A]]) -> Trie[A]:
        """The ``Some`` values, unwrapped."""
        return self._rebuilt((k, v.value) for k, v in self.entries() if isinstance(v, Some))

    # --- equality -------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Trie):
            return NotImplemented
        theirs = Trie[object].to_entries(other)  # pyright: ignore[reportUnknownArgumentType]
        mine = self.to_entries()
        return len(mine) == len(theirs) and all(
            a[0] == b[0] and equals(a[1], b[1]) for a, b in zip(mine, theirs, strict=True)
        )

    def __hash__(self) -> int:
        return hash(tuple((k, equal_key(v)) for k, v in self.entries()))

    def __repr__(self) -> str:
        return f"Trie({self.to_entries()!r})"


__all__ = ["Trie"]
