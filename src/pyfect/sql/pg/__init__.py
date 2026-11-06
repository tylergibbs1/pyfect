"""PostgreSQL on psycopg 3 (Effect's ``@effect/sql-pg``; the ``pyfect-dev[pg]``
extra, never imported by ``pyfect``).

psycopg's asyncio API runs on a loop thread of its own, so the client works
under ``run_blocking`` and ``run_async`` and no fiber blocks; interrupting a
statement cancels it in PostgreSQL::

    from pyfect.sql import pg

    layer = pg.layer(pg.PgPoolConfig(url=redacted.make("postgres://...")))

- ``client``: ``PgClient`` (an ``SqlClient`` with ``json``, ``listen``,
  ``notify``), ``make`` (pooled), ``make_client`` (one session),
  ``layer``, ``layer_config``, ``layer_from``, ``make_compiler``
- ``connection``: ``PgConnection`` sessions (``query``, ``query_values``,
  ``stream``, ``listen``, ``pin``, ``interrupt``)
- ``pool``: ``PgPool``
- ``config``: ``PgConnectionConfig``, ``PgClientConfig``, ``PgPoolConfig``
- ``error``: SQLSTATE classification
- ``migrator``: migrations, with ``pg_dump`` schema dumps

Values are adapted by psycopg (Effect's ``PgTypes``): ``bytea`` reads as
``bytes``, ``numeric`` as ``Decimal``, ``int8`` as ``int``, timestamps as
``datetime``, ``json`` / ``jsonb`` parsed, enums and unknown types as
``str``; ``config.types`` takes a psycopg ``AdaptersMap`` for more, and
psycopg's wrappers (``Jsonb``, ``Int4``, ...) type a parameter.
"""

from pyfect._extras import missing_extra

try:
    import psycopg  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.sql.pg", "pg") from error

from pyfect.sql.pg import client, config, connection, error, migrator, pool
from pyfect.sql.pg.client import (
    PgClient,
    PgClientService,
    layer,
    layer_config,
    layer_from,
    make,
    make_client,
    make_compiler,
)
from pyfect.sql.pg.config import PgClientConfig, PgConnectionConfig, PgPoolConfig
from pyfect.sql.pg.connection import (
    DEFAULT_LISTEN_CAPACITY,
    Field,
    Notification,
    PgConnection,
    Result,
)
from pyfect.sql.pg.pool import PgPool, PgPoolService

__all__ = [
    "DEFAULT_LISTEN_CAPACITY",
    "Field",
    "Notification",
    "PgClient",
    "PgClientConfig",
    "PgClientService",
    "PgConnection",
    "PgConnectionConfig",
    "PgPool",
    "PgPoolConfig",
    "PgPoolService",
    "Result",
    "client",
    "config",
    "connection",
    "error",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_client",
    "make_compiler",
    "migrator",
    "pool",
]
