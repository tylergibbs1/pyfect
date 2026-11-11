"""Every statement ``sql.model``'s repositories and resolvers send, on every
dialect's compiler, is the one Effect 4.1.2's ``SqlModel`` sends.

``fixtures/sql_model_statements.json`` was printed by Effect's
``makeRepository`` / ``makeResolvers`` under Node, each on a client whose
connection records its SQL, with the pg, mysql2, mssql, ClickHouse and
SQLite compilers (libSQL and D1 use SQLite's). Dialect SQL the model wrote by
hand, as its ``returning *`` was (SQL Server takes ``OUTPUT INSERTED.*``,
which only the compiler writes), shows up here as a difference.

Where Effect's own statement fails on a dialect, so does pyfect's: an
update's ``returning *`` on SQL Server and ClickHouse, an insert's
``RETURNING *`` on ClickHouse."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.schema import model as Model
from pyfect.sql import clickhouse, mssql, mysql, pg
from pyfect.sql import client as sql_client
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R
from pyfect.sql import statement as st
from pyfect.sql.client import SqlClientService
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError

EFFECT: dict[str, dict[str, list[str]]] = json.loads(
    (Path(__file__).parent / "oracle" / "fixtures" / "sql_model_statements.json").read_text()
)

COMPILERS: dict[str, Callable[[], st.Compiler]] = {
    "pg": pg.make_compiler,
    "mysql": mysql.make_compiler,
    "sqlite": st.make_compiler_sqlite,
    "mssql": mssql.make_compiler,
    "clickhouse": clickhouse.make_compiler,
}


class AccountInsert(TypedDict):
    code: str
    name: str


class AccountUpdate(AccountInsert):
    id: int


class Account(Model.Class[AccountInsert, AccountUpdate]):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    code: str
    name: str


class SoftInsert(TypedDict):
    code: str


class SoftUpdate(SoftInsert):
    id: int
    deleted_at: str | None


class Soft(Model.Class[SoftInsert, SoftUpdate]):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    code: str
    deleted_at: str | None = Model.field(Model.field_only(["select", "update"])(S.NullOr(S.String)))


_ROW = {"id": 1, "code": "cash", "name": "Cash", "deleted_at": None}


class _Recording:
    """A connection that records each statement and answers with one row."""

    def __init__(self, sent: list[str]) -> None:
        self.sent = sent

    def _run(self, sql: str, rows: object) -> fx.Effect[Any]:
        return fx.sync(lambda: self.sent.append(sql)).as_(rows)

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._run(sql, [_ROW])

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self._run(sql, [_ROW])

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, [])

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, [])

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        # MySQL's statement-and-SELECT: the results of both.
        return self._run(sql, [[], [_ROW]])

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Stream[Row, SqlError]:
        raise NotImplementedError


def _client(dialect: str, sent: list[str]) -> SqlClientService:
    made = sql_client.make(
        driver=dialect, acquirer=fx.succeed(_Recording(sent)), compiler=COMPILERS[dialect]()
    )
    return fx.run_blocking(made.pipe(fx.provide(reactivity.layer)))


def _both[A](effect: Callable[[Any], fx.Effect[A, Any, Any]], a: object, b: object) -> Any:
    return fx.all(effect(a), effect(b), concurrency="unbounded")


def _operations(
    label: str, model: Any, rows: tuple[Any, Any], update: Any, soft: str | None
) -> dict[str, Callable[[], fx.Effect[Any, Any, Any]]]:
    options: dict[str, Any] = {
        "table_name": "accounts" if label == "plain" else "softs",
        "span_prefix": "A",
        "id_column": "id",
        "soft_delete_column": soft,
    }
    one, two = model.insert.make(rows[0]), model.insert.make(rows[1])
    updated = model.update.make(update)

    def repo(call: Callable[[Any], fx.Effect[Any, Any, Any]]) -> Callable[[], Any]:
        return lambda: sql_model.make_repository(model, **options).flat_map(call)

    def resolvers(name: str, a: object, b: object) -> Callable[[], Any]:
        def run(made: Any) -> Any:
            return _both(R.request(getattr(made, name)), a, b)

        return lambda: sql_model.make_resolvers(model, **options).flat_map(run)

    return {
        f"{label}.insert": repo(lambda r: r.insert(one)),
        f"{label}.insertVoid": repo(lambda r: r.insert_void(one)),
        f"{label}.update": repo(lambda r: r.update(updated)),
        f"{label}.updateVoid": repo(lambda r: r.update_void(updated)),
        f"{label}.findById": repo(lambda r: r.find_by_id(1)),
        f"{label}.delete": repo(lambda r: r.delete(1)),
        f"{label}.resolvers.insert": resolvers("insert", one, two),
        f"{label}.resolvers.insertVoid": resolvers("insert_void", one, two),
        f"{label}.resolvers.findById": resolvers("find_by_id", 1, 2),
        f"{label}.resolvers.delete": resolvers("delete", 1, 2),
    }


OPERATIONS = _operations(
    "plain",
    Account,
    ({"code": "cash", "name": "Cash"}, {"code": "bank", "name": "Bank"}),
    {"id": 1, "code": "cash", "name": "Cash"},
    None,
) | _operations(
    "soft",
    Soft,
    ({"code": "cash"}, {"code": "bank"}),
    {"id": 1, "code": "cash", "deleted_at": None},
    "deleted_at",
)


def _clickhouse_types(sql: str) -> str:
    # ClickHouse placeholders carry the value's type: a JavaScript number is
    # Float64 and null a String, where Python's int is Int64 and None Nullable.
    return re.sub(r"\{p(\d+): [^}]+\}", r"{p\1}", sql)


def test_the_cases_cover_every_statement_effect_printed():
    for dialect in COMPILERS:
        assert set(EFFECT[dialect]) == set(OPERATIONS)


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
@pytest.mark.parametrize("dialect", sorted(COMPILERS))
def test_the_model_sends_effects_statements(dialect: str, operation: str):
    sent: list[str] = []
    client = _client(dialect, sent)
    fx.run_blocking_exit(
        OPERATIONS[operation]().pipe(fx.provide_service(sql_client.SqlClient, client))
    )
    expected = EFFECT[dialect][operation]
    if dialect == "clickhouse":
        sent, expected = list(map(_clickhouse_types, sent)), list(map(_clickhouse_types, expected))
    assert sent == expected
