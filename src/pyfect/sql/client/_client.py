"""The ``SqlClient`` service (Effect's ``effect/sql/SqlClient``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import copy as copy_module
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, Protocol, Self, TypedDict, cast

from pyfect._core import Effect, _Succeed, _WithFiber
from pyfect._effect_args import require_effect
from pyfect.context import Tag
from pyfect.errors import Done
from pyfect.queue import Dequeue
from pyfect.reactivity import Keys, Reactivity, ReactivityService
from pyfect.scope import Scope
from pyfect.sql.client._transaction import (
    TransactionConnection,
    TransactionOptions,
    WithTransaction,
    make_after_commit,
    transaction_connection,
)
from pyfect.sql.connection import Acquirer, Borrower, Connection, TransformRows
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Compiler, Constructor, SpanAttributes

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.stream import Stream


class ReactiveQueue(Protocol):
    """A driver's own ``reactive_mailbox``."""

    def __call__[A, E, R](
        self, keys: Keys, effect: Effect[A, E, R], /
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]: ...


class ClientFields(TypedDict):
    """The arguments of ``SqlClientService``."""

    acquirer: Acquirer
    compiler: Compiler
    span_attributes: SpanAttributes
    transform_rows: TransformRows | None
    borrower: Borrower | None
    driver: str
    reserve: Acquirer
    transaction_service: type[TransactionConnection]
    with_transaction: WithTransaction
    after_commit: Callable[[Effect[None, Never, Any]], Effect[None]]
    reactivity: ReactivityService
    reactive_queue: ReactiveQueue | None


