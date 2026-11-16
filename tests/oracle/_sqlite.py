"""Helpers for the SQLite driver ports: clients on a file in a temporary
directory, the way Effect's tests make them."""

from pathlib import Path
from typing import Any

import pyfect as fx
from pyfect import reactivity
from pyfect.sql import sqlite

SQLITE_FILE = "test.db"


def make_client(
    directory: Path, **config: Any
) -> fx.Effect[sqlite.SqliteClientService, Any, fx.Scope]:
    """A client on ``directory/SQLITE_FILE``, closed with the test's scope."""
    return sqlite.make(
        sqlite.SqliteClientConfig(filename=str(directory / SQLITE_FILE), **config)
    ).pipe(fx.provide(reactivity.layer))


def make_memory_client(**config: Any) -> fx.Effect[sqlite.SqliteClientService, Any, fx.Scope]:
    return sqlite.make(sqlite.SqliteClientConfig(filename=":memory:", **config)).pipe(
        fx.provide(reactivity.layer)
    )
