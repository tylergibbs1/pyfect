"""MySQL on asyncmy (Effect's ``@effect/sql-mysql2``; the ``pyfect-dev[mysql]``
extra, never imported by ``pyfect``).

asyncmy runs on the SQL loop thread, so the client works under
``run_blocking`` and ``run_async`` and no fiber blocks::

    from pyfect.sql import mysql

    layer = mysql.layer(mysql.MysqlClientConfig(url=redacted.make("mysql://...")))

- ``client``: ``MysqlClient`` (an ``SqlClient`` with its ``config``),
  ``make``, ``layer``, ``layer_config``, ``layer_from``, ``make_compiler``
- ``config``: ``MysqlClientConfig``
- ``error``: errno classification
- ``migrator``: migrations

Statements run as server-side prepared statements (binary protocol) unless
``disable_prepared_statements``; ``unprepared`` ones and streams are sent
as text, several statements at once allowed. Values are asyncmy's:
``DECIMAL`` reads as ``Decimal``, ``BIGINT`` as ``int``, ``DATETIME`` as a
naive ``datetime``, ``JSON`` parsed, ``BLOB`` as ``bytes``; a ``dict`` or
``list`` parameter goes as its JSON text. A statement without rows gives a
``ResultSetHeader`` through ``.raw``.
"""

from pyfect._extras import missing_extra

try:
    import asyncmy  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.sql.mysql", "mysql") from error

from pyfect.sql.mysql import client, config, error, migrator
from pyfect.sql.mysql._session import ResultSetHeader
from pyfect.sql.mysql.client import (
    MysqlClient,
    MysqlClientService,
    layer,
    layer_config,
    layer_from,
    make,
    make_compiler,
)
from pyfect.sql.mysql.config import MysqlClientConfig

__all__ = [
    "MysqlClient",
    "MysqlClientConfig",
    "MysqlClientService",
    "ResultSetHeader",
    "client",
    "config",
    "error",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
    "migrator",
]