class SqlClientService(Constructor):
    """A database client: a statement constructor (call it with SQL; see
    ``Constructor``) with transactions and reactive queries."""

    __slots__ = (
        "_after_commit",
        "_reactive_queue",
        "_reactivity",
        "_reserve",
        "_with_transaction",
        "driver",
        "transaction_service",
    )

    driver: str
    """The driver that made the client, such as ``"sqlite"``. Unlike the
    dialect, it tells apart drivers of the same SQL."""

    transaction_service: type[TransactionConnection]
    """The tag of this client's open transaction."""

    def __init__(
        self,
        *,
        acquirer: Acquirer,
        compiler: Compiler,
        span_attributes: SpanAttributes,
        transform_rows: TransformRows | None,
        borrower: Borrower | None,
        driver: str,
        reserve: Acquirer,
        transaction_service: type[TransactionConnection],
        with_transaction: WithTransaction,
        after_commit: Callable[[Effect[None, Never, Any]], Effect[None]],
        reactivity: ReactivityService,
        reactive_queue: ReactiveQueue | None,
    ) -> None:
        super().__init__(acquirer, compiler, span_attributes, transform_rows, borrower)
        self.driver = driver
        self._reserve = reserve
        self.transaction_service = transaction_service
        self._with_transaction = with_transaction
        self._after_commit = after_commit
        self._reactivity = reactivity
        self._reactive_queue = reactive_queue

    @property
    def reserve(self) -> Acquirer:
        """Leases a connection of its own (the driver's transaction
        acquirer, never the open transaction's connection) until the
        current scope closes. Fails with an ``SqlError`` when no connection
        can be acquired."""
        return self._reserve

    @property
    def safe(self) -> SqlClientService:
        """The client itself (Effect's copy for SafeQL)."""
        return self

    def fields(self) -> ClientFields:
        """What the client was built from, to build a driver's own client
        class on it: ``Driver(extra=..., **client.fields())``."""
        return {
            "acquirer": self.acquirer,
            "compiler": self.compiler,
            "span_attributes": self.span_attributes,
            "transform_rows": self.transform_rows,
            "borrower": self.borrower,
            "driver": self.driver,
            "reserve": self._reserve,
            "transaction_service": self.transaction_service,
            "with_transaction": self._with_transaction,
            "after_commit": self._after_commit,
            "reactivity": self._reactivity,
            "reactive_queue": self._reactive_queue,
        }

    def without_transforms(self) -> Self:
        """This client, without renaming identifiers or result columns."""
        if self.transform_rows is None:
            return self
        copy = copy_module.copy(self)
        copy.compiler = self.compiler.without_transform
        copy.transform_rows = None
        return copy

    def with_transaction[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E | SqlError, R]:
        """Run ``effect`` in a transaction: it commits if ``effect``
        succeeds and rolls back otherwise (also when interrupted). Nested,
        it is a savepoint.

        Inside, ``Reactivity`` invalidations wait for the outermost commit
        (and are dropped on rollback). ``BeginTransaction`` replaces the
        client's ``BEGIN``."""
        require_effect(effect, "effect")
        return self._with_transaction(effect)

    def after_commit[R](self, effect: Effect[None, Never, R]) -> Effect[None, Never, R]:
        """Run ``effect`` once the outermost transaction commits, or now
        outside a transaction.

        Callbacks are dropped if the transaction (or their savepoint) rolls
        back or its ``COMMIT`` fails. They run in registration order, after
        the connection is released and before ``with_transaction`` returns,
        uninterruptibly, with the services in scope when registered minus
        the transaction. A callback that dies is logged at
        ``UnhandledLogLevel``. Registering after the transaction ended is a
        defect."""
        require_effect(effect, "effect")
        return self._after_commit(effect)

    def reactive[A, E, R](self, keys: Keys, effect: Effect[A, E, R]) -> Stream[A, E, R]:
        """``effect``'s results, again each time ``keys`` are
        invalidated."""
        from pyfect import stream

        require_effect(effect, "effect")
        if self._reactive_queue is None:
            return self._reactivity.stream(keys, effect)
        queues = self._reactive_queue(keys, effect).map(stream.from_queue)
        return stream.unwrap(cast("Effect[Stream[A, E, R], E, Scope | R]", queues))

    def reactive_mailbox[A, E, R](
        self, keys: Keys, effect: Effect[A, E, R]
    ) -> Effect[Dequeue[A, E | Done], Never, R | Scope]:
        """A queue of ``effect``'s results, refreshed when ``keys`` are
        invalidated."""
        require_effect(effect, "effect")
        if self._reactive_queue is None:
            return self._reactivity.query(keys, effect)
        return self._reactive_queue(keys, effect)


class SqlClient(Tag[SqlClientService], key="effect/sql/SqlClient"):
    """The SQL client service."""


