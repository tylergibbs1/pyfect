"""Settings of a MySQL client (Effect's ``@effect/sql-mysql2``
``MysqlClientConfig``).

``url`` (``mysql://user:password@host:port/database``) wins over every
other connection field and over ``connect_options``, as in Effect; it is
checked when the config is made. ``connect_options`` (Effect's
``poolConfig``) are passed to ``asyncmy.connect`` as they are, for TLS
(``ssl``), a ``unix_socket``, ``init_command`` and the rest.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from pyfect.duration import Duration
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_MAX_CONNECTIONS = 10
"""mysql2's ``connectionLimit``."""

DEFAULT_IDLE_TIMEOUT = 60.0
"""mysql2's ``idleTimeout``, in seconds."""


@dataclass(frozen=True, slots=True)
class UrlParts:
    """What a ``mysql://`` URL names."""

    host: str
    port: int | None
    database: str | None
    username: str | None
    password: str | None


def parse_url(url: str) -> UrlParts:
    """The parts of a ``mysql://`` URL; ``ValueError`` when it is not
    one."""
    parts = urlsplit(url)
    if parts.scheme != "mysql":
        raise ValueError(f"expected a mysql:// URL, got scheme {parts.scheme!r}")
    if parts.query or parts.fragment:
        raise ValueError("MySQL URLs take no query or fragment; use connect_options")
    if not parts.hostname:
        raise ValueError("the MySQL URL names no host")
    database = unquote(parts.path.removeprefix("/")) or None
    return UrlParts(
        host=parts.hostname,
        port=parts.port,
        database=database,
        username=None if parts.username is None else unquote(parts.username),
        password=None if parts.password is None else unquote(parts.password),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class MysqlClientConfig:
    """How to connect, and what the client does with rows and names.

    - ``url``: a ``mysql://`` URL, overriding the connection fields below
      and ``connect_options``
    - ``host`` (``localhost``) / ``port`` (3306) / ``database`` /
      ``username`` / ``password``
    - ``max_connections``: the pool's size (10)
    - ``connection_ttl``: an unused connection closes after this long (60
      seconds)
    - ``connect_options``: more ``asyncmy.connect`` keywords (Effect's
      ``poolConfig``)
    - ``disable_prepared_statements``: send statements as text with their
      parameters escaped in, for proxies without ``COM_STMT_PREPARE``
      (Cloudflare Hyperdrive)
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)
    """

    url: Redacted[str] | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: Redacted[str] | None = None
    max_connections: int | None = None
    connection_ttl: Duration | None = None
    connect_options: Mapping[str, Any] = field(default_factory=dict[str, Any])
    disable_prepared_statements: bool = False
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        if self.url is not None:
            parse_url(redacted_value(self.url))
        if self.max_connections is not None and self.max_connections < 1:
            raise ValueError(f"max_connections must be >= 1, got {self.max_connections}")


__all__ = [
    "DEFAULT_IDLE_TIMEOUT",
    "DEFAULT_MAX_CONNECTIONS",
    "MysqlClientConfig",
    "UrlParts",
    "parse_url",
]
