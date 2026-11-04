"""Ports of Effect's ``sql-mysql2/test/Model.integration.test.ts`` on the
session's MySQL container (``_mysql.mysql_server``; skipped without
Docker): ``SqlModel.makeRepository`` / ``makeResolvers`` on MySQL's path,
the statement followed by a ``SELECT ... LAST_INSERT_ID()``. The same
titles run on SQLite's ``RETURNING *`` path in ``test_sql_model``, whose
models these reuse. Each test's docstring is the Effect test title.

Adapted: each title's table is dropped first, since the server is shared by
every test of the session; ``deletedAt`` is ``deleted_at``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect import case, testing
from pyfect.errors import NoSuchElementException
from pyfect.sql import SqlClient, SqlClientService, mysql
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R

from ._mysql import MysqlServer, query_now
from .test_sql_model import SoftDeleteUser, User

type Body = Callable[[], Generator[Any, Any, Any]]


def _run(server: MysqlServer, body: Body, *, transforms: bool = False) -> None:
    config = mysql.MysqlClientConfig(
        url=server.url,
        transform_query_names=case.camel_to_snake if transforms else None,
        transform_result_names=case.snake_to_camel if transforms else None,
    )
    program = fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config))).or_die()
    testing.run_test(testing.with_live(program))


def _create_users(table: str) -> fx.Effect[None, Any, SqlClient]:
    query_now(f"DROP TABLE IF EXISTS {table}")

    def body():
        sql = yield from SqlClient()
        yield from sql(
            "CREATE TABLE {} (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255), age INT)",
            sql.identifier(table),
        )

    return fx.gen(body)


def _create_soft_delete(table: str) -> fx.Effect[SqlClientService, Any, SqlClient]:
    query_now(f"DROP TABLE IF EXISTS {table}")

    def body():
        sql = yield from SqlClient()
        yield from sql(
            "CREATE TABLE {} (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(255), "
            "deleted_at VARCHAR(255) NULL)",
            sql.identifier(table),
        )
        return sql

    return fx.gen(body)


def _users(table: str):
    return sql_model.make_repository(
        User, table_name=table, id_column="id", span_prefix="UserRepository"
    )


def _resolvers(table: str):
    return sql_model.make_resolvers(
        User, table_name=table, id_column="id", span_prefix="UserRepository"
    )


def _insert_body(table: str) -> Body:
    def body():
        repo = yield from _users(table)
        yield from _create_users(table)
        result = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        assert result == User(id=1, name="Alice", age=30)

    return body


def test_insert_returns_result(mysql_server: MysqlServer):
    """SqlModel / insert returns result"""
    _run(mysql_server, _insert_body("users_insert"))


def test_insert_returns_result_with_transforms(mysql_server: MysqlServer):
    """SqlModel / insert returns result with transforms"""
    _run(mysql_server, _insert_body("users_insert_transforms"), transforms=True)


def test_insert_void(mysql_server: MysqlServer):
    """SqlModel / insertVoid"""

    def body():
        repo = yield from _users("users_insert_void")
        yield from _create_users("users_insert_void")
        result = yield from repo.insert_void(User.insert.make({"name": "Alice", "age": 30}))
        assert result is None

    _run(mysql_server, body)


def test_insert_data_loader_returns_result(mysql_server: MysqlServer):
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

    _run(mysql_server, body)


def test_find_by_id_data_loader(mysql_server: MysqlServer):
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

    _run(mysql_server, body)


def test_find_by_id_ignores_soft_deleted_rows(mysql_server: MysqlServer):
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

    _run(mysql_server, body)


def test_find_by_id_data_loader_ignores_soft_deleted_rows(mysql_server: MysqlServer):
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

    _run(mysql_server, body)


def _update_body(table: str) -> Body:
    def body():
        repo = yield from _users(table)
        yield from _create_users(table)
        result = yield from repo.insert(User.insert.make({"name": "Alice", "age": 30}))
        update = User.update.make({"id": result.id, "name": "Bob", "age": result.age})
        result = yield from repo.update(update)
        assert result == User(id=1, name="Bob", age=30)

    return body


def test_update_returns_result(mysql_server: MysqlServer):
    """SqlModel / update returns result"""
    _run(mysql_server, _update_body("users_update"))


def test_update_returns_result_with_transforms(mysql_server: MysqlServer):
    """SqlModel / update returns result with transforms"""
    _run(mysql_server, _update_body("users_update_transforms"), transforms=True)
