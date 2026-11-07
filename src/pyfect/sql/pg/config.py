"""Settings of PostgreSQL connections, pools and clients (Effect's
``PgConnection.Config``, ``PgPool.Config``, ``PgClientConfig`` and
``PgPoolConfig``).

Each config extends the one before it: ``PgConnectionConfig`` opens one
session, ``PgClientConfig`` adds what a client does with rows and
identifiers, and ``PgPoolConfig`` adds the pool's limits. A pool reads only
the connection and pool fields.

Connections go through libpq (psycopg), so TLS takes libpq's settings:
``ssl=True`` is ``sslmode=verify-full`` against the system's trusted CAs
(``sslrootcert=system``, libpq 16 or later), ``ssl=False`` turns TLS off,
and a mapping gives libpq's ``sslmode`` / ``sslrootcert`` / ``sslcert`` /
``sslkey`` / ... as they are (``sslmode`` defaults to ``verify-full``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.duration import Duration
from pyfect.redacted import Redacted

if TYPE_CHECKING:
    from psycopg.adapt import AdaptersMap

type Password = Redacted[str] | Effect[Redacted[str]]
"""A static password, or an effect run for each connection attempt."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PgConnectionConfig:
    """How to open a session.

    - ``url``: a libpq URI (``postgres://`` or ``postgresql://``); the
      fields below win over what it says
    - ``host`` / ``port`` / ``path``: where to connect; a ``host`` starting
      with ``/`` is a socket directory, a ``path`` a socket file named
      ``.s.PGSQL.<port>``
    - ``ssl``: see the module docs; from the URL's ``sslmode`` when unset
    - ``database`` / ``username`` (default: ``$USER``) / ``password``
    - ``connect_timeout``: bounds the password, the connection and
      authentication (5 seconds)
    - ``keep_alive``: idle time before TCP keepalive probes start (whole
      seconds, at least one)
    - ``application_name``: overrides ``startup_parameters`` and the URL
      (default ``"pyfect"``)
    - ``startup_parameters``: session defaults (``SET``-able settings) for
      every session; ``startup_options``: libpq's ``options``, as they are
    - ``types``: a psycopg ``AdaptersMap`` with the session's own dumpers
      and loaders (Effect's ``PgTypes.Registry``)
    - ``prepare`` / ``prepared_statement_cache_size``: keep up to that many
      statements prepared per session (on, 100)
    """

    url: Redacted[str] | None = None
    host: str | None = None
    port: int | None = None
    path: str | None = None
    ssl: bool | Mapping[str, str] | None = None
    database: str | None = None
    username: str | None = None
    password: Password | None = None
    connect_timeout: Duration | None = None
    keep_alive: Duration | None = None
    application_name: str | None = None
    startup_parameters: Mapping[str, str] = field(default_factory=dict[str, str])
    startup_options: str | None = None
    types: AdaptersMap | None = None
    prepare: bool = True
    prepared_statement_cache_size: int = 100

    def __post_init__(self) -> None:
        if self.password is not None and not isinstance(self.password, Redacted):
            require_effect(self.password, "password")
        if self.prepared_statement_cache_size < 0:
            raise ValueError(
                "prepared_statement_cache_size must be >= 0, "
                f"got {self.prepared_statement_cache_size}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class PgClientConfig(PgConnectionConfig):
    """A session's settings and what the client does with them.

    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)
    - ``transform_json``: also rename the keys of ``json`` values (on)
    - ``on_acquire``: runs in the fiber that takes a connection, once per
      statement outside a transaction and once per ``with_transaction``,
      ``reserve``, ``listen`` and ``notify``; its finalizers run when that
      use ends. Services it needs come from where the client was built,
      overridden by the fiber's own.
    """

    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None
    transform_json: bool = True
    on_acquire: Effect[None, Never, Any] | None = None

    def __post_init__(self) -> None:
        super(PgClientConfig, self).__post_init__()
        if self.on_acquire is not None:
            require_effect(self.on_acquire, "on_acquire")


@dataclass(frozen=True, slots=True, kw_only=True)
class PgPoolConfig(PgClientConfig):
    """A client's settings and its pool's limits.

    - ``min_connections`` / ``max_connections``: the pool's size (0 to 10)
    - ``idle_timeout``: connections above the minimum close after this long
      unused (60 seconds)
    - ``connection_ttl``: replace a connection this long after it opened
      (each is used at least once, so 0 means never reuse)
    - ``acquire_timeout``: bound waiting for a connection, opening one
      included (unbounded)
    """

    min_connections: int = 0
    max_connections: int = 10
    idle_timeout: Duration = "60 seconds"
    connection_ttl: Duration | None = None
    acquire_timeout: Duration | None = None

    def __post_init__(self) -> None:
        super(PgPoolConfig, self).__post_init__()
        if not 0 <= self.min_connections <= self.max_connections or self.max_connections < 1:
            raise ValueError(
                "expected 0 <= min_connections <= max_connections and max_connections >= 1, "
                f"got {self.min_connections} and {self.max_connections}"
            )


__all__ = ["Password", "PgClientConfig", "PgConnectionConfig", "PgPoolConfig"]
