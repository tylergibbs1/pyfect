from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.schema import model as Model
from pyfect.sql import SqlClient, sqlite
from pyfect.sql import model as sql_model
from pyfect.sql import resolver as R


class AccountInsert(TypedDict):
    code: str


class AccountUpdate(AccountInsert):
    id: int


class Account(Model.Class[AccountInsert, AccountUpdate]):
    id: int = Model.field(Model.field_only(["select", "update", "json"])(S.Int))
    code: str


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE accounts (id INTEGER PRIMARY KEY, code TEXT)")
    resolvers = yield from sql_model.make_resolvers(
        Account, table_name="accounts", id_column="id", span_prefix="Accounts"
    )
    # R.request turns a resolver into a function from one request to its effect.
    insert = R.request(resolvers.insert)
    find = R.request(resolvers.find_by_id)

    # Requests made together run as one INSERT ... RETURNING *, each getting its row.
    codes = ["cash", "bank", "sales"]
    created = yield from fx.all(
        *(insert(Account.insert.make({"code": c})) for c in codes), concurrency="unbounded"
    )
    print([(account.id, account.code) for account in created])

    # And as one SELECT ... WHERE id IN (...); an id with no row fails its request alone.
    found = yield from fx.all(find(3), find(1), concurrency="unbounded")
    print([account.code for account in found])
    print(type((yield from find(9).flip())).__name__)


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
