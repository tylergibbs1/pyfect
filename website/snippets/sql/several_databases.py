import pyfect as fx
from pyfect import layer
from pyfect.sql import SqlClient, libsql, sqlite

# Both layers provide SqlClient as well as their own tag.
buffer = libsql.layer(libsql.LibsqlClientConfig(url=":memory:"))
store = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))


@fx.fn
def program():
    # The driver tags always name the database you meant.
    in_buffer = yield from libsql.LibsqlClient()
    in_store = yield from sqlite.SqliteClient()
    yield from in_buffer("CREATE TABLE hits (id INTEGER)")
    yield from in_store("CREATE TABLE sites (id INTEGER)")

    # SqlClient is the last layer's, here the SQLite store: no error, just another database.
    either = yield from SqlClient()
    tables = yield from either("SELECT name FROM sqlite_master")
    print(tables)


fx.run_main(program().pipe(fx.provide(layer.merge(buffer, store))))
