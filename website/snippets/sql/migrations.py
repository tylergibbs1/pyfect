import pyfect as fx
from pyfect.sql import SqlClient, sqlite
from pyfect.sql.sqlite import migrator


@fx.fn
def create_users():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")


@fx.fn
def add_email():
    sql = yield from SqlClient()
    yield from sql("ALTER TABLE users ADD COLUMN email TEXT")


# Keys are "<id>_<name>". New migrations run in id order, all in one transaction.
loader = migrator.from_record({"1_create_users": create_users(), "2_add_email": add_email()})


@fx.fn
def program():
    sql = yield from SqlClient()
    print((yield from migrator.run(loader=loader)))
    print((yield from migrator.run(loader=loader)))  # already applied: nothing to do
    print((yield from sql("SELECT migration_id, name FROM effect_sql_migrations")))


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
