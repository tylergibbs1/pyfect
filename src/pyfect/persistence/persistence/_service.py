"""The ``Persistence`` service over a ``BackingPersistence`` (Effect's
``Persistence.layer``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Generator, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Never, Protocol

from pyfect import _json_text
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.clock import ClockService
from pyfect.context import Tag
from pyfect.duration import Seconds, to_millis, to_seconds
from pyfect.effect import fail, gen, succeed, suspend, void
from pyfect.exit import Exit, Failure
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.persistable import (
    AnyPersistable,
    Persistable,
    TimeToLive,
    deserialize_exit,
    serialize_exit,
)
from pyfect.schema import SchemaError
from pyfect.scope import CloseableScope, Scope

# --- the backing store: JSON values by string key -----------------------------------


type BackingEntry = tuple[str, object, Seconds | None]
"""A key, its JSON value and how long to keep it (``None``: forever)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BackingPersistenceStore:
    """One store of a backend: JSON values by key, each with an optional
    time to live. ``get_many`` gets at least one key and answers each, in
    order."""

    get: Callable[[str], Effect[object | None, PersistenceError]]
    get_many: Callable[[Sequence[str]], Effect[list[object | None], PersistenceError]]
    set: Callable[[str, object, Seconds | None], Effect[None, PersistenceError]]
    set_many: Callable[[Sequence[BackingEntry]], Effect[None, PersistenceError]]
    remove: Callable[[str], Effect[None, PersistenceError]]
    clear: Effect[None, PersistenceError]

    def __post_init__(self) -> None:
        require_effect(self.clear, "clear")


@dataclass(frozen=True, slots=True)
class BackingPersistenceService:
    """A backend: ``make(store_id)`` opens one of its stores, kept apart
    from the others."""

    make: Callable[[str], Effect[BackingPersistenceStore, Never, Scope]]


class BackingPersistence(
    Tag[BackingPersistenceService], key="effect/persistence/BackingPersistence"
):
    """Where ``Persistence`` keeps what it stores."""


# --- the typed store: request outcomes by primary key --------------------------------


class PersistenceStore(Protocol):
    """Request outcomes by the request's primary key, written by the
    request's schemas. ``get`` gives ``None`` for an outcome never stored
    (or expired) and fails with ``SchemaError`` for one the schemas no
    longer read; ``get_many`` gives ``None`` for those and removes them."""

    def get[A, E, R](
        self, key: Persistable[A, E, R]
    ) -> Effect[Exit[A, E] | None, PersistenceError | SchemaError, R]: ...

    def get_many[A, E, R](
        self, keys: Iterable[Persistable[A, E, R]]
    ) -> Effect[list[Exit[A, E] | None], PersistenceError | SchemaError, R]: ...

    def set[A, E, R](
        self, key: Persistable[A, E, R], value: Exit[A, E]
    ) -> Effect[None, PersistenceError | SchemaError, R]: ...

    def set_many[A, E, R](
        self, entries: Iterable[tuple[Persistable[A, E, R], Exit[A, E]]]
    ) -> Effect[None, PersistenceError | SchemaError, R]: ...

    def remove(self, key: AnyPersistable) -> Effect[None, PersistenceError]: ...

    @property
    def clear(self) -> Effect[None, PersistenceError]: ...


class PersistenceService(Protocol):
    def make(
        self,
        *,
        store_id: str,
        time_to_live: TimeToLive[Any, Any, Any] | None = None,
    ) -> Effect[PersistenceStore, Never, Scope]:
        """Open the store ``store_id``. ``time_to_live`` says how long each
        outcome is kept (default: forever); one of zero or less is not
        written."""
        ...


class Persistence(Tag[PersistenceService], key="effect/persistence/Persistence"):
    """Stores request outcomes outside the process."""


