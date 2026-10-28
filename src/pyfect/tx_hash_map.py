"""``TxHashMap[K, V]``: a transactional hash map (Effect's ``TxHashMap``).

The value is a ``dict`` held in a ``TxRef`` and never mutated: a write
copies it (copy-on-write), so a snapshot stays as it was. Every operation
joins the running transaction (``fx.tx``) or runs as one of its own.
Iteration follows insertion order, where Effect's follows its HAMT's hash
order.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any, Never, TypeIs, overload

from pyfect import _tx_ops
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import same_value
from pyfect._primitives import _Gen
from pyfect.option import Option, Some
from pyfect.result import Ok, Result
from pyfect.transaction import tx
from pyfect.tx_ref import TxRef


class TxHashMap[K, V]:
    """``TxHashMap(ref)`` wraps an existing ``TxRef``; ``empty``, ``make``
    and ``from_iterable`` are the effects."""

    __slots__ = ("_ref",)

    def __init__(self, ref: TxRef[dict[K, V]]) -> None:
        self._ref = ref

    @classmethod
    def empty(cls) -> Effect[TxHashMap[K, V]]:
        """Spelled ``TxHashMap[str, int].empty()``."""
        return _new(dict[K, V]())

    @staticmethod
    def make[K2, V2](*entries: tuple[K2, V2]) -> Effect[TxHashMap[K2, V2]]:
        return TxHashMap.from_iterable(entries)

    @staticmethod
    def from_iterable[K2, V2](entries: Iterable[tuple[K2, V2]]) -> Effect[TxHashMap[K2, V2]]:
        """A new map each time the effect runs. ``entries`` is read once,
        here, so a one-shot iterator survives transaction retries."""
        return _new(dict(entries))

    @property
    def ref(self) -> TxRef[dict[K, V]]:
        return self._ref

    # --- reads ---------------------------------------------------------------

    def get(self, key: K) -> Effect[Option[V]]:
        return _tx_ops.read(self._ref, lambda d: Some(d[key]) if key in d else None)

    def has(self, key: K) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda d: key in d)

    def get_hash(self, key: K, hash: int) -> Effect[Option[V]]:
        """``get``, finding nothing unless ``hash`` is ``hash(key)``."""
        return _tx_ops.read(
            self._ref, lambda d: Some(d[key]) if key in d and _hash(key) == hash else None
        )

    def has_hash(self, key: K, hash: int) -> Effect[bool]:
        """``has``, finding nothing unless ``hash`` is ``hash(key)``."""
        return _tx_ops.read(self._ref, lambda d: key in d and _hash(key) == hash)

    def size(self) -> Effect[int]:
        return _tx_ops.read(self._ref, len)

    def is_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, lambda d: not d)

    def is_non_empty(self) -> Effect[bool]:
        return _tx_ops.read(self._ref, bool)

    def keys(self) -> Effect[list[K]]:
        return _tx_ops.read(self._ref, list)

    def values(self) -> Effect[list[V]]:
        return _tx_ops.read(self._ref, lambda d: list(d.values()))

    def entries(self) -> Effect[list[tuple[K, V]]]:
        return _tx_ops.read(self._ref, lambda d: list(d.items()))

    def to_entries(self) -> Effect[list[tuple[K, V]]]:
        return self.entries()

    def to_values(self) -> Effect[list[V]]:
        return self.values()

    def snapshot(self) -> Effect[Mapping[K, V]]:
        """A read-only view of the map as it is now; later writes copy, so
        the view never changes."""
        return _tx_ops.read(self._ref, MappingProxyType)

    def reduce[A](self, zero: A, f: Callable[[A, V, K], A]) -> Effect[A]:
        def fold(d: dict[K, V]) -> A:
            acc = zero
            for key, value in d.items():
                acc = f(acc, value, key)
            return acc

        return _tx_ops.read(self._ref, fold)

    def has_by(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return self.some(predicate)

    def some(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return _tx_ops.read(
            self._ref, lambda d: any(predicate(value, key) for key, value in d.items())
        )

    def every(self, predicate: Callable[[V, K], bool]) -> Effect[bool]:
        return _tx_ops.read(
            self._ref, lambda d: all(predicate(value, key) for key, value in d.items())
        )

    def find_first(self, predicate: Callable[[V, K], bool]) -> Effect[tuple[K, V] | None]:
        return _tx_ops.read(
            self._ref,
            lambda d: next(
                ((key, value) for key, value in d.items() if predicate(value, key)), None
            ),
        )

    def for_each[E = Never, R = Never](
        self, f: Callable[[V, K], Effect[Any, E, R]]
    ) -> Effect[None, E, R]:
        """Run ``f`` on each entry of the map as it was read, in order."""
        return (
            self.entries()
            .flat_map(lambda items: for_each(items, lambda entry: f(entry[1], entry[0])))
            .as_void()
        )

    # --- writes --------------------------------------------------------------

    def set(self, key: K, value: V) -> Effect[None]:
        return self._ref.update(lambda d: _set_all(d, ((key, value),)))

    def remove(self, key: K) -> Effect[bool]:
        """Remove ``key``; ``True`` when it was there."""
        return _tx_ops.modify_or_skip(
            self._ref, lambda d: (True, Some(_without(d, (key,)))) if key in d else (False, None)
        )

    def clear(self) -> Effect[None]:
        return self._ref.set({})

    def modify(self, key: K, f: Callable[[V], V]) -> Effect[Option[V]]:
        """Replace the value at ``key`` with ``f`` of it; the old value, or
        ``None`` (and no write) when ``key`` is absent."""

        def run(d: dict[K, V]) -> tuple[Option[V], Option[dict[K, V]]]:
            if key not in d:
                return None, None
            old = d[key]
            return Some(old), Some(_set_all(d, ((key, f(old)),)))

        return _tx_ops.modify_or_skip(self._ref, run)

    def modify_at(self, key: K, f: Callable[[Option[V]], Option[V]]) -> Effect[None]:
        """Set ``key`` to what ``f`` returns for its current value, or remove
        it when ``f`` returns ``None``."""

        def run(d: dict[K, V]) -> tuple[None, Option[dict[K, V]]]:
            current = Some(d[key]) if key in d else None
            match f(current):
                case Some(value):
                    return None, Some(_set_all(d, ((key, value),)))
                case None:
                    return None, None if current is None else Some(_without(d, (key,)))

        return _tx_ops.modify_or_skip(self._ref, run)

    def union(self, other: Mapping[K, V]) -> Effect[None]:
        """Add ``other``'s entries, replacing values at shared keys."""
        return self._ref.update(lambda d: _set_all(d, other.items()))

    def set_many(self, entries: Iterable[tuple[K, V]]) -> Effect[None]:
        """Set every entry; ``entries`` is read once, here."""
        added = list(entries)
        return self._ref.update(lambda d: _set_all(d, added))

    def remove_many(self, keys: Iterable[K]) -> Effect[None]:
        """Remove every key; ``keys`` is read once, here."""
        removed = list(keys)
        return self._ref.update(lambda d: _without(d, removed))

    # --- new maps ------------------------------------------------------------

    def map[A](self, f: Callable[[V, K], A]) -> Effect[TxHashMap[K, A]]:
        return _derive(self, lambda d: {key: f(value, key) for key, value in d.items()})

    @overload
    def filter[B](self, predicate: Callable[[V, K], TypeIs[B]]) -> Effect[TxHashMap[K, B]]: ...
    @overload
    def filter(self, predicate: Callable[[V, K], bool]) -> Effect[TxHashMap[K, V]]: ...
    def filter(self, predicate: Callable[[V, K], bool]) -> Effect[TxHashMap[K, Any]]:
        return _derive(self, lambda d: {key: v for key, v in d.items() if predicate(v, key)})

    def filter_map[A](self, f: Callable[[V, K], Result[A, object]]) -> Effect[TxHashMap[K, A]]:
        """A new map of the ``Ok`` values ``f`` gives; ``Err`` drops the
        entry."""

        def build(d: dict[K, V]) -> dict[K, A]:
            out: dict[K, A] = {}
            for key, value in d.items():
                match f(value, key):
                    case Ok(mapped):
                        out[key] = mapped
                    case _:
                        pass
            return out

        return _derive(self, build)

    def compact[A](self: TxHashMap[K, Option[A]]) -> Effect[TxHashMap[K, A]]:
        """A new map of the ``Some`` values, unwrapped."""
        return _derive(
            self, lambda d: {key: value.value for key, value in d.items() if value is not None}
        )

    def flat_map[A, E = Never, R = Never](
        self, f: Callable[[V, K], Effect[TxHashMap[K, A], E, R]]
    ) -> Effect[TxHashMap[K, A], E, R]:
        """A new map of the entries of every map ``f`` gives, in one
        transaction; later entries replace earlier ones."""

        def body():
            source = yield from self.entries()
            out: dict[K, A] = {}
            for key, value in source:
                produced = yield from f(value, key)
                out.update((yield from produced.entries()))
            return TxHashMap(TxRef(out))

        return tx(_Gen(body))

    def __repr__(self) -> str:
        return f"TxHashMap({self._ref!r})"


_hash = hash


def _new[K, V](d: dict[K, V]) -> Effect[TxHashMap[K, V]]:
    return TxRef.make(d).map(TxHashMap)


def _derive[K, V, K2, V2](
    source: TxHashMap[K, V], f: Callable[[dict[K, V]], dict[K2, V2]]
) -> Effect[TxHashMap[K2, V2]]:
    return _tx_ops.read(source._ref, lambda d: TxHashMap(TxRef(f(d))))


# The only places a map's dict is rebuilt. Like Effect's HAMT, each returns
# ``d`` itself when nothing changes (a value replaced by one that is
# ``Object.is`` the same), so the commit leaves the ref's version alone.


def _set_all[K, V](d: dict[K, V], entries: Iterable[tuple[K, V]]) -> dict[K, V]:
    out = d
    for key, value in entries:
        if out is d:
            if key in d and same_value(d[key], value):
                continue
            out = d.copy()
        out[key] = value
    return out


def _without[K, V](d: dict[K, V], keys: Iterable[K]) -> dict[K, V]:
    out = d
    for key in keys:
        if key in out:
            if out is d:
                out = d.copy()
            del out[key]
    return out


__all__ = ["TxHashMap"]
