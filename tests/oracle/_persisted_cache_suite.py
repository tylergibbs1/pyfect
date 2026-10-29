"""Effect's ``test/persistence/PersistedCacheTest.ts``: the suite each
``Persistence`` backend runs (its ``suite(storeId, layer)``), as bodies
for the test modules to run on their backends.

Requests are frozen dataclasses on ``persistable.Class``; ``Schema.Class``
is ``S.Class``, ``Schema.Struct`` a ``TypedDict``. Durations are seconds
(Effect's ``5000`` milliseconds is ``5``).
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Literal, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.persistence import persistable, persisted_cache
from pyfect.persistence.persistence import Persistence


class User(S.Class):
    id: int
    name: str


@dataclass(frozen=True)
class TTLRequest(persistable.Class(success=User, error=S.String)):
    id: int

    def primary_key(self) -> str:
        return f"TTLRequest:{self.id}"


@dataclass(frozen=True)
class _Lookup:
    value: str


class LookupService(fx.Tag[_Lookup]): ...


type Body = Callable[[], Generator[Any, Any]]


def run(layer: fx.Layer[Persistence, Any, Any], body: Body) -> None:
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)))


def smoke_test():
    persistence = yield from Persistence()
    store = yield from persistence.make(store_id="users")
    invocations = 0

    def lookup(req: TTLRequest) -> fx.Effect[User]:
        def make() -> User:
            nonlocal invocations
            invocations += 1
            return User(id=req.id, name="John")

        return fx.sync(make)

    cache = yield from persisted_cache.make(
        lookup, store_id="users", time_to_live=lambda _exit, _req: 5
    )
    assert (yield from cache.get(TTLRequest(1))) == User(id=1, name="John")
    assert (yield from store.get(TTLRequest(1))) == fx.exit.succeed(User(id=1, name="John"))
    assert invocations == 1
    assert (yield from cache.get(TTLRequest(1))) == User(id=1, name="John")
    assert invocations == 1

    cache = yield from persisted_cache.make(
        lookup, store_id="users", time_to_live=lambda _exit, _req: 5
    )
    assert (yield from cache.get(TTLRequest(1))) == User(id=1, name="John")
    assert invocations == 1

    yield from store.set_many(
        [
            (TTLRequest(1), fx.exit.fail("Not found")),
            (TTLRequest(2), fx.exit.succeed(User(id=2, name="Jane"))),
        ]
    )
    results = yield from store.get_many([TTLRequest(1), TTLRequest(2)])
    assert results == [fx.exit.fail("Not found"), fx.exit.succeed(User(id=2, name="Jane"))]


class _OldUser(TypedDict):
    name: str


class _OldError(TypedDict):
    message: str


class _NewUser(TypedDict):
    name: str
    age: float


class _NewError(TypedDict):
    message: str
    code: float


@dataclass(frozen=True)
class _OldRequest(persistable.Class(success=S.Struct(_OldUser), error=S.Struct(_OldError))):
    id: int

    def primary_key(self) -> str:
        return f"GetUser:{self.id}"


@dataclass(frozen=True)
class _Request(persistable.Class(success=S.Struct(_NewUser), error=S.Struct(_NewError))):
    id: int

    def primary_key(self) -> str:
        return f"GetUser:{self.id}"


def _one_day(_exit: object, _req: object) -> float:
    return 86400


def recomputes_stale(store_id: str, outcome: Literal["success", "error"]) -> Body:
    def body():
        options: dict[str, Any] = {
            "store_id": f"{store_id}-stale-{outcome}",
            "time_to_live": _one_day,
        }
        store = yield from (yield from Persistence()).make(**options)
        old: fx.Exit[_OldUser, _OldError] = (
            fx.exit.succeed(_OldUser(name="John"))
            if outcome == "success"
            else fx.exit.fail(_OldError(message="Not found"))
        )
        yield from store.set(_OldRequest(1), old)

        request = _Request(1)

        def lookup(_req: _Request) -> fx.Effect[_NewUser]:
            return fx.succeed(_NewUser(name="John", age=42))

        def must_not_run(_req: _Request) -> fx.Effect[_NewUser]:
            return fx.die(AssertionError("The persisted replacement should be reused"))

        cache = yield from persisted_cache.make(lookup, **options)
        assert (yield from cache.get(request)) == {"name": "John", "age": 42}

        fresh = yield from persisted_cache.make(must_not_run, **options)
        assert (yield from fresh.get(request)) == {"name": "John", "age": 42}

    return body


def require_services_at_lookup(store_id: str) -> Body:
    def body():
        def lookup(req: TTLRequest) -> fx.Effect[User, Never, LookupService]:
            return LookupService().map(lambda service: User(id=req.id, name=service.value))

        cache = yield from persisted_cache.make(
            lookup,
            store_id=f"{store_id}-require-services-at",
            time_to_live=lambda _exit, _req: 5,
            require_services_at="lookup",
        )

        def get(id: int, value: str) -> fx.Effect[User, Any]:
            return cache.get(TTLRequest(id)).pipe(fx.provide_service(LookupService, _Lookup(value)))

        assert (yield from get(1, "first")) == User(id=1, name="first")
        assert (yield from get(2, "second")) == User(id=2, name="second")
        assert (yield from get(1, "third")) == User(id=1, name="first")

    return body
