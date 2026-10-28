from collections.abc import Sequence
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.sql import SqlClient, sqlite
from pyfect.sql import resolver as R


class User(TypedDict):
    id: int
    name: str


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    yield from sql(
        "INSERT INTO users {}", sql.insert([{"name": n} for n in ["Ada", "Linus", "Grace"]])
    )

    def select(ids: Sequence[int]):
        print("query for", list(ids))
        return sql("SELECT * FROM users WHERE id IN {}", sql.in_(ids))

    # One request per id; requests made together run as one query.
    user_by_id = R.request(
        R.find_by_id(
            id=S.Int,
            result=S.Struct(User),
            result_id=lambda user, _row: user["id"],
            execute=select,
        )
    )

    users = yield from fx.all(user_by_id(3), user_by_id(1), user_by_id(3), concurrency="unbounded")
    print(users)

    # An id with no row fails that request alone.
    missing = yield from user_by_id(9).flip()
    print(type(missing).__name__)


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
