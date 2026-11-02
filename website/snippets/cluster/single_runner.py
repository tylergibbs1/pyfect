import tempfile
from pathlib import Path
from typing import TypedDict

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.cluster import cluster_workflow_engine, single_runner
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.workflow import activity, workflow


class Greeting(TypedDict):
    name: str


Greet = workflow.make(
    "Greet", payload=S.Struct(Greeting), success=S.String, idempotency_key=lambda g: g["name"]
)


def compose(name: str) -> str:
    print("composing for", name)
    return f"hello, {name}"


@fx.fn
def greet(greeting: Greeting, _execution_id: str):
    return (
        yield from activity.make(
            name="greet", success=S.String, execute=fx.sync(lambda: compose(greeting["name"]))
        )
    )


def app(database: Path):
    sql = fx.layer.effect(
        SqlClient, sqlite.make(sqlite.SqliteClientConfig(filename=str(database)))
    ).pipe(fx.layer.provide(reactivity.layer))
    # One runner whose messages and shard locks are in SQL, so executions survive a restart.
    return (
        Greet.to_layer(greet)
        .pipe(fx.layer.provide_merge(cluster_workflow_engine.layer))
        .pipe(fx.layer.provide_merge(single_runner.layer()))
        .pipe(fx.layer.provide(sql))
        .or_die()
    )


with tempfile.TemporaryDirectory() as directory:
    database = Path(directory) / "cluster.db"
    print(fx.run_sync(Greet.execute({"name": "ada"}).pipe(fx.provide(app(database)))))
    # A new run on the same database reads the stored result: nothing is composed again.
    print(fx.run_sync(Greet.execute({"name": "ada"}).pipe(fx.provide(app(database)))))
