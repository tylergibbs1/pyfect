"""Settings of a SQL Server client (Effect's ``@effect/sql-mssql``
``MssqlClientConfig``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.redacted import Redacted
from pyfect.sql.mssql.types import ParameterTypes, default_parameter_types

DEFAULT_PORT = 1433
DEFAULT_MIN_CONNECTIONS = 1
DEFAULT_MAX_CONNECTIONS = 10
DEFAULT_CONNECTION_TTL = Seconds(45 * 60)
"""How long a connection lives (Effect: 45 minutes from its creation)."""

DEFAULT_CHECK_TIMEOUT = Seconds(5)
"""How long ``make`` waits for its ``SELECT 1`` without a
``connect_timeout``."""

DEFAULT_CONNECT_TIMEOUT = Seconds(15)
DEFAULT_CANCEL_TIMEOUT = Seconds(5)
DEFAULT_CONNECTION_RETRY_INTERVAL = Seconds(0.5)
DEFAULT_MAX_RETRIES_ON_TRANSIENT_ERRORS = 3
"""tedious's defaults."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MssqlClientConfig:
    """How to connect, and what the client does with values and names.

    - ``server`` / ``port`` (1433) / ``instance_name`` (found through the
      SQL Server Browser; not with ``port``) / ``database`` / ``username`` /
      ``password``: a SQL Server login
    - ``encrypt``: TLS for the whole session (default); ``False`` encrypts
      the login only, when the server allows it
    - ``trust_server``: accept the server's certificate without checking it
    - ``connect_timeout``: the connection and login of one connection (15
      seconds), and the client's first ``SELECT 1`` (5 seconds when unset)
    - ``cancel_timeout``: how long an interrupted statement's cancel may
      take before its connection is closed (5 seconds)
    - ``connection_retry_interval`` / ``max_retries_on_transient_errors``:
      retries of a login failing with a transient error (0.5 seconds, 3)
    - ``min_connections`` (1) / ``max_connections`` (10) /
      ``connection_ttl`` (45 minutes from a connection's creation): the pool
    - ``parameter_types``: the type each kind of value is sent as
      (``default_parameter_types``)
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)
    """

    server: str
    port: int | None = None
    instance_name: str | None = None
    database: str | None = None
    username: str | None = None
    password: Redacted[str] | None = None
    encrypt: bool = True
    trust_server: bool = False
    connect_timeout: Duration | None = None
    cancel_timeout: Duration | None = None
    connection_retry_interval: Duration | None = None
    max_retries_on_transient_errors: int | None = None
    min_connections: int | None = None
    max_connections: int | None = None
    connection_ttl: Duration | None = None
    parameter_types: ParameterTypes = field(default_factory=lambda: default_parameter_types)
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        if self.port is not None and self.instance_name is not None:
            raise ValueError("port and instance_name are mutually exclusive")
        if self.max_connections is not None and self.max_connections < 1:
            raise ValueError(f"max_connections must be >= 1, got {self.max_connections}")
        if self.min_connections is not None and self.min_connections < 0:
            raise ValueError(f"min_connections must be >= 0, got {self.min_connections}")
        retries = self.max_retries_on_transient_errors
        if retries is not None and retries < 0:
            raise ValueError(f"max_retries_on_transient_errors must be >= 0, got {retries}")
        missing = [kind for kind in default_parameter_types if kind not in self.parameter_types]
        if missing:
            raise ValueError(f"parameter_types has no type for {missing}")


def seconds_or(value: Duration | None, default: Seconds) -> Seconds:
    return default if value is None else to_seconds(value)


__all__ = [
    "DEFAULT_CANCEL_TIMEOUT",
    "DEFAULT_CHECK_TIMEOUT",
    "DEFAULT_CONNECTION_RETRY_INTERVAL",
    "DEFAULT_CONNECTION_TTL",
    "DEFAULT_CONNECT_TIMEOUT",
    "DEFAULT_MAX_CONNECTIONS",
    "DEFAULT_MAX_RETRIES_ON_TRANSIENT_ERRORS",
    "DEFAULT_MIN_CONNECTIONS",
    "DEFAULT_PORT",
    "MssqlClientConfig",
    "seconds_or",
]
