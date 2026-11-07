import os
from dataclasses import dataclass

import pyfect as fx
from pyfect import redacted
from pyfect.sql import pg

layer = pg.layer(pg.PgPoolConfig(url=redacted.make(os.environ["DATABASE_URL"])))


@dataclass
class Rejected(fx.TaggedError):
    reason: str


@fx.fn
def checkpoint(job: int, row: int, *, reject: bool = False):
    sql = yield from pg.PgClient()
    yield from sql("UPDATE jobs SET row = {} WHERE id = {}", row, job)
    # Sent only if the transaction commits; a notify can fail, after_commit's
    # effect can't, so its error is logged and dropped.
    yield from sql.after_commit(
        sql.notify("progress", f"{job}:{row}").pipe(fx.catch_all(fx.log_error))
    )
    if reject:
        yield from Rejected("checkpoint refused")  # rolls back, nothing is sent


@fx.fn
def program():
    sql = yield from pg.PgClient()
    yield from sql("CREATE TABLE jobs (id int PRIMARY KEY, row int)")
    yield from sql("INSERT INTO jobs VALUES (1, 0)")

    # LISTEN holds a session until the scope closes; the Dequeue gets every
    # notification sent on the channel from then on.
    progress = yield from sql.listen("progress")
    # A checkpoint that commits between the LISTEN and the read below.
    yield from sql.with_transaction(checkpoint(1, 500))

    # Read the current state after listening, then take only newer rows:
    # the 500 notification is still queued and is older than what we read.
    [state] = yield from sql("SELECT row FROM jobs WHERE id = 1")
    seen = state["row"]
    assert isinstance(seen, int)
    print("read", seen)

    error = yield from sql.with_transaction(checkpoint(1, 750, reject=True)).flip()
    print(repr(error))
    yield from sql.with_transaction(checkpoint(1, 1000))

    while seen < 1000:
        notification = yield from progress.take().timeout("5 seconds")
        row = int(notification.payload.split(":")[1])
        if row <= seen:
            print("dropped", notification.payload)
            continue
        seen = row
        print(notification.channel, notification.payload)


fx.run_main(fx.scoped(program()).pipe(fx.provide(layer)))