class _Store:
    __slots__ = ("_scope", "_storage", "_time_to_live")

    def __init__(
        self,
        storage: BackingPersistenceStore,
        time_to_live: TimeToLive[Any, Any, Any] | None,
        scope: CloseableScope,
    ) -> None:
        self._storage = storage
        self._time_to_live = time_to_live
        self._scope = scope

    def _ttl(self, value: Exit[Any, Any], key: AnyPersistable) -> Seconds:
        if self._time_to_live is None:
            return _FOREVER
        return to_seconds(self._time_to_live(value, key))

    def get[A, E, R](
        self, key: Persistable[A, E, R]
    ) -> Effect[Exit[A, E] | None, PersistenceError | SchemaError, R]:
        def decoded(found: object | None) -> Effect[Exit[A, E] | None, SchemaError, R]:
            return succeed(None) if found is None else deserialize_exit(key, found)

        return self._storage.get(key.primary_key()).flat_map(decoded)

    def get_many[A, E, R](
        self, keys: Iterable[Persistable[A, E, R]]
    ) -> Effect[list[Exit[A, E] | None], PersistenceError | SchemaError, R]:
        requests = list(keys)
        primary_keys = [key.primary_key() for key in requests]
        storage = self._storage
        scope = self._scope

        def body() -> Generator[Effect[Any, Any, R], Any, list[Exit[A, E] | None]]:
            if not primary_keys:
                return []
            results = yield from storage.get_many(primary_keys)
            if len(results) != len(primary_keys):
                return (
                    yield from fail(
                        PersistenceError(
                            message=f"Expected {len(primary_keys)} results but got "
                            f"{len(results)} from backing store"
                        )
                    )
                )
            out: list[Exit[A, E] | None] = []
            for request, primary_key, result in zip(requests, primary_keys, results, strict=True):
                if result is None:
                    out.append(None)
                    continue
                decoded = yield from deserialize_exit(request, result).exit()
                if isinstance(decoded, Failure):
                    out.append(None)
                    yield from storage.remove(primary_key).fork_in(scope)
                    continue
                out.append(decoded.value)
            return out

        return gen(body)

    def set[A, E, R](
        self, key: Persistable[A, E, R], value: Exit[A, E]
    ) -> Effect[None, PersistenceError | SchemaError, R]:
        storage = self._storage

        def write() -> Effect[None, PersistenceError | SchemaError, R]:
            ttl = self._ttl(value, key)
            if ttl <= 0:
                return void
            return serialize_exit(key, value).flat_map(
                lambda encoded: storage.set(key.primary_key(), encoded, _finite(ttl))
            )

        return suspend(write)

    def set_many[A, E, R](
        self, entries: Iterable[tuple[Persistable[A, E, R], Exit[A, E]]]
    ) -> Effect[None, PersistenceError | SchemaError, R]:
        pairs = list(entries)
        storage = self._storage

        def body() -> Generator[Effect[Any, Any, R], Any]:
            encoded: list[BackingEntry] = []
            for key, value in pairs:
                ttl = self._ttl(value, key)
                if ttl <= 0:
                    continue
                json_value = yield from serialize_exit(key, value)
                encoded.append((key.primary_key(), json_value, _finite(ttl)))
            if encoded:
                yield from storage.set_many(encoded)

        return gen(body)

    def remove(self, key: AnyPersistable) -> Effect[None, PersistenceError]:
        return self._storage.remove(key.primary_key())

    @property
    def clear(self) -> Effect[None, PersistenceError]:
        return self._storage.clear


_FOREVER: Final = Seconds(math.inf)


def _finite(ttl: Seconds) -> Seconds | None:
    return None if math.isinf(ttl) else ttl


class _Persistence:
    __slots__ = ("_backing", "_scope")

    def __init__(self, backing: BackingPersistenceService, scope: CloseableScope) -> None:
        self._backing = backing
        self._scope = scope

    def make(
        self,
        *,
        store_id: str,
        time_to_live: TimeToLive[Any, Any, Any] | None = None,
    ) -> Effect[PersistenceStore, Never, Scope]:
        scope = self._scope
        return self._backing.make(store_id).map(
            lambda storage: _Store(storage, time_to_live, scope)
        )


def _build() -> Generator[Effect[Any, Never, Any], Any, PersistenceService]:
    backing = yield from BackingPersistence()
    scope = yield from Scope()
    return _Persistence(backing, scope)


layer: Layer[Persistence, Never, BackingPersistence] = layer_effect(Persistence, gen(_build))
"""``Persistence`` writing through the ``BackingPersistence``."""


# --- helpers for backends -----------------------------------------------------------


def unsafe_ttl_to_expires(clock: ClockService, ttl: Seconds | None) -> int | None:
    """When an entry written now with ``ttl`` expires, in epoch
    milliseconds (``None``: never)."""
    if ttl is None:
        return None
    return clock.now_nanos_unsafe() // 1_000_000 + math.ceil(to_millis(ttl))


def now_millis(clock: ClockService) -> int:
    return clock.now_nanos_unsafe() // 1_000_000


def to_json(value: object) -> str:
    """``JSON.stringify``: compact, non-ASCII kept."""
    return _json_text.stringify(value)
