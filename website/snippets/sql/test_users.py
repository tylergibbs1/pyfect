import pyfect as fx
from pyfect import layer, testing
from pyfect.sql import SqlClient, SqlError, sqlite
from pyfect.sql.error import UniqueViolation
from pyfect.sql.sqlite import migrator


@fx.fn
def create_users():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")


@fx.fn
def add_user(name: str):
    sql = yield from SqlClient()
    [row] = yield from sql("INSERT INTO users (name) VALUES ({}) RETURNING id", name)
    return row["id"]


# A fresh in-memory database for each test, migrated before the test starts.
database = migrator.layer(loader=migrator.from_record({"1_create_users": create_users()})).pipe(
    layer.provide_merge(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
)
db = testing.layer_fixture(database, scope="function")


@testing.effect
def test_adds_users(db: testing.Services[SqlClient]):
    assert (yield from add_user("Ada")) == 1
    assert (yield from add_user("Linus")) == 2


@testing.effect
def test_each_test_starts_empty(db: testing.Services[SqlClient]):
    sql = yield from SqlClient()
    assert (yield from sql("SELECT * FROM users")) == []


@testing.effect
def test_names_are_unique(db: testing.Services[SqlClient]):
    yield from add_user("Ada")
    error = yield from add_user("Ada").flip()
    assert isinstance(error, SqlError)
    assert isinstance(error.reason, UniqueViolation)
