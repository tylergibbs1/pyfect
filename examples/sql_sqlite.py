"""SQL on the standard library's SQLite: a migration, safe statements, a transaction.

A migration creates the table. Every statement is a template whose values
become bound parameters, never text pasted into the SQL. A transaction
commits when its effect succeeds and rolls back when it fails, so the
order below that fails half way leaves the table as it was. The rows come
back decoded by a schema.

Run with: uv run examples/sql_sqlite.py
"""

from dataclasses import dataclass

import pyfect as fx
from pyfect import schema as S
from pyfect.sql import SqlClient, sqlite
from pyfect.sql import schema as sql_schema
from pyfect.sql.sqlite import migrator


@fx.fn
def create_items():
    sql = yield from SqlClient()
    yield from sql(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, stock INTEGER NOT NULL)"
    )


migrations = migrator.from_record({"1_create_items": create_items()})


class Item(S.Class, identifier="Item"):
    id: int
    name: str
    stock: int


@dataclass
class OutOfStock(fx.TaggedError):
    name: str


@fx.fn
def take(name: str, quantity: int):
    """Take items from stock, failing if there are not enough left."""
    sql = yield from SqlClient()
    yield from sql("UPDATE items SET stock = stock - {} WHERE name = {}", quantity, name)
    short = yield from sql("SELECT 1 FROM items WHERE name = {} AND stock < 0", name)
    if short:
        yield from OutOfStock(name)


@fx.fn
def program():
    sql = yield from SqlClient()
    print(f"migrated {(yield from migrator.run(loader=migrations))}")

    # The name is a bound parameter: the quote in it is data, not SQL.
    stock = [{"name": "apple", "stock": 3}, {"name": "pear", "stock": 1}]
    yield from sql("INSERT INTO items {}", sql.insert([*stock, {"name": "Ada's jam", "stock": 2}]))
    print(sql("SELECT * FROM items WHERE name = {}", "Ada's jam").compile())

    all_items = sql_schema.find_all(
        request=S.Void,
        result=Item,
        execute=lambda _: sql("SELECT * FROM items ORDER BY id"),
    )
    show = all_items(None).map(lambda items: [f"{i.name}={i.stock}" for i in items])
    print(f"before: {(yield from show)}")

    # Both updates run in one transaction: the pear is short, so the apples come back too.
    order = fx.all(take("apple", 2), take("pear", 2))
    error = yield from sql.with_transaction(order).flip()
    print(f"order failed: {error!r}")
    print(f"after:  {(yield from show)}")


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))

if __name__ == "__main__":
    fx.run_main(program().pipe(fx.provide(database)))
