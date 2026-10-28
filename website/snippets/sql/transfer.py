from dataclasses import dataclass

import pyfect as fx
from pyfect.sql import SqlClient, sqlite


@dataclass
class InsufficientFunds(fx.TaggedError):
    account: str


@fx.fn
def transfer(source: str, target: str, amount: int):
    sql = yield from SqlClient()
    yield from sql("UPDATE accounts SET balance = balance - {} WHERE name = {}", amount, source)
    yield from sql("UPDATE accounts SET balance = balance + {} WHERE name = {}", amount, target)
    overdrawn = yield from sql("SELECT 1 FROM accounts WHERE name = {} AND balance < 0", source)
    if overdrawn:
        yield from InsufficientFunds(source)  # rolls back both updates


@fx.fn
def program():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE accounts (name TEXT PRIMARY KEY, balance INTEGER)")
    yield from sql(
        "INSERT INTO accounts {}",
        sql.insert([{"name": "ada", "balance": 100}, {"name": "bob", "balance": 0}]),
    )

    # Commits when the effect succeeds, rolls back when it fails or is interrupted.
    yield from sql.with_transaction(transfer("ada", "bob", 30))
    error = yield from sql.with_transaction(transfer("ada", "bob", 500)).flip()
    print(repr(error))

    print((yield from sql("SELECT * FROM accounts ORDER BY name")))


database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
fx.run_main(program().pipe(fx.provide(database)))
