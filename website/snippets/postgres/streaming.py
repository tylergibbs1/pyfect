import os
from collections.abc import Mapping

import pyfect as fx
from pyfect import redacted
from pyfect.sql import pg

config = pg.PgPoolConfig(url=redacted.make(os.environ["DATABASE_URL"]))


def number(row: Mapping[str, object]) -> int:
    value = row["n"]
    assert isinstance(value, int)
    return value


@fx.fn
def program():
    sql = yield from pg.PgClient()

    # .stream gives the rows as PostgreSQL sends them, holding one session until it ends.
    # (generate_series in the select list streams; in FROM it is computed whole first.)
    rows = sql("SELECT generate_series(1, 1000000000) AS n").stream
    multiples = rows.filter(lambda row: number(row) % 40 == 0).take(3)
    print((yield from multiples.run_collect()))

    # take(3) ended the stream, which cancelled the query: nothing is left running.
    running = yield from sql(
        "SELECT count(*) AS n FROM pg_stat_activity "
        "WHERE state = 'active' AND query LIKE 'SELECT generate_series%'"
    )
    print(running)

    # Folding a stream never holds every row in memory.
    small = sql("SELECT generate_series(1, 100000) AS n").stream
    print((yield from small.run_fold(lambda: 0, lambda total, row: total + number(row))))


fx.run_main(program().pipe(fx.provide(pg.layer(config))))
