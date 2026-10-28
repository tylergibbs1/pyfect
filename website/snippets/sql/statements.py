import pyfect as fx
from pyfect.sql import SqlClient, sqlite


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, role TEXT)")

    # Values are always bound parameters, never pasted into the text.
    yield from sql(
        "INSERT INTO users {}",
        sql.insert([{"name": "Ada", "role": "admin"}, {"name": "Linus", "role": "dev"}]),
    )
    name = "Robert'); DROP TABLE users;--"
    yield from sql("INSERT INTO users (name, role) VALUES ({}, {})", name, "dev")

    devs = sql("SELECT name FROM users WHERE role = {role} ORDER BY id", role="dev")
    print(devs.compile())
    print((yield from devs))

    # Helpers build fragments: lists, column sets, conditions.
    some = yield from sql("SELECT id, name FROM users WHERE {}", sql.in_("id", [1, 3]))
    print(some)


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
