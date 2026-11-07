import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pyfect as fx
from pyfect import layer, reactivity
from pyfect import schema as S
from pyfect.persistence import persisted_queue
from pyfect.persistence.persisted_queue import Metadata
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


def queues(database: str):
    sql = layer.effect(SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=database))).pipe(
        layer.provide(reactivity.layer)
    )
    # 120 s by default (90 s on Redis). A live worker renews its lock every
    # lock_refresh_interval (30 s by default), so keep the expiration above that.
    store = persisted_queue.layer_store_sql(
        poll_interval="50 millis", lock_refresh_interval="500 millis", lock_expiration="2 seconds"
    )
    return persisted_queue.layer.pipe(layer.provide(store)).pipe(layer.provide(sql))


def die(_job: str, _meta: Metadata) -> fx.Effect[None]:
    return fx.sync(lambda: os._exit(9))  # the worker is gone, its lock is still held


def finish(job: str, meta: Metadata) -> fx.Effect[None]:
    return fx.sync(lambda: print(f"{job} taken again, attempt {meta.attempts}"))


@fx.fn
def worker(handler: Callable[[str, Metadata], fx.Effect[None]]):
    queue = yield from persisted_queue.make(name="jobs", schema=S.String)
    return (yield from queue.take(handler))


@fx.fn
def offer():
    queue = yield from persisted_queue.make(name="jobs", schema=S.String)
    yield from queue.offer("pack order 7", id="7")


if len(sys.argv) > 1:
    fx.run_main(worker(die).pipe(fx.provide(queues(sys.argv[1]))))
else:
    with tempfile.TemporaryDirectory() as directory:
        database = str(Path(directory) / "queues.db")
        fx.run_main(offer().pipe(fx.provide(queues(database))))
        killed = subprocess.run([sys.executable, __file__, database], check=False)
        print("worker exited with", killed.returncode)
        fx.run_main(worker(finish).pipe(fx.provide(queues(database))))
