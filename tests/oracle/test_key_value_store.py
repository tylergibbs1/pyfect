"""Ports of Effect's ``test/persistence/KeyValueStore.test.ts``.

Each test's docstring is the Effect test title. A missing value is
``None`` (Effect: ``undefined``); ``Option`` is ``Some`` / ``None``.
``Schema.Class`` is ``S.Class``, ``Schema.Struct({ a: Schema.Date })`` a
``TypedDict`` with ``S.DateTimeUtc`` (an aware ``datetime``), and the
``afterEach`` clear runs at the start of each test, whose store is fresh
anyway (``layer_memory`` builds a new one per run).
"""

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.option import Some
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence import persistence

type Body = Callable[[], Generator[Any, Any]]


def _run(body: Body) -> None:
    testing.run_test(fx.scoped(fx.gen(body).pipe(fx.provide(kvs.layer_memory))))


# --- KeyValueStore / layerMemory / store operations -----------------------------------


def test_set() -> None:
    """set"""

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("/foo/bar", "bar")
        assert (yield from kv.get("/foo/bar")) == "bar"
        assert (yield from kv.size) == 1

    _run(body)


def test_get_missing() -> None:
    """get/ missing"""

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.clear
        assert (yield from kv.get("foo")) is None

    _run(body)


def test_remove() -> None:
    """remove"""

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("foo", "bar")
        yield from kv.remove("foo")
        assert (yield from kv.get("foo")) is None
        assert (yield from kv.size) == 0

    _run(body)


def test_clear() -> None:
    """clear"""

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("foo", "bar")
        yield from kv.clear
        assert (yield from kv.get("foo")) is None
        assert (yield from kv.size) == 0

    _run(body)


def test_modify() -> None:
    """modify"""

    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("foo", "bar")
        assert (yield from kv.modify("foo", lambda v: v + "bar")) == "barbar"
        assert (yield from kv.size) == 1

    _run(body)


def test_modify_none() -> None:
    """modify - none"""

    def body():
        kv = yield from kvs.KeyValueStore()
        assert (yield from kv.modify("foo", lambda v: v + "bar")) is None
        assert (yield from kv.size) == 0

    _run(body)


def test_set_many_stores_entries_without_a_ttl() -> None:
    """setMany stores entries without a TTL"""

    def body():
        backing = yield from persistence.BackingPersistence()
        store = yield from backing.make("store")
        yield from store.set_many([("key", {"value": 1}, None)])
        assert (yield from store.get("key")) == {"value": 1}

    program = fx.gen(body).pipe(fx.provide(persistence.layer_backing_kvs))
    testing.run_test(fx.scoped(program).pipe(fx.provide(kvs.layer_memory)).or_die())


# --- KeyValueStore / prefix ------------------------------------------------------------


@testing.effect
def test_prefixes_the_keys():
    """prefixes the keys"""

    def body():
        store = yield from kvs.KeyValueStore()
        prefixed = store.prefix("prefix/")
        yield from prefixed.set("foo", "bar")
        yield from prefixed.modify("foo", lambda v: v + "bar")
        assert (yield from prefixed.get("foo")) == "barbar"
        assert (yield from prefixed.has("foo"))
        assert (yield from store.get("prefix/foo")) == "barbar"
        assert (yield from store.has("prefix/foo"))

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_memory))


# --- toSchemaStore ---------------------------------------------------------------------


class User(S.Class):
    name: str
    age: float


@testing.effect
def test_encodes_and_decodes():
    """encodes & decodes"""

    def body():
        store = yield from kvs.KeyValueStore()
        schema_store = store.to_schema_store(User)
        yield from schema_store.set("foo", User(name="foo", age=42))
        yield from schema_store.modify("foo", lambda user: User(name=user.name, age=43))
        value = yield from schema_store.get("foo")
        assert isinstance(value, Some)
        assert value.value.name == "foo"
        assert value.value.age == 43

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_memory))


@testing.effect
def test_prefix():
    """prefix"""

    def body():
        store = yield from kvs.KeyValueStore()
        schema_store = store.to_schema_store(User)
        yield from schema_store.set("prefix/foo", User(name="foo", age=42))
        value = yield from schema_store.get("prefix/foo")
        assert value == Some(User(name="foo", age=42))

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_memory))


class _WithDate(TypedDict):
    a: datetime


_WITH_DATE = S.Struct(_WithDate, a=S.DateTimeUtc)


@testing.effect
def test_json_compliant():
    """json compliant"""

    def body():
        store = yield from kvs.KeyValueStore()
        schema_store = store.to_schema_store(_WITH_DATE)
        epoch = datetime.fromtimestamp(0, UTC)
        yield from schema_store.set("foo", {"a": epoch})
        value = yield from schema_store.get("foo")
        assert value == Some({"a": epoch})

    yield from fx.gen(body).pipe(fx.provide(kvs.layer_memory))
