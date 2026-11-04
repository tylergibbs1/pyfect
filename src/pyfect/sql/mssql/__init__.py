"""SQL Server on pytds (Effect's ``@effect/sql-mssql``; the
``pyfect-dev[mssql]`` extra, never imported by ``pyfect``).

pytds speaks TDS in pure Python, as tedious does in Node; each connection's
calls run on a thread of its own, so the client works under ``run_sync``
and ``run_async`` and no fiber blocks::

    from pyfect.sql import mssql

    layer = mssql.layer(
        mssql.MssqlClientConfig(
            server="localhost", username="sa", password=redacted.make("..."), trust_server=True
        )
    )

- ``client``: ``MssqlClient`` (an ``SqlClient`` with its ``config``,
  ``param`` and ``call``), ``make``, ``layer``, ``layer_config``,
  ``layer_from``, ``make_compiler``
- ``config``: ``MssqlClientConfig``
- ``types``: ``TYPES``, ``ParameterOptions``, ``default_parameter_types``
- ``parameter`` / ``procedure``: stored procedure calls
- ``error``: error number classification
- ``migrator``: migrations

Statements run through ``sp_executesql`` with ``@1``, ``@2``, ...
parameters, typed by ``parameter_types`` unless given with ``param``.
Values are pytds's: ``DECIMAL`` reads as ``Decimal``, ``DATETIME`` as a
naive ``datetime`` (sent as its UTC wall clock when aware),
``UNIQUEIDENTIFIER`` as ``uuid.UUID``, binary as ``bytes``. A request's
rows are those of all its result sets in turn.
"""

from pyfect._extras import missing_extra

try:
    import OpenSSL  # noqa: F401  # pyright: ignore[reportUnusedImport]
    import pytds  # noqa: F401  # pyright: ignore[reportUnusedImport, reportMissingTypeStubs]
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.sql.mssql", "mssql") from error

from pyfect.sql.mssql import client, config, error, migrator, parameter, procedure, types
from pyfect.sql.mssql.client import (
    MssqlClient,
    MssqlClientService,
    layer,
    layer_config,
    layer_from,
    make,
    make_compiler,
)
from pyfect.sql.mssql.config import MssqlClientConfig
from pyfect.sql.mssql.parameter import Parameter
from pyfect.sql.mssql.procedure import Procedure, Result
from pyfect.sql.mssql.types import TYPES, DataType, ParameterOptions, default_parameter_types

__all__ = [
    "TYPES",
    "DataType",
    "MssqlClient",
    "MssqlClientConfig",
    "MssqlClientService",
    "Parameter",
    "ParameterOptions",
    "Procedure",
    "Result",
    "client",
    "config",
    "default_parameter_types",
    "error",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
    "migrator",
    "parameter",
    "procedure",
    "types",
]
