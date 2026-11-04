"""libSQL and Turso (Effect's ``@effect/sql-libsql``): a local ``file:`` or
``:memory:`` database on ``sqlite3``, or a remote server (sqld, Turso)
over Hrana over HTTP, which needs the ``pyfect-dev[httpx]`` extra::

    from pyfect.sql import libsql

    layer = libsql.layer(libsql.LibsqlClientConfig(url="libsql://db.turso.io", auth_token=token))

- ``client``: ``LibsqlClient`` (an ``SqlClient`` with its ``config`` and
  ``sdk``), ``make``, ``layer``, ``layer_config``, ``layer_from``
- ``config``: ``LibsqlClientConfig`` (a URL), ``LibsqlLiveConfig`` (a
  client the caller owns)
- ``sdk``: what the client runs on (``LibsqlSdk``), ``ResultSet`` (what
  ``.raw`` gives), ``LibsqlError``
- ``migrator``: migrations

Values are ``None``, ``int``, ``float``, ``str`` and ``bytes``; a
``bool`` argument is 0 or 1. Failures are classified from SQLite's
primary code (a unique violation is a ``ConstraintError``, as in Effect).
"""

from pyfect.sql.libsql import client, config, migrator, sdk
from pyfect.sql.libsql.client import (
    LibsqlClient,
    LibsqlClientService,
    layer,
    layer_config,
    layer_from,
    make,
)
from pyfect.sql.libsql.config import LibsqlClientConfig, LibsqlLiveConfig
from pyfect.sql.libsql.sdk import (
    LibsqlError,
    LibsqlSdk,
    LibsqlSdkTransaction,
    ResultSet,
    TransactionMode,
)

__all__ = [
    "LibsqlClient",
    "LibsqlClientConfig",
    "LibsqlClientService",
    "LibsqlError",
    "LibsqlLiveConfig",
    "LibsqlSdk",
    "LibsqlSdkTransaction",
    "ResultSet",
    "TransactionMode",
    "client",
    "config",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "migrator",
    "sdk",
]
