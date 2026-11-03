"""A persistent hash array mapped trie, the storage of ``HashMap`` and
``HashSet`` (Effect's ``internal/hashMap.ts``).

Entries are keyed by an ``equal_key`` (``pyfect._equal``), already hashable
and ``==`` exactly when Effect's ``Equal.equals`` is. Every update copies
only the nodes on the path to its entry, so it costs about
``log32(size)`` and shares the rest with the old trie. ``None`` is the
empty trie. Hashes are Effect's (``pyfect._effect_hash``), 32 bits read five
at a time from the low end as Effect's trie reads them, so entries sit and
iterate in Effect's order.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterator
from typing import NamedTuple

from pyfect._effect_hash import effect_hash
from pyfect._js import same_value

_BITS = 5
_MASK = (1 << _BITS) - 1


class Entry[K, V](NamedTuple):
    hash: int
    ident: Hashable
    key: K
    value: V


class _Bitmap:
    """Children by the 5 hash bits at its depth; ``bitmap`` marks which."""

    __slots__ = ("bitmap", "children")

    def __init__(self, bitmap: int, children: tuple[Node, ...]) -> None:
        self.bitmap = bitmap
        self.children = children


class _Collision:
    """Entries whose 64-bit hashes are all equal."""

    __slots__ = ("entries", "hash")

    def __init__(self, hash: int, entries: tuple[Entry[object, object], ...]) -> None:
        self.hash = hash
        self.entries = entries


type Node = _Bitmap | _Collision | Entry[object, object]


def hash_of(ident: Hashable) -> int:
    return effect_hash(ident)


def find(node: Node | None, hash: int, ident: Hashable) -> Entry[object, object] | None:
    shift = 0
    while True:
        match node:
            case None:
                return None
            case Entry():
                return node if node.hash == hash and node.ident == ident else None
            case _Collision():
                if node.hash != hash:
                    return None
                return next((e for e in node.entries if e.ident == ident), None)
            case _Bitmap():
                bit = 1 << ((hash >> shift) & _MASK)
                if not node.bitmap & bit:
                    return None
                node = node.children[(node.bitmap & (bit - 1)).bit_count()]
                shift += _BITS


def insert(node: Node | None, entry: Entry[object, object], shift: int = 0) -> Node:  # noqa: PLR0911
    """``node`` with ``entry``, replacing the one of an equal ``ident``; the
    same node when that entry already holds this value (``Object.is``, as
    Effect's). An existing entry keeps its key."""
    match node:
        case None:
            return entry
        case Entry():
            if node.hash == entry.hash and node.ident == entry.ident:
                if same_value(node.value, entry.value):
                    return node
                return Entry(node.hash, node.ident, node.key, entry.value)
            return _merge(node, entry, shift)
        case _Collision():
            if node.hash != entry.hash:
                return _merge(node, entry, shift)
            for i, old in enumerate(node.entries):
                if old.ident == entry.ident:
                    if same_value(old.value, entry.value):
                        return node
                    kept = Entry(old.hash, old.ident, old.key, entry.value)
                    return _Collision(node.hash, (*node.entries[:i], kept, *node.entries[i + 1 :]))
            return _Collision(node.hash, (*node.entries, entry))
        case _Bitmap():
            bit = 1 << ((entry.hash >> shift) & _MASK)
            index = (node.bitmap & (bit - 1)).bit_count()
            children = node.children
            if not node.bitmap & bit:
                return _Bitmap(node.bitmap | bit, (*children[:index], entry, *children[index:]))
            child = insert(children[index], entry, shift + _BITS)
            if child is children[index]:
                return node
            return _Bitmap(node.bitmap, (*children[:index], child, *children[index + 1 :]))


def _merge(
    old: Entry[object, object] | _Collision, entry: Entry[object, object], shift: int
) -> Node:
    """A node holding ``old`` and ``entry`` at depth ``shift``."""
    if old.hash == entry.hash:
        olds = old.entries if isinstance(old, _Collision) else (old,)
        return _Collision(entry.hash, (*olds, entry))
    a, b = (old.hash >> shift) & _MASK, (entry.hash >> shift) & _MASK
    if a == b:
        return _Bitmap(1 << a, (_merge(old, entry, shift + _BITS),))
    pair: tuple[Node, ...] = (old, entry) if a < b else (entry, old)
    return _Bitmap((1 << a) | (1 << b), pair)


def remove(node: Node | None, hash: int, ident: Hashable, shift: int = 0) -> Node | None:  # noqa: PLR0911
    """``node`` without the entry of ``ident``: the same node when it has
    none, ``None`` when that leaves it empty."""
    match node:
        case None:
            return None
        case Entry():
            return None if node.hash == hash and node.ident == ident else node
        case _Collision():
            if node.hash != hash:
                return node
            kept = tuple(e for e in node.entries if e.ident != ident)
            if len(kept) == len(node.entries):
                return node
            return kept[0] if len(kept) == 1 else _Collision(node.hash, kept)
        case _Bitmap():
            bit = 1 << ((hash >> shift) & _MASK)
            if not node.bitmap & bit:
                return node
            index = (node.bitmap & (bit - 1)).bit_count()
            children = node.children
            child = remove(children[index], hash, ident, shift + _BITS)
            if child is children[index]:
                return node
            if child is None:
                if len(children) == 1:
                    return None
                rest = (*children[:index], *children[index + 1 :])
                if len(rest) == 1 and not isinstance(rest[0], _Bitmap):
                    return rest[0]
                return _Bitmap(node.bitmap & ~bit, rest)
            if len(children) == 1 and not isinstance(child, _Bitmap):
                return child
            return _Bitmap(node.bitmap, (*children[:index], child, *children[index + 1 :]))


def entries(node: Node | None) -> Iterator[Entry[object, object]]:
    match node:
        case None:
            return
        case Entry():
            yield node
        case _Collision():
            yield from node.entries
        case _Bitmap():
            for child in node.children:
                yield from entries(child)
