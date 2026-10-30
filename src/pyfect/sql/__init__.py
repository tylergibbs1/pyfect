"""SQL (Effect's ``effect/sql``): statements built from string literals
with bound parameters, a client with transactions, batched resolvers,
schema-typed queries, migrations, and a SQLite driver on ``sqlite3``. The
PostgreSQL driver, ``pyfect.sql.pg`` on psycopg 3, is the ``pyfect-dev[pg]``
extra and is not imported here.

- ``statement``: fragments, helpers and compilers
- ``client``: ``SqlClient`` and ``make`` for drivers
- ``connection``: what a driver implements
- ``error``: ``SqlError`` and its reasons
- ``resolver``: batched requests (``SqlResolver``)
- ``schema``: queries typed by schemas (``SqlSchema``)
- ``stream``: streams from drivers that push rows (``SqlStream``)
- ``migrator``: migrations
- ``model``: repositories of ``pyfect.schema.model`` classes (``SqlModel``)
- ``sqlite``: the SQLite client (``pyfect.sql.sqlite.migrator`` runs its
  migrations)
"""

from pyfect.sql import (
    client,
    connection,
    error,
    migrator,
    model,
    resolver,
    schema,
    statement,
    stream,
)
from pyfect.sql.client import BeginTransaction, SafeIntegers, SqlClient, SqlClientService
from pyfect.sql.connection import Connection, Row
from pyfect.sql.error import SqlError
from pyfect.sql.migrator import MigrationError
from pyfect.sql.resolver import SqlRequest
from pyfect.sql.statement import Fragment, Statement

__all__ = [
    "BeginTransaction",
    "Connection",
    "Fragment",
    "MigrationError",
    "Row",
    "SafeIntegers",
    "SqlClient",
    "SqlClientService",
    "SqlError",
    "SqlRequest",
    "Statement",
    "client",
    "connection",
    "error",
    "migrator",
    "model",
    "resolver",
    "schema",
    "statement",
    "stream",
]
