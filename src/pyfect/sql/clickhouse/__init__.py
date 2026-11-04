"""ClickHouse (Effect's ``@effect/sql-clickhouse``): an ``SqlClient`` over
ClickHouse's HTTP interface, sent with a pyfect ``HttpClient`` (by default
one on httpx, the ``pyfect-dev[httpx]`` extra)::

    from pyfect.sql import clickhouse

    layer = clickhouse.layer(clickhouse.ClickhouseClientConfig(url="http://localhost:8123"))

- ``client``: ``ClickhouseClient`` (an ``SqlClient`` with ``param``,
  ``as_command``, ``insert_query``, ``with_query_id``,
  ``with_clickhouse_settings``, its ``config`` and ``client``), ``make``,
  ``layer``, ``layer_config``, ``layer_from``, ``make_compiler``, and the
  ``ClientMethod`` / ``QueryId`` / ``ClickhouseSettings`` references
- ``config``: ``ClickhouseClientConfig``
- ``driver``: ``ClickhouseDriver``, the HTTP client underneath
  (``query``, ``command``, ``exec``, ``insert``, ``ping``) and its results
- ``params``: how values are sent (``TupleParam``, settings, inferred
  types)
- ``error``: ``ClickhouseError`` and the ``SqlError`` reasons of its codes
- ``migrator``: migrations
"""

from pyfect.sql.clickhouse import client, config, driver, error, migrator, params
from pyfect.sql.clickhouse.client import (
    ClickhouseClient,
    ClickhouseClientService,
    ClickhouseParam,
    ClickhouseSettings,
    ClientMethod,
    QueryId,
    layer,
    layer_config,
    layer_from,
    make,
    make_compiler,
)
from pyfect.sql.clickhouse.config import ClickhouseClientConfig
from pyfect.sql.clickhouse.driver import (
    ClickhouseDriver,
    CommandResult,
    InsertResult,
    ResultSet,
)
from pyfect.sql.clickhouse.error import ClickhouseError
from pyfect.sql.clickhouse.params import Setting, Settings, TupleParam

__all__ = [
    "ClickhouseClient",
    "ClickhouseClientConfig",
    "ClickhouseClientService",
    "ClickhouseDriver",
    "ClickhouseError",
    "ClickhouseParam",
    "ClickhouseSettings",
    "ClientMethod",
    "CommandResult",
    "InsertResult",
    "QueryId",
    "ResultSet",
    "Setting",
    "Settings",
    "TupleParam",
    "client",
    "config",
    "driver",
    "error",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
    "migrator",
    "params",
]
