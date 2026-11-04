import os

import pyfect as fx
from pyfect.sql import libsql
from pyfect.sql.error import ConstraintError

# A file or :memory: runs on sqlite3; libsql://, https:// or http:// talk to
# a libSQL server (sqld, Turso). LIBSQL_URL=libsql://db.turso.io python connect.py
config = libsql.LibsqlClientConfig(url=os.environ.get("LIBSQL_URL", ":memory:"))


@fx.fn
def program():
    sql = yield from libsql.LibsqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")

    # .raw gives the ResultSet, with the rows changed and the new rowid.
    print((yield from sql("INSERT INTO users (email) VALUES ({})", "ada@example.com").raw))

    # Failures are read from SQLite's primary code, as in Effect.
    error = yield from sql("INSERT INTO users (email) VALUES ({})", "ada@example.com").flip()
    assert isinstance(error.reason, ConstraintError)

    # A transaction rolls back when its effect fails.
    insert = sql("INSERT INTO users (email) VALUES ({})", "grace@example.com")
    yield from sql.with_transaction(insert.and_then(fx.fail("changed my mind"))).ignore()
    print((yield from sql("SELECT email FROM users ORDER BY id")))


fx.run_main(program().pipe(fx.provide(libsql.layer(config))))
