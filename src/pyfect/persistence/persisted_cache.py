"""A ``Cache`` in front of a persistence store (Effect's
``effect/persistence/PersistedCache``)::

    users = yield from persisted_cache.make(
        lambda req: fetch_user(req.id),
        store_id="users",
        time_to_live=lambda _exit, _req: 3600,
    )
    user = yield from users.get(GetUser(1))

``get`` answers from memory, then from the ``Persistence`` store, then by
running ``lookup`` and storing its outcome, failures and defects too. A
stored outcome the request's schemas no longer read is looked up again
and replaced.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal, Never, Protocol, cast, overload

from pyfect._catch import catch_tag
from pyfect._core import Effect
from pyfect.batching._request import TypedRequest
from pyfect.cache import Cache, RequireServicesAt
from pyfect.duration import Input as DurationInput
from pyfect.effect import from_exit, gen, succeed, suspend
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.persistable import AnyPersistable, HasPersistableTypes, TimeToLive
from pyfect.persistence.persistence import Persistence, PersistenceStore
from pyfect.schema import SchemaError
from pyfect.scope import Scope

_IN_MEMORY_TTL: DurationInput = "10 seconds"
_IN_MEMORY_CAPACITY = 1024


class _LookupTypes[K_co, A_co, E_co](Protocol):
    def _lookup_types(self) -> tuple[K_co, A_co, E_co]: ...


class PersistedCache[K: AnyPersistable, R = Never, A = Any, E = Any]:
    """Make one with ``make``. ``get``'s success and error come from the
    request's schemas; ``R`` is what the lookup needs when
    ``require_services_at="lookup"``; ``A`` and ``E`` are what the lookup
    gives, which must fit the request's schemas (``get`` is a pyright
    error otherwise)."""

    __slots__ = ("_in_memory", "_store")

    def __init__(self, in_memory: Cache[K, Any, Any, Any], store: PersistenceStore) -> None:
        self._in_memory = in_memory
        self._store = store

    def _lookup_types(self) -> tuple[K, A, E]:
        """Never called: ties the lookup's success and error to the
        request's for ``get``."""
        raise NotImplementedError

    @property
    def in_memory(self) -> Cache[K, Any, Any, Any]:
        """The in-memory cache in front of the store."""
        return self._in_memory

    def get[AA, EE, RR, SA, SE](
        self: _LookupTypes[HasPersistableTypes[SA, SE], SA, SE],
        key: TypedRequest[AA, EE, RR, K],
    ) -> Effect[AA, EE, RR | R]:
        """The outcome for ``key``: from memory, from the store, or looked
        up now and stored."""
        cache = cast("PersistedCache[K, R]", self)
        return cache._in_memory.get(key)  # pyright: ignore[reportArgumentType]

    def invalidate(self, key: K) -> Effect[None, PersistenceError]:
        """Forget ``key`` in the store and in memory."""
        return self._store.remove(key).and_then(self._in_memory.invalidate(key))


@overload
def make[K: AnyPersistable, A, E, R = Never](
    lookup: Callable[[K], Effect[A, E, R]],
    *,
    store_id: str,
    time_to_live: TimeToLive[K, A, E],
    in_memory_capacity: int | None = _IN_MEMORY_CAPACITY,
    in_memory_ttl: TimeToLive[K, A, E | PersistenceError | SchemaError] | None = None,
    require_services_at: Literal["construction"] = "construction",
) -> Effect[PersistedCache[K, Never, A, E], Never, R | Persistence | Scope]: ...
@overload
def make[K: AnyPersistable, A, E, R = Never](
    lookup: Callable[[K], Effect[A, E, R]],
    *,
    store_id: str,
    time_to_live: TimeToLive[K, A, E],
    in_memory_capacity: int | None = _IN_MEMORY_CAPACITY,
    in_memory_ttl: TimeToLive[K, A, E | PersistenceError | SchemaError] | None = None,
    require_services_at: Literal["lookup"],
) -> Effect[PersistedCache[K, R, A, E], Never, Persistence | Scope]: ...
def make(
    lookup: Callable[[Any], Effect[Any, Any, Any]],
    *,
    store_id: str,
    time_to_live: TimeToLive[Any, Any, Any],
    in_memory_capacity: int | None = _IN_MEMORY_CAPACITY,
    in_memory_ttl: TimeToLive[Any, Any, Any] | None = None,
    require_services_at: RequireServicesAt = "construction",
) -> Effect[PersistedCache[Any, Any, Any, Any], Never, Any]:
    """A cache of ``lookup``'s outcomes in the store ``store_id``, kept
    there for ``time_to_live`` and in memory for ``in_memory_ttl``
    (default: 10 seconds), at most ``in_memory_capacity`` of them (default:
    1024). ``lookup`` must give the request's success or fail with its
    error (a pyright error at ``get`` otherwise): the store writes them by
    the request's schemas. ``time_to_live`` sees the lookup's ``Exit``;
    ``in_memory_ttl`` may also see the store's failures."""

    def body() -> Generator[Effect[Any, Any, Any], Any, PersistedCache[Any, Any, Any, Any]]:
        persistence = yield from Persistence()
        store = yield from persistence.make(store_id=store_id, time_to_live=time_to_live)

        def cached_lookup(key: AnyPersistable) -> Effect[Any, Any, Any]:
            def run() -> Generator[Effect[Any, Any, Any], Any, Any]:
                stored = yield from store.get(key).pipe(
                    catch_tag(SchemaError, lambda _: succeed(None))
                )
                if stored is not None:
                    return (yield from from_exit(stored))
                result = yield from suspend(lambda: lookup(key)).exit()
                yield from store.set(key, result)
                return (yield from from_exit(result))

            return gen(run)

        ttl: TimeToLive[Any, Any, Any] = in_memory_ttl or _default_in_memory_ttl
        in_memory: Cache[Any, Any, Any, Any]
        if require_services_at == "lookup":
            in_memory = yield from Cache.make(
                cached_lookup,
                capacity=in_memory_capacity,
                time_to_live=ttl,
                require_services_at="lookup",
            )
        else:
            in_memory = yield from Cache.make(
                cached_lookup, capacity=in_memory_capacity, time_to_live=ttl
            )
        return PersistedCache(in_memory, store)

    return gen(body)


def _default_in_memory_ttl(_exit: object, _key: object) -> DurationInput:
    return _IN_MEMORY_TTL


__all__ = [
    "PersistedCache",
    "PersistenceError",
    "make",
]
