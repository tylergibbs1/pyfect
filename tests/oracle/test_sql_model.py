"""Ports of Effect's ``sql-mysql2/test/Model.integration.test.ts``
(``SqlModel.makeRepository`` / ``makeResolvers``), run on SQLite: pyfect
has no MySQL driver, and these titles test the repository, not MySQL.
SQLite takes the ``INSERT ... RETURNING *`` path that every dialect but
MySQL takes. Each test's docstring is the Effect test title.

Python mappings: ``Model.Class<User>("User")({...})`` is ``class
User(Model.Class[UserInsert, UserUpdate])``, the TypedDicts typing the
insert and update variants; ``deletedAt`` is ``deleted_at``; ``{ ...result,
name: "Bob" }`` spells the update's keys out. "with transforms" uses the
SQLite client's ``transform_query_names`` / ``transform_result_names``.
"""

from collections.abc import Callable, Generator
from datetime import datetime
from typing import Any, NotRequired, TypedDict

import pyfect as fx
from pyfect import case, testing
from pyfect import schema as S
from pyfect.errors import NoSuchElementException
from pyfect.schema import model as Model
from pyfect.sql import SqlClient, SqlClientService
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

from ._sqlite import make_memory_client


class UserInsert(TypedDict):
    name: str
    age: int


class UserUpdate(TypedDict):
    id: int
    name: str
    age: int


class User(Model.Class[UserInsert, UserUpdate]):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    name: str
    age: int


class SoftDeleteInsert(TypedDict):
    name: str


class SoftDeleteUpdate(TypedDict):
    id: int
    name: str
    deleted_at: str | None


class SoftDeleteUser(Model.Class[SoftDeleteInsert, SoftDeleteUpdate]):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    name: str
    deleted_at: str | None = Model.field(Model.field_only(["select", "update"])(S.NullOr(S.String)))


type Body = Callable[[], Generator[Any, Any, Any]]


def _with_client(body: Body, *, transforms: bool = False) -> fx.Effect[Any, Any, fx.Scope]:
    config: dict[str, Any] = (
        {
            "transform_query_names": case.camel_to_snake,
            "transform_result_names": case.snake_to_camel,
        }
        if transforms
        else {}
    )
    return make_memory_client(**config).flat_map(
        lambda sql: fx.gen(body).pipe(fx.provide_service(SqlClient, sql))
    )


def _users(table: str):
    return sql_model.make_repository(
        User, table_name=table, id_column="id", span_prefix="UserRepository"
    )


def _create_users(table: str) -> fx.Effect[None, Any, SqlClient]:
    def body():
        sql = yield from SqlClient()
        yield from sql(
            "CREATE TABLE {} (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER)",
            sql.identifier(table),
        )

    return fx.gen(body)


@testing.effect
def test_insert_returns_result():
    """SqlModel / insert returns result"""

    def body():
        repo = yield from _users("users_insert")
        yield from _create_users("users_insert")
        result = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        assert result == User(id=1, name="Alice", age=30)

    yield from _with_client(body)


@testing.effect
def test_insert_returns_result_with_transforms():
    """SqlModel / insert returns result with transforms"""

    def body():
        repo = yield from _users("users_insert_transforms")
        yield from _create_users("users_insert_transforms")
        result = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        assert result == User(id=1, name="Alice", age=30)

    yield from _with_client(body, transforms=True)


@testing.effect
def test_insert_void():
    """SqlModel / insertVoid"""

    def body():
        repo = yield from _users("users_insert_void")
        yield from _create_users("users_insert_void")
        result = yield from repo.insert_void(User.insert.make({"name": "Alice", "age": 30}))
        assert result is None

    yield from _with_client(body)


def _resolvers(table: str):
    return sql_model.make_resolvers(
        User, table_name=table, id_column="id", span_prefix="UserRepository"
    )


@testing.effect
def test_insert_data_loader_returns_result():
    """SqlModel / insert data loader returns result"""

    def body():
        repo = yield from _resolvers("users_insert_loader")
        yield from _create_users("users_insert_loader")
        alice, john = yield from fx.all(
            R.request(User.insert.make({"name": "Alice", "age": 30}), repo.insert),
            R.request(User.insert.make({"name": "John", "age": 30}), repo.insert),
            concurrency="unbounded",
        )
        assert alice.name == "Alice"
        assert john.name == "John"

    yield from _with_client(body)


