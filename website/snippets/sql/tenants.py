from collections.abc import Sequence
from typing import TypedDict

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.sql import SqlClient, SqlClientService, sqlite
from pyfect.sql import resolver as R


class Account(TypedDict):
    id: int
    owner: str


def tenant_database(owner: str):
    """A tenant's own database, holding its account 1."""

    @fx.fn
    def make():
        sql = yield from sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
        yield from sql("CREATE TABLE accounts (id INTEGER PRIMARY KEY, owner TEXT)")
        yield from sql("INSERT INTO accounts {}", sql.insert({"id": 1, "owner": owner}))
        return sql

    return make()


@fx.fn
def select_from_context(ids: Sequence[int]):
    sql = yield from SqlClient()  # the client of the batch's first request
    return (yield from sql("SELECT * FROM accounts WHERE id IN {}", sql.in_(ids)))


# Unsafe across tenants: one resolver, the client read from each request's context.
shared_account = R.request(
    R.find_by_id(
        id=S.Int,
        result=S.Struct(Account),
        result_id=lambda account, _row: account["id"],
        execute=select_from_context,
    )
)


# Safe: a resolver per tenant, over that tenant's client.
def account_lookup(sql: SqlClientService):
    return R.request(
        R.find_by_id(
            id=S.Int,
            result=S.Struct(Account),
            result_id=lambda account, _row: account["id"],
            execute=lambda ids: sql("SELECT * FROM accounts WHERE id IN {}", sql.in_(ids)),
        )
    )


@fx.fn
def program():
    a = yield from tenant_database("tenant a")
    b = yield from tenant_database("tenant b")

    # Requests made together share a batch, whatever client each provides.
    got = yield from fx.all(
        shared_account(1).pipe(fx.provide_service(SqlClient, a)),
        shared_account(1).pipe(fx.provide_service(SqlClient, b)),
        concurrency="unbounded",
    )
    print("shared:", [account["owner"] for account in got])

    account_of_a, account_of_b = account_lookup(a), account_lookup(b)
    got = yield from fx.all(account_of_a(1), account_of_b(1), concurrency="unbounded")
    print("per tenant:", [account["owner"] for account in got])


fx.run_main(fx.scoped(program()).pipe(fx.provide(reactivity.layer)))