def make(
    *,
    acquirer: Acquirer,
    compiler: Compiler,
    driver: str,
    span_attributes: SpanAttributes = (),
    borrower: Borrower | None = None,
    transaction_acquirer: Acquirer | None = None,
    transaction_service: type[TransactionConnection] | None = None,
    prepare_transaction_controls: bool = False,
    begin_transaction: str = "BEGIN",
    rollback: str = "ROLLBACK",
    commit: str | Callable[[Connection], Effect[None, SqlError]] = "COMMIT",
    on_commit_failure: Callable[[Connection], Effect[None, SqlError]] | None = None,
    is_transaction: Callable[[Connection], bool] | None = None,
    savepoint: Callable[[str], str] = lambda name: f"SAVEPOINT {name}",
    release_savepoint: Callable[[str], str] | None = None,
    rollback_savepoint: Callable[[str], str] = lambda name: f"ROLLBACK TO SAVEPOINT {name}",
    transform_rows: TransformRows | None = None,
    reactive_queue: ReactiveQueue | None = None,
) -> Effect[SqlClientService, Never, Reactivity]:
    """A client on a driver's connections (Effect's ``SqlClient.make``).

    - ``acquirer`` leases connections; ``borrower`` lends one for a single
      statement outside transactions; ``transaction_acquirer`` (default:
      ``acquirer``) leases those of transactions and ``reserve``
    - ``prepare_transaction_controls``: run ``BEGIN``, ``COMMIT`` and
      ``SAVEPOINT`` prepared (off by default: several databases refuse);
      rollbacks and savepoint releases always run unprepared
    - ``commit``: its SQL, or an effect committing on the connection;
      ``on_commit_failure`` cleans up when it fails
    - ``is_transaction``: whether a transaction is open; when it says no,
      rollbacks and savepoint releases are skipped
    - ``savepoint`` / ``release_savepoint`` / ``rollback_savepoint``: SQL
      for a savepoint name (``effect_sql_<depth>``)
    """
    service = transaction_service or transaction_connection()

    def unprepared(conn: Connection, sql: str) -> Effect[None, SqlError]:
        return conn.execute_unprepared(sql, (), None).as_void()

    def control(conn: Connection, sql: str) -> Effect[None, SqlError]:
        if prepare_transaction_controls:
            return conn.execute(sql, (), None).as_void()
        return unprepared(conn, sql)

    def cleanup(conn: Connection, sql: str) -> Effect[None, SqlError]:
        # Always unprepared, so a prepared statement the backend has dropped
        # cannot stop a rollback or a savepoint release.
        if is_transaction is not None and not is_transaction(conn):
            return _Succeed(None)
        return unprepared(conn, sql)

    def begin(conn: Connection, statement: str | None) -> Effect[None, SqlError]:
        # Unlike the client's own, a provided statement isn't fixed, so it
        # isn't prepared.
        if statement is None:
            return control(conn, begin_transaction)
        return unprepared(conn, statement)

    def name(depth: int) -> str:
        return f"effect_sql_{depth}"

    release = release_savepoint
    tx_acquirer = transaction_acquirer or acquirer
    with_transaction = WithTransaction(
        TransactionOptions(
            transaction_service=service,
            span_attributes=tuple(span_attributes),
            acquire_connection=lambda restore: restore(tx_acquirer),
            begin=begin,
            savepoint=lambda conn, depth: control(conn, savepoint(name(depth))),
            release_savepoint=None
            if release is None
            else lambda conn, depth: cleanup(conn, release(name(depth))),
            commit=(lambda conn: control(conn, commit)) if isinstance(commit, str) else commit,
            on_commit_failure=on_commit_failure,
            rollback=lambda conn: cleanup(conn, rollback),
            rollback_savepoint=lambda conn, depth: cleanup(conn, rollback_savepoint(name(depth))),
        )
    )

    def in_transaction(fiber: Fiber[Any, Any]) -> Effect[Connection, SqlError, Scope]:
        found, level = fiber._context.lookup(service)
        return _Succeed(level.connection) if found else acquirer

    get_connection: Acquirer = _WithFiber(in_transaction)

    client_borrower: Borrower | None = None
    if borrower is not None:
        lend = borrower

        # A statement in a transaction runs on its connection, so only
        # statements outside one borrow.
        def borrow[A, E, R](
            f: Callable[[Connection], Effect[A, E, R]],
        ) -> Effect[A, E | SqlError, R]:
            def body(fiber: Fiber[Any, Any]) -> Effect[A, E | SqlError, R]:
                found, level = fiber._context.lookup(service)
                return f(level.connection) if found else lend(f)

            return _WithFiber(body)

        client_borrower = borrow

    def build(reactivity: ReactivityService) -> SqlClientService:
        return SqlClientService(
            acquirer=get_connection,
            compiler=compiler,
            span_attributes=span_attributes,
            transform_rows=transform_rows,
            borrower=client_borrower,
            driver=driver,
            reserve=tx_acquirer,
            transaction_service=service,
            with_transaction=with_transaction,
            after_commit=make_after_commit(service),
            reactivity=reactivity,
            reactive_queue=reactive_queue,
        )

    return Reactivity().map(build)


__all__ = ["ClientFields", "ReactiveQueue", "SqlClient", "SqlClientService", "make"]
