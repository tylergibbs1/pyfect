import os

import pyfect as fx
from pyfect import redacted
from pyfect.sql import pg

# DATABASE_URL=postgres://user:password@localhost:5432/app python connect.py
config = pg.PgPoolConfig(
    url=redacted.make(os.environ["DATABASE_URL"]),
    max_connections=5,
    idle_timeout="30 seconds",
)


@fx.fn
def program():
    sql = yield from pg.PgClient()
    yield from sql("CREATE TABLE events (id serial PRIMARY KEY, kind text, data jsonb)")

    # sql.json binds a value as jsonb; reading the column gives back the dict.
    yield from sql(
        "INSERT INTO events (kind, data) VALUES ({}, {})",
        "signup",
        sql.json({"user": "ada", "plan": "pro"}),
    )
    rows = yield from sql("SELECT kind, data FROM events")
    print(rows)

    # sql.literal is trusted SQL text (a LiteralString), spliced in as written.
    order = sql.literal("ORDER BY id DESC")
    print((yield from sql("SELECT id, kind FROM events {}", order)))

    # unsafe takes text built at runtime; PostgreSQL's placeholders are $1, $2, ...
    column = "kind"
    found = yield from sql.unsafe(f"SELECT id FROM events WHERE {column} = $1", ["signup"])
    print(found)


fx.run_main(program().pipe(fx.provide(pg.layer(config))))
