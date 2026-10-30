from datetime import datetime
from typing import NotRequired, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.schema import model as Model
from pyfect.sql import SqlClient, sqlite
from pyfect.sql import model as sql_model


# Pyright cannot compute a variant's keys, so the model declares them.
class UserInsert(TypedDict):
    name: str
    password: str
    created_at: NotRequired[datetime]  # has a default: now


class UserUpdate(TypedDict):
    id: int
    name: str
    password: str


class User(Model.Class[UserInsert, UserUpdate]):
    # The database assigns the id: it is not inserted, and a JSON client never sends it.
    id: int = Model.field(Model.field_only(["select", "update", "json"])(S.Int))
    name: str
    password: str = Model.field(Model.Sensitive(S.String))  # never in the JSON variants
    created_at: datetime = Model.field(Model.DateTimeInsertFromNumber)


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, password TEXT, created_at INTEGER)"
    )
    users = yield from sql_model.make_repository(
        User, table_name="users", id_column="id", span_prefix="Users"
    )
    ada = yield from users.insert(User.insert.make({"name": "Ada", "password": "s3cret"}))
    print(ada.id, ada.name)
    yield from users.update(User.update.make({"id": ada.id, "name": "Ada L.", "password": "x"}))
    print((yield from users.find_by_id(ada.id)).name)
    print(sorted(User.json.fields))  # what a JSON API sends: no password
    yield from users.delete(ada.id)
    print((yield from users.find_by_id(ada.id).option()))


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
