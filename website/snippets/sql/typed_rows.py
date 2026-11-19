import pyfect as fx
from pyfect import schema as S
from pyfect.sql import SqlClient, sqlite
from pyfect.sql import schema as sql_schema


class User(S.Class, identifier="User"):
    id: int
    name: str


class NewUser(S.Class, identifier="NewUser"):
    name: str


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")

    # Each function takes the request's schema, the row's schema and the statement, and
    # gives the query as a function of the request: encoded before, rows decoded after.
    insert = sql_schema.void(
        request=NewUser,
        execute=lambda new: sql("INSERT INTO users {}", sql.insert(new)),
    )
    by_id = sql_schema.find_one_option(
        request=S.Int,
        result=User,
        execute=lambda id: sql("SELECT * FROM users WHERE id = {}", id),
    )
    every = sql_schema.find_all(
        request=S.Void,  # no input: the request is None
        result=User,
        execute=lambda _: sql("SELECT * FROM users ORDER BY id"),
    )

    yield from insert(NewUser(name="Ada"))
    yield from insert(NewUser(name="Linus"))
    print((yield from every(None)))
    print((yield from by_id(2)))
    print((yield from by_id(9)))

    # A row of the wrong shape fails with a SchemaError.
    yield from sql("INSERT INTO users (name) VALUES (NULL)")
    print(type((yield from every(None).flip())).__name__)


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
