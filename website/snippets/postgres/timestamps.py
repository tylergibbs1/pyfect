import os
from datetime import datetime
from typing import TypedDict

import pyfect as fx
from pyfect import redacted
from pyfect import schema as S
from pyfect.sql import pg

# The session's TimeZone decides the zone timestamptz values come back in; it is the
# server's setting unless the pool sets one.
config = pg.PgPoolConfig(
    url=redacted.make(os.environ["DATABASE_URL"]),
    startup_parameters={"TimeZone": "America/Chicago"},
)


class Event(TypedDict):
    at: datetime


EVENT = S.Struct(Event, at=S.DateTimeUtcFromDate)


@fx.fn
def program():
    sql = yield from pg.PgClient()
    rows = yield from sql("SELECT timestamptz '2026-11-12 18:00:00+00' AS at")
    print(rows[0]["at"])

    # S.DateTimeUtc only takes a datetime that is already UTC, so it rejects this one.
    rejected = yield from S.decode_unknown_effect(S.DateTimeUtc)(rows[0]["at"]).flip()
    print(rejected)

    # S.DateTimeUtcFromDate takes the instant in any zone, as Effect's does a Date.
    event = yield from S.decode_unknown_effect(EVENT)(rows[0])
    print(event["at"])


fx.run_main(program().pipe(fx.provide(pg.layer(config))))
