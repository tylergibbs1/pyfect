"""What the client needs of a SQL Server driver: a blocking connection,
used from its own worker thread (``_worker``), that pytds provides
(``_tds``) and tests replace.

A connection runs one request at a time. ``cancel`` and ``close`` may be
called from any thread: ``cancel`` stops the request in flight, which then
raises; ``close`` ends the connection. A driver calls ``on_end`` (from any
thread, maybe more than once) once its connection can no longer be used,
as tedious emits ``end`` and ``error``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pyfect.duration import Seconds
from pyfect.sql.mssql.types import DataType, ParameterOptions

type Column = tuple[str, object]
"""A column of a row: its name and value."""

type Rows = list[list[Column]]
"""The rows of a request, those of every result set in turn (tedious's
``rowCollectionOnRequestCompletion``)."""


@dataclass(frozen=True, slots=True)
class TypedValue:
    """A parameter of a request: its name (without ``@``), type and value."""

    name: str
    type: DataType
    value: object
    options: ParameterOptions


@dataclass(frozen=True, slots=True, kw_only=True)
class ConnectOptions:
    """Where and how to connect, resolved from the client's config."""

    server: str
    port: int | None
    instance_name: str | None
    database: str | None
    username: str | None
    password: str | None
    encrypt: bool
    trust_server: bool
    connect_timeout: Seconds
    cancel_timeout: Seconds
    connection_retry_interval: Seconds
    max_retries_on_transient_errors: int


class RawConnection(Protocol):
    """A logged-in connection."""

    def execute(self, sql: str, params: Sequence[TypedValue], /) -> Rows:
        """Run ``sql`` (``sp_executesql``) with its ``@1``, ``@2``, ...
        parameters; the first error the server reports is raised once the
        request ends."""
        ...

    def call_procedure(
        self, name: str, params: Sequence[TypedValue], outputs: Sequence[TypedValue], /
    ) -> tuple[Rows, dict[str, object]]:
        """Run the procedure ``name``: its rows and output values by name."""
        ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def save(self, name: str, /) -> None:
        """Set the savepoint ``name``."""
        ...

    def rollback(self, name: str | None, /) -> None:
        """Roll back the transaction, or to the savepoint ``name``."""
        ...

    def cancel(self) -> None:
        """Stop the request in flight, or the next one if none is (any
        thread; the client calls it only while a call runs)."""
        ...

    def forget_cancel(self) -> None:
        """Drop a cancel not yet acted on (the client calls it as each call
        ends, so a late cancel never stops the next call's request)."""
        ...

    def close(self) -> None:
        """End the connection (any thread)."""
        ...


type Connect = Callable[[ConnectOptions, Callable[[], None]], RawConnection]
"""Opens a connection (blocking); the callback is its ``on_end``."""


__all__ = ["Column", "Connect", "ConnectOptions", "RawConnection", "Rows", "TypedValue"]