@testing.effect
def test_find_by_id_data_loader():
    """SqlModel / findById data loader"""

    def body():
        repo = yield from _resolvers("users_find_loader")
        yield from _create_users("users_find_loader")
        alice = yield from R.request(User.insert.make({"name": "Alice", "age": 30}), repo.insert)
        john = yield from R.request(User.insert.make({"name": "John", "age": 30}), repo.insert)
        alice2, john2 = yield from fx.all(
            R.request(alice.id, repo.find_by_id),
            R.request(john.id, repo.find_by_id),
            concurrency="unbounded",
        )
        assert alice2.name == "Alice"
        assert john2.name == "John"

    yield from _with_client(body)


def _create_soft_delete(table: str) -> fx.Effect[SqlClientService, Any, SqlClient]:
    def body():
        sql = yield from SqlClient()
        yield from sql(
            "CREATE TABLE {} (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, deleted_at TEXT NULL)",  # noqa: E501
            sql.identifier(table),
        )
        return sql

    return fx.gen(body)


@testing.effect
def test_find_by_id_ignores_soft_deleted_rows():
    """SqlModel / findById ignores soft deleted rows"""

    def body():
        repo = yield from sql_model.make_repository(
            SoftDeleteUser,
            table_name="soft_delete_users",
            id_column="id",
            span_prefix="SoftDeleteUserRepository",
            soft_delete_column="deleted_at",
        )
        sql = yield from _create_soft_delete("soft_delete_users")
        alice = yield from repo.insert(SoftDeleteUser.insert.make({"name": "Alice"}))
        bob = yield from repo.insert(SoftDeleteUser.insert.make({"name": "Bob"}))
        yield from sql(
            "UPDATE soft_delete_users SET deleted_at = CURRENT_TIMESTAMP WHERE id = {}", bob.id
        )

        alice_result = yield from repo.find_by_id(alice.id)
        assert alice_result == SoftDeleteUser(id=alice.id, name="Alice", deleted_at=None)

        error = yield from repo.find_by_id(bob.id).flip()
        assert isinstance(error, NoSuchElementException)

        yield from repo.delete(alice.id)
        rows = yield from sql("SELECT deleted_at FROM soft_delete_users WHERE id = {}", alice.id)
        assert len(rows) == 1
        assert rows[0]["deleted_at"] is not None

        deleted_error = yield from repo.find_by_id(alice.id).flip()
        assert isinstance(deleted_error, NoSuchElementException)

    yield from _with_client(body)


@testing.effect
def test_find_by_id_data_loader_ignores_soft_deleted_rows():
    """SqlModel / findById data loader ignores soft deleted rows"""

    def body():
        repo = yield from sql_model.make_resolvers(
            SoftDeleteUser,
            table_name="soft_delete_user_resolvers",
            id_column="id",
            span_prefix="SoftDeleteUserRepository",
            soft_delete_column="deleted_at",
        )
        sql = yield from _create_soft_delete("soft_delete_user_resolvers")
        alice = yield from R.request(SoftDeleteUser.insert.make({"name": "Alice"}), repo.insert)
        bob = yield from R.request(SoftDeleteUser.insert.make({"name": "Bob"}), repo.insert)
        yield from sql(
            "UPDATE soft_delete_user_resolvers SET deleted_at = CURRENT_TIMESTAMP WHERE id = {}",
            bob.id,
        )

        alice_result = yield from R.request(alice.id, repo.find_by_id)
        assert alice_result == SoftDeleteUser(id=alice.id, name="Alice", deleted_at=None)

        error = yield from R.request(bob.id, repo.find_by_id).flip()
        assert isinstance(error, NoSuchElementException)

        yield from R.request(alice.id, repo.delete)
        rows = yield from sql(
            "SELECT deleted_at FROM soft_delete_user_resolvers WHERE id = {}", alice.id
        )
        assert len(rows) == 1
        assert rows[0]["deleted_at"] is not None

        deleted_error = yield from R.request(alice.id, repo.find_by_id).flip()
        assert isinstance(deleted_error, NoSuchElementException)

    yield from _with_client(body)


