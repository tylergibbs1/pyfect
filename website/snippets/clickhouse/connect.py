import os
import uuid

import pyfect as fx
from pyfect import redacted
from pyfect.sql import clickhouse

# CLICKHOUSE_URL=http://localhost:8123 CLICKHOUSE_PASSWORD=... python connect.py
config = clickhouse.ClickhouseClientConfig(
    url=os.environ.get("CLICKHOUSE_URL", "http://localhost:8123"),
    username=os.environ.get("CLICKHOUSE_USER", "default"),
    password=redacted.make(os.environ.get("CLICKHOUSE_PASSWORD", "")),
)
table = f"events_{uuid.uuid4().hex[:8]}"


@fx.fn
def program():
    sql = yield from clickhouse.ClickhouseClient()
    yield from sql(
        "CREATE TABLE {} (kind String, at DateTime) ENGINE = MergeTree ORDER BY at",
        sql.identifier(table),
    )

    # Rows go in through insert_query, as JSONEachRow by default.
    rows = [
        {"kind": "signup", "at": "2024-01-15 14:30:00"},
        {"kind": "login", "at": "2024-01-15 15:00:00"},
    ]
    yield from sql.insert_query(table=table, values=rows)

    # Each value is a {p1: Type} parameter; the type comes from the value,
    # or from sql.param.
    since = sql.param("DateTime", "2024-01-15 14:45:00")
    print((yield from sql("SELECT kind FROM {} WHERE at > {}", sql.identifier(table), since)))

    # Settings and the query id apply to every statement of an effect.
    count = sql(
        "SELECT count() AS n, getSetting('max_threads') AS threads FROM {}", sql.identifier(table)
    )
    print((yield from sql.with_clickhouse_settings(count, {"max_threads": 2})))

    # A statement with data (INSERT ... VALUES) runs as a command, without
    # the FORMAT JSON a query gets.
    insert = sql("INSERT INTO {} VALUES ({}, now())", sql.identifier(table), "logout")
    yield from sql.as_command(insert)
    yield from sql("DROP TABLE {}", sql.identifier(table))


fx.run_main(program().pipe(fx.provide(clickhouse.layer(config))))
