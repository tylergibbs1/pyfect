"""``sql.model`` on the session's SQL Server (``_mssql.mssql_server``;
skipped without Docker). The titles are ``(pyfect)``: Effect's model tests
run on MySQL only. Effect 4.1.2's ``SqlModel`` builds the insert with
``sql.insert(request).returning("*")``, which its mssql compiler writes as
``OUTPUT INSERTED.*`` (checked against SQL Server: the row comes back); its
update appends a literal ``returning *``, which SQL Server refuses, in
Effect too (dogfood ledger #1 and #5)."""

from collections.abc import Callable, Generator
from typing import Any, TypedDict

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.schema import model as Model
from pyfect.sql import SqlClient, mssql
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R
from pyfect.sql.error import SqlSyntaxError

from ._mssql import MssqlServer


class AccountInsert(TypedDict):
    code: str
    name: str


class AccountUpdate(AccountInsert):
    id: int


class Account(Model.Class[AccountInsert, AccountUpdate]):
    id: int = Model.field(Model.field_only(["select", "update", "json"])(S.Int))
    code: str
    name: str


def _on_server(
    server: MssqlServer, table: str, body: Callable[[], fx.Effect[Any, Any, Any]]
) -> fx.Effect[Any, Any]:
    @fx.fn
    def program() -> Generator[Any, Any, Any]:
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(table))
        yield from sql(
            "CREATE TABLE {} (id INT IDENTITY PRIMARY KEY, code NVARCHAR(40), name NVARCHAR(100))",
            sql.identifier(table),
        )
        return (yield from body())

    return fx.scoped(program()).pipe(fx.provide(mssql.layer(server.config())))


def _accounts(table: str):
    return sql_model.make_repository(
        Account, table_name=table, id_column="id", span_prefix="Accounts"
    )


@testing.live
def test_repository_insert_returns_the_row_on_sql_server(mssql_server: MssqlServer):
    """(pyfect) repository insert returns the row on SQL Server"""

    @fx.fn
    def body():
        accounts = yield from _accounts("model_insert")
        first = yield from accounts.insert(Account.insert.make({"code": "cash", "name": "Cash"}))
        second = yield from accounts.insert(Account.insert.make({"code": "bank", "name": "Bank"}))
        return first, second

    first, second = yield from _on_server(mssql_server, "model_insert", body)
    assert first == Account(id=1, code="cash", name="Cash")
    assert second == Account(id=2, code="bank", name="Bank")


@testing.live
def test_resolver_insert_returns_the_rows_on_sql_server(mssql_server: MssqlServer):
    """(pyfect) resolver insert returns the rows on SQL Server"""

    @fx.fn
    def body():
        resolvers = yield from sql_model.make_resolvers(
            Account, table_name="model_resolvers", id_column="id", span_prefix="Accounts"
        )
        insert = R.request(resolvers.insert)
        return (
            yield from fx.all(
                insert(Account.insert.make({"code": "cash", "name": "Cash"})),
                insert(Account.insert.make({"code": "bank", "name": "Bank"})),
                concurrency="unbounded",
            )
        )

    rows = yield from _on_server(mssql_server, "model_resolvers", body)
    assert sorted(row.code for row in rows) == ["bank", "cash"]


@testing.live
def test_repository_update_fails_on_sql_server_as_in_effect(mssql_server: MssqlServer):
    """(pyfect) repository update fails on SQL Server, as in Effect; update_void works"""

    @fx.fn
    def body():
        accounts = yield from _accounts("model_update")
        row = yield from accounts.insert(Account.insert.make({"code": "cash", "name": "Cash"}))
        renamed = Account.update.make({"id": row.id, "code": "cash", "name": "Petty cash"})
        failed = yield from accounts.update(renamed).flip()
        yield from accounts.update_void(renamed)
        return failed, (yield from accounts.find_by_id(row.id))

    failed, found = yield from _on_server(mssql_server, "model_update", body)
    assert isinstance(failed.reason, SqlSyntaxError)
    assert found.name == "Petty cash"