def _update_body(table: str) -> Body:
    def body():
        repo = yield from _users(table)
        yield from _create_users(table)
        result = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        update = User.update.make({"id": result.id, "name": "Bob", "age": result.age})
        result = yield from repo.update(update)
        assert result == User(id=1, name="Bob", age=30)

    return body


@testing.effect
def test_update_returns_result():
    """SqlModel / update returns result"""
    yield from _with_client(_update_body("users_update"))


@testing.effect
def test_update_returns_result_with_transforms():
    """SqlModel / update returns result with transforms"""
    yield from _with_client(_update_body("users_update_transforms"), transforms=True)


# --- pyfect: the variants' TypedDicts are checked against the fields ----------


def test_a_variant_typed_dict_must_have_the_variant_keys():
    """(pyfect) a TypedDict given for a variant must have its keys"""

    class WrongInsert(TypedDict):
        id: int
        name: str

    try:

        class Wrong(Model.Class[WrongInsert]):  # pyright: ignore[reportUnusedClass]
            id: int = Model.field(Model.GeneratedByDb(S.Int))
            name: str

    except TypeError as error:
        assert "unknown key 'id'" in str(error)
    else:
        raise AssertionError("expected TypeError")


def test_only_defaulted_keys_may_be_not_required():
    """(pyfect) only keys with a constructor default may be NotRequired"""

    class LooseInsert(TypedDict):
        name: NotRequired[str]

    try:

        class Loose(Model.Class[LooseInsert]):  # pyright: ignore[reportUnusedClass]
            name: str

    except TypeError as error:
        assert "'name' is NotRequired" in str(error)
    else:
        raise AssertionError("expected TypeError")

    class StampedInsert(TypedDict):
        created_at: NotRequired[datetime]

    class Stamped(Model.Class[StampedInsert]):
        created_at: datetime = Model.field(Model.DateTimeInsert)

    assert list(Stamped.insert.fields) == ["created_at"]


@testing.effect
def test_insert_and_update_without_a_returned_row_die():
    """(pyfect) an update matching no row (missing or soft-deleted) is a defect, as in Effect"""

    def body():
        repo = yield from sql_model.make_repository(
            SoftDeleteUser,
            table_name="soft_deleted",
            id_column="id",
            span_prefix="SoftDeleteUserRepository",
            soft_delete_column="deleted_at",
        )
        yield from _create_soft_delete("soft_deleted")
        alice = yield from repo.insert(SoftDeleteUser.insert.make({"name": "Alice"}))
        missing = SoftDeleteUser.update.make({"id": 99, "name": "Nobody", "deleted_at": None})
        exit_ = yield from repo.update(missing).exit()
        assert isinstance(exit_, fx.Failure)
        assert isinstance(exit_.cause.find_defect(), NoSuchElementException)

        yield from repo.delete(alice.id)
        update = SoftDeleteUser.update.make({"id": alice.id, "name": "Al", "deleted_at": None})
        exit_ = yield from repo.update(update).exit()
        assert isinstance(exit_, fx.Failure)
        assert isinstance(exit_.cause.find_defect(), NoSuchElementException)

    yield from _with_client(body)


@testing.effect
def test_repository_operations_run_in_spans_named_by_the_prefix():
    """(pyfect) each repository operation runs in a ``<span_prefix>.<operation>`` span"""
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    def body():
        repo = yield from _users("users_spans")
        yield from _create_users("users_spans")
        user = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        yield from repo.insert_void(User.insert.make({"name": "John", "age": 31}))
        update = User.update.make({"id": user.id, "name": "Bob", "age": 30})
        yield from repo.update(update)
        yield from repo.update_void(update)
        yield from repo.find_by_id(user.id)
        yield from repo.delete(user.id)

    yield from _with_client(body).with_tracer(Tracer(make))
    named = [(s.name, dict(s.attributes)) for s in spans if s.name.startswith("UserRepository.")]
    assert named == [
        ("UserRepository.insert", {}),
        ("UserRepository.insertVoid", {}),
        ("UserRepository.update", {"id": 1}),
        ("UserRepository.updateVoid", {"id": 1}),
        ("UserRepository.findById", {"id": 1}),
        ("UserRepository.delete", {"id": 1}),
    ]
