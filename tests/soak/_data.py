"""Stream pipelines, retries on schedules, schema round trips and SQLite, with
failures mid-stream, schedules giving up, invalid input and rolled-back
transactions."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pyfect as fx
from pyfect import schedule, stream
from pyfect import schema as S
from pyfect.sql import SqlClient, SqlError
from pyfect.sql.error import UniqueViolation

from ._workload import Workload, check, failed_with


@dataclass(eq=False)
class Flaky(fx.TaggedError):
    n: int


@fx.fn
def _streams(rng: random.Random):
    count = rng.randint(50, 500)
    keys = rng.randint(1, 6)

    def slow_double(n: int) -> fx.Effect[int]:
        return fx.sleep("0 millis").as_(n * 2) if n % 50 == 0 else fx.succeed(n * 2)

    doubled = stream.range(1, count).map_effect(slow_double, concurrency=4)
    grouped = doubled.group_by_key(lambda n: n % keys, buffer_size=rng.choice([1, 16])).map_effect(
        lambda kv: kv[1].buffer(capacity=8).run_fold(lambda: 0, lambda a, n: a + n),
        concurrency="unbounded",
    )
    merged = grouped.merge(stream.range(1, 10).map(lambda _: 0))
    roll = rng.random()
    if roll < 0.1:
        # Fail part way and recover with another stream.
        failing = stream.range(1, count).map_effect(
            lambda n: fx.fail(Flaky(n)) if n == count // 2 else fx.succeed(n)
        )
        recovered = yield from failing.catch_all(lambda _e: stream.make(-1)).run_collect()
        yield from check(recovered[-1] == -1, "the failing stream did not recover")
        return
    if roll < 0.2:
        # Interrupted mid-pipeline.
        yield from merged.interrupt_when(fx.sleep("1 millis")).run_drain()
        return
    sums = yield from merged.run_collect()
    total = sum(sums)
    yield from check(total == count * (count + 1), f"pipeline summed {total}")


@fx.fn
def _retry(rng: random.Random):
    failures = rng.randint(0, 4)
    attempts: list[int] = []

    def flaky() -> fx.Effect[int, Flaky]:
        attempts.append(1)
        return fx.fail(Flaky(len(attempts))) if len(attempts) <= failures else fx.succeed(1)

    policy = schedule.max(schedule.exponential("1 millis").jittered(), schedule.recurs(3))
    ex = yield from fx.suspend(flaky).retry(policy).exit()
    if failures <= 3:
        yield from check(ex == fx.Success(1), f"retry after {failures} failures gave {ex!r}")
    else:
        yield from check(isinstance(ex, fx.Failure), f"retry should have given up: {ex!r}")
    repeated = yield from fx.succeed(1).repeat(schedule.spaced("1 millis").up_to(times=3))
    yield from check(repeated == 3, f"repeat gave {repeated}")


class Item(S.Class):
    sku: str
    quantity: int


class Order(S.Class):
    id: int
    price: float = S.field(S.NumberFromString)
    items: tuple[Item, ...]
    note: str | None = None


_order_json = S.from_json_string(Order)
_decode_json = S.decode_effect(_order_json)
_encode_json = S.encode_effect(_order_json)
_decode_unknown = S.decode_unknown_effect(Order)


@fx.fn
def _schema(rng: random.Random):
    order = Order(
        id=rng.randint(0, 10**6),
        price=round(rng.uniform(0, 100), 2),
        items=tuple(Item(sku=f"s{i}", quantity=i) for i in range(rng.randint(0, 20))),
        note=None if rng.random() < 0.5 else "fragile",
    )
    text = yield from _encode_json(order)
    back = yield from _decode_json(text)
    yield from check(back == order, f"round trip changed {order!r} into {back!r}")
    invalid = {"id": "x", "price": 3, "items": [{"sku": 1}]}
    ex = yield from _decode_unknown(invalid).exit()
    yield from check(
        failed_with(ex, S.SchemaError),
        f"invalid input decoded: {ex!r}",
    )


SCHEMA = "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, k TEXT UNIQUE, n INTEGER)"


@fx.fn
def _sql(rng: random.Random):
    sql = yield from SqlClient()
    key = f"k{rng.getrandbits(64)}"
    roll = rng.random()
    if roll < 0.1:
        # A failing transaction rolls back its insert.
        insert = sql("INSERT INTO events (k, n) VALUES ({}, {})", key, 1)
        ex = yield from sql.with_transaction(insert.and_then(fx.fail(Flaky(0)))).exit()
        rows = yield from sql("SELECT COUNT(*) AS c FROM events WHERE k = {}", key)
        yield from check(isinstance(ex, fx.Failure), "the failing transaction succeeded")
        yield from check(rows == [{"c": 0}], f"the rolled-back row is there: {rows}")
        return
    rows = [{"k": f"{key}-{i}", "n": i} for i in range(rng.randint(1, 20))]
    yield from sql.with_transaction(sql("INSERT INTO events {}", sql.insert(rows)))
    if roll < 0.2:
        duplicate = sql("INSERT INTO events (k, n) VALUES ({}, {})", rows[0]["k"], 0)
        caught = yield from duplicate.pipe(
            fx.catch_reason(SqlError, UniqueViolation, lambda _reason, _e: fx.succeed("dup"))
        )
        yield from check(caught == "dup", f"a duplicate key was inserted: {caught!r}")
    found = yield from sql("SELECT SUM(n) AS s FROM events WHERE k LIKE {}", f"{key}-%")
    expected = sum(int(row["n"]) for row in rows)
    yield from check(found == [{"s": expected}], f"summed {found}, expected {expected}")
    # Keep the table small.
    yield from sql("DELETE FROM events WHERE k LIKE {}", f"{key}-%")


data_workloads = [
    Workload("streams", _streams, loops=2, pace=0.2),
    Workload("retry", _retry, loops=1, pace=0.08),
    Workload("schema", _schema, loops=1, pace=0.08),
    Workload("sql", _sql, loops=2, pace=0.08),
]
