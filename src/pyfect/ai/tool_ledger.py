"""A ledger of tool calls, so a replayed call does not run its handler twice.

``guard(toolkit, on_unknown=...)`` gives the toolkit back with every handler behind a
``ToolLedger``, keyed by the call's ``tool_call_id``. Before a handler runs, the ledger
records the intent to run it; when the handler has given its final result, the ledger
records that result. A call the ledger has seen before is answered from it:

- a recorded result is returned as it is, and the handler does not run;
- an intent without a result (the run before was interrupted, or its process died) runs
  again only for a tool annotated ``Idempotent`` or ``Readonly``. Any other tool does not
  run: the call's outcome is unknown, and ``on_unknown`` says what happens. With
  ``"tell_model"`` the model gets a failed tool result holding a ``ToolOutcomeUnknown``, so
  the conversation stays valid; with ``"fail"`` the call fails with ``ToolOutcomeUnknown``,
  for a person to decide.

The guarantee is at most once, or you are told: a handler runs at most once per
``tool_call_id`` (idempotent and read-only tools aside), and when the ledger cannot say
whether it ran, you get ``ToolOutcomeUnknown``. It is not exactly once: a handler
interrupted mid-way may have done part of its work, and one that finished but whose result
was not recorded did all of it.

``layer_memory`` keeps the ledger in the process; ``layer_sql`` keeps it in a table of the
``SqlClient``, so it outlives the process.
"""

from __future__ import annotations

import secrets
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, LiteralString, Never, TypedDict, TypeIs, cast, overload

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._json_text import parse as parse_json
from pyfect._json_text import stringify
from pyfect.ai import _tool_outcomes as outcomes
from pyfect.ai._call_schemas import call_schema
from pyfect.ai._tool_outcomes import Outcome
from pyfect.ai.response import ToolResultFailure
from pyfect.ai.tool import (
    AnyTool,
    FailureOrigin,
    Idempotent,
    Readonly,
    is_client_executed,
)
from pyfect.ai.toolkit import HandlerResult, WithHandler
from pyfect.cause import Cause
from pyfect.context import Tag
from pyfect.errors import TaggedError
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import sync as layer_sync
from pyfect.persistence._columns import column_int, column_text
from pyfect.persistence._sql_keys import MSSQL_KEY, MYSQL_KEY, key_equals, mssql_match
from pyfect.schema import transformation as T
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Identifier
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.workflow._services import WorkflowInstance

type OnUnknown = Literal["tell_model", "fail"]
"""What a call whose outcome is unknown does: ``"tell_model"`` answers the model with a
failed tool result holding ``ToolOutcomeUnknown``; ``"fail"`` fails the call with it."""


class ToolOutcomeUnknown(S.TaggedError, identifier="pyfect/ai/ToolLedger/ToolOutcomeUnknown"):
    """The call ``tool_call_id`` of ``tool_name`` was started before and did not record a
    result, so it may or may not have run; it was not run again."""

    tool_call_id: str = S.field(S.String, key="toolCallId")
    tool_name: str = S.field(S.String, key="toolName")
    description: str = S.field(
        S.String,
        default="This tool call was started before and may or may not have run. It was not "
        "run again. Do not assume it succeeded or failed.",
    )


@dataclass(eq=False)
class ToolLedgerError(TaggedError):
    """The ledger could not read or write the record of ``tool_call_id`` (``method`` is the
    operation, ``cause`` what the store raised)."""

    message: str
    method: str
    tool_call_id: str
    cause: object = None

    @classmethod
    def __codec__(cls) -> S.Bottom[ToolLedgerError, Mapping[str, object]]:
        return _LEDGER_ERROR


class _EncodedLedgerError(TypedDict):
    _tag: Literal["ToolLedgerError"]
    message: str
    method: str
    toolCallId: str
    cause: object


def _is_ledger_error(value: object) -> TypeIs[ToolLedgerError]:
    return isinstance(value, ToolLedgerError)


_LEDGER_ERROR: S.Bottom[ToolLedgerError, Mapping[str, object]] = S.Struct(
    _EncodedLedgerError, _tag=S.Literal("ToolLedgerError"), cause=S.Defect()
).pipe(
    S.decode_to(
        S.declare(_is_ledger_error, expected="ToolLedgerError"),
        T.transform(
            decode=lambda e: ToolLedgerError(
                e["message"], e["method"], e["toolCallId"], e["cause"]
            ),
            encode=lambda e: _EncodedLedgerError(
                _tag="ToolLedgerError",
                message=e.message,
                method=e.method,
                toolCallId=e.tool_call_id,
                cause=e.cause,
            ),
        ),
    )
)
"""A ``ToolLedgerError`` as JSON, its ``cause`` as a defect (an exception comes back as
an ``ErrorInstance``), for a store of a guarded call's failures or a workflow's ``error=``."""


@dataclass(frozen=True)
class Claimed:
    """``begin`` recorded the intent: the caller runs the handler."""


@dataclass(frozen=True)
class Pending:
    """An intent without a result: the call was started and did not finish."""

    tool_name: str


@dataclass(frozen=True)
class Completed:
    """The call finished with ``outcome``."""

    tool_name: str
    outcome: Outcome


type Entry = Pending | Completed
"""What the ledger holds for a call."""

type Begun = Claimed | Entry
"""What ``begin`` found: nothing (now ``Claimed``), or the call's entry, unchanged."""


class ToolLedgerService(ABC):
    """The records of tool calls, by ``tool_call_id``."""

    @abstractmethod
    def begin(self, tool_call_id: str, tool_name: str) -> Effect[Begun, ToolLedgerError]:
        """Record the intent to run ``tool_call_id``, atomically, unless the ledger has it:
        ``Claimed`` when this call recorded it, else the entry it found."""

    @abstractmethod
    def complete(self, tool_call_id: str, outcome: Outcome) -> Effect[None, ToolLedgerError]:
        """Record the call's ``outcome``."""

    @abstractmethod
    def lookup(self, tool_call_id: str) -> Effect[Entry | None, ToolLedgerError]:
        """The call's entry, if any."""


class ToolLedger(Tag[ToolLedgerService], key="pyfect/ai/ToolLedger"):
    """The ledger ``guard`` records tool calls in."""


# In memory -------------------------------------------------------------------------------


class _MemoryLedger(ToolLedgerService):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}

    def begin(self, tool_call_id: str, tool_name: str) -> Effect[Begun, ToolLedgerError]:
        def claim() -> Begun:
            with self._lock:
                found = self._entries.get(tool_call_id)
                if found is not None:
                    return found
                self._entries[tool_call_id] = Pending(tool_name)
                return Claimed()

        return fx.sync(claim)

    def complete(self, tool_call_id: str, outcome: Outcome) -> Effect[None, ToolLedgerError]:
        def record() -> None:
            with self._lock:
                name = self._entries[tool_call_id].tool_name
                self._entries[tool_call_id] = Completed(name, outcome)

        return fx.sync(record)

    def lookup(self, tool_call_id: str) -> Effect[Entry | None, ToolLedgerError]:
        return fx.sync(lambda: self._entries.get(tool_call_id))


def memory() -> ToolLedgerService:
    """A new, empty ledger in this process."""
    return _MemoryLedger()


layer_memory: Layer[ToolLedger] = layer_sync(ToolLedger, memory)
"""A ``ToolLedger`` in this process, new for each build: it survives an interrupt or a
retry, but not the process."""


# In SQL ----------------------------------------------------------------------------------

_SUCCESS = 0
_FAILURE = 1


def layer_sql(*, table: str = "effect_ai_tool_ledger") -> Layer[ToolLedger, Never, SqlClient]:
    """A ``ToolLedger`` in ``table`` (made if missing) of the ``SqlClient``: one row per
    tool call, the result as JSON text once there is one."""
    return layer_effect(ToolLedger, fx.gen(lambda: _build_sql(table)))


def _build_sql(table_name: str) -> Generator[Effect[Any, Any, SqlClient], Any, ToolLedgerService]:
    sql = (yield from SqlClient()).without_transforms()
    table = sql.identifier(table_name)
    yield from sql.on_dialect_or_else(
        mysql=lambda: sql(
            f"CREATE TABLE IF NOT EXISTS {{}} (id {MYSQL_KEY} PRIMARY KEY, "
            "tool_name TEXT NOT NULL, claim VARCHAR(32) NOT NULL, outcome SMALLINT NULL, "
            "failure_origin VARCHAR(16) NULL, result LONGTEXT NULL)",
            table,
        ),
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sysobjects WHERE name={} AND xtype='U') "
            f"CREATE TABLE {{}} (id {MSSQL_KEY} PRIMARY KEY, "
            "tool_name NVARCHAR(MAX) NOT NULL, claim VARCHAR(32) NOT NULL, "
            "outcome SMALLINT NULL, failure_origin VARCHAR(16) NULL, result NVARCHAR(MAX) NULL)",
            table_name,
            table,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, "
            "claim VARCHAR(32) NOT NULL, outcome SMALLINT NULL, failure_origin VARCHAR(16) NULL, "
            "result TEXT NULL)",
            table,
        ),
    ).or_die()
    return _SqlLedger(sql, table)


class _SqlLedger(ToolLedgerService):
    def __init__(self, sql: SqlClientService, table: Identifier) -> None:
        self._sql = sql
        self._table = table
        self._insert = _insert_if_absent(sql, table)

    def _failed(self, method: str, tool_call_id: str) -> Callable[[SqlError], ToolLedgerError]:
        return lambda cause: ToolLedgerError(
            f"Unable to {method} the tool call {tool_call_id}", method, tool_call_id, cause
        )

    def _select(self, method: str, tool_call_id: str) -> Effect[Row | None, ToolLedgerError]:
        sql = self._sql
        return (
            sql(
                "SELECT tool_name, claim, outcome, failure_origin, result FROM {} WHERE {}",
                self._table,
                key_equals(sql, "id", tool_call_id),
            )
            .map(lambda rows: rows[0] if rows else None)
            .map_error(self._failed(method, tool_call_id))
        )

    def begin(self, tool_call_id: str, tool_name: str) -> Effect[Begun, ToolLedgerError]:
        def claim(token: str) -> Effect[Begun, ToolLedgerError]:
            inserted = self._insert(tool_call_id, tool_name, token).map_error(
                self._failed("begin", tool_call_id)
            )
            return inserted.and_then(self._select("begin", tool_call_id)).map(
                lambda row: _begun(row, token)
            )

        return fx.sync(lambda: secrets.token_hex(16)).flat_map(claim)

    def complete(self, tool_call_id: str, outcome: Outcome) -> Effect[None, ToolLedgerError]:
        sql = self._sql
        return (
            sql(
                "UPDATE {} SET outcome = {}, failure_origin = {}, result = {} WHERE {}",
                self._table,
                _FAILURE if outcome.is_failure else _SUCCESS,
                outcome.failure_origin,
                stringify(outcome.encoded_result),
                key_equals(sql, "id", tool_call_id),
            )
            .map_error(self._failed("complete", tool_call_id))
            .as_void()
        )

    def lookup(self, tool_call_id: str) -> Effect[Entry | None, ToolLedgerError]:
        return self._select("lookup", tool_call_id).map(
            lambda row: None if row is None else _entry(row)
        )


def _entry(row: Row) -> Entry:
    name = column_text(row["tool_name"])
    if row["outcome"] is None:
        return Pending(name)
    origin = row["failure_origin"]
    outcome = Outcome(
        column_int(row["outcome"]) == _FAILURE,
        parse_json(column_text(row["result"])),
        None if origin is None else cast("FailureOrigin", column_text(origin)),
    )
    return Completed(name, outcome)


def _begun(row: Row | None, token: str) -> Begun:
    if row is None:
        raise RuntimeError("ToolLedger: the row begin inserted is gone")
    entry = _entry(row)
    if isinstance(entry, Pending) and column_text(row["claim"]) == token:
        return Claimed()
    return entry


type _Insert = Callable[[str, str, str], Effect[object, SqlError]]


def _insert_if_absent(sql: SqlClientService, table: Identifier) -> _Insert:
    """Insert the intent row unless the id has one (one statement, so two callers never
    both insert)."""

    def on_conflict() -> _Insert:
        return lambda id, name, token: sql(
            "INSERT INTO {} (id, tool_name, claim) VALUES ({}, {}, {}) ON CONFLICT (id) DO NOTHING",
            table,
            id,
            name,
            token,
        )

    def mysql() -> _Insert:
        return lambda id, name, token: sql(
            "INSERT INTO {} (id, tool_name, claim) VALUES ({}, {}, {}) "
            "ON DUPLICATE KEY UPDATE id = id",
            table,
            id,
            name,
            token,
        )

    def mssql() -> _Insert:
        return lambda id, name, token: sql(
            "MERGE {} WITH (HOLDLOCK) AS target "
            "USING (SELECT {} AS id, {} AS tool_name, {} AS claim) AS source "
            f"ON {mssql_match('id')} "
            "WHEN NOT MATCHED THEN INSERT (id, tool_name, claim) "
            "VALUES (source.id, source.tool_name, source.claim);",
            table,
            id,
            name,
            token,
        )

    return sql.on_dialect_or_else(mysql=mysql, mssql=mssql, or_else=on_conflict)


# The guard -------------------------------------------------------------------------------


def _reruns(tool: AnyTool) -> bool:
    """Whether running the tool again is harmless."""
    return bool(tool.annotations.get_unsafe(Idempotent) or tool.annotations.get_unsafe(Readonly))


@dataclass(frozen=True)
class _Guarded(WithHandler[Any, Any, Any, Any]):
    inner: WithHandler[Any, Any, Any, Any] = field(repr=False)
    ledger: ToolLedgerService = field(repr=False)
    on_unknown: OnUnknown

    def handle(
        self,
        name: str,
        params: object,
        tool_call_id: str | None = None,
        options: S.ParseOptions | None = None,
    ) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
        parse = options or {}
        tool = self.tools.get(name)
        if tool is None or is_client_executed(tool):
            return self.inner.handle(name, params, tool_call_id, parse)
        if tool_call_id is None:
            return fx.die(ValueError(f'ToolLedger: a call of "{name}" needs a tool_call_id'))
        call = _Call(self, tool, tool_call_id, params, parse)
        decode = cast("Any", S.decode_unknown_effect(tool.parameters_schema, **parse))
        checked: Effect[Any, Any] = decode(params).exit()
        # Invalid parameters never reach the handler: no record is needed.
        return checked.flat_map(
            lambda exit: (
                fx.succeed(StreamC.unwrap(call.begin()))
                if isinstance(exit, Success)
                else self.inner.handle(name, params, tool_call_id, parse)
            )
        )

    def call_failure_schema(self, name: str) -> S.Top:
        return call_schema(
            self,
            "failures",
            name,
            lambda: S.Union(
                cast("Any", self.inner.call_failure_schema(name)),
                cast("Any", ToolOutcomeUnknown),
                cast("Any", ToolLedgerError),
            ),
        )


@dataclass(frozen=True)
class _Call:
    guarded: _Guarded
    tool: AnyTool
    id: str
    params: object
    options: S.ParseOptions

    def begin(self) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
        """Claim the call's record and act on what the ledger held. Inside a workflow the
        record's key is ``<execution id>/<tool_call_id>``, so executions sharing a ledger
        never answer each other's calls; outside one it is the bare ``tool_call_id``."""
        ledger = self.guarded.ledger

        def decide(key: str, found: Begun) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
            match found:
                case Claimed():
                    return self.run(key)
                case Pending() if _reruns(self.tool):
                    return self.run(key)
                case Pending():
                    return self.unknown()
                case Completed(outcome=outcome):
                    return self.replay(outcome)

        def claim(key: str) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
            return ledger.begin(key, self.tool.name).flat_map(lambda found: decide(key, found))

        def in_execution(execution_id: str) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
            # Releases up to 0.6.22 keyed calls inside a workflow by the bare id too: a
            # record they left still answers, so a run in flight across the upgrade does
            # not run its tool again.
            return ledger.lookup(self.id).flat_map(
                lambda legacy: (
                    claim(f"{execution_id}/{self.id}")
                    if legacy is None
                    else decide(self.id, legacy)
                )
            )

        return fx.service_option(WorkflowInstance).flat_map(
            lambda found: (
                claim(self.id) if found is None else in_execution(found.value.execution_id)
            )
        )

    def run(self, key: str) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
        ledger = self.guarded.ledger
        tool = self.tool

        def record(result: HandlerResult) -> Effect[HandlerResult, ToolLedgerError]:
            if result.preliminary:
                return fx.succeed(result)
            return ledger.complete(key, outcomes.of_result(result)).as_(result)

        def record_failure(cause: Cause[Any]) -> Stream[HandlerResult, Any, Any]:
            # A failure the handler raised to the caller ("error" mode) is an outcome too;
            # a defect or an interrupt is not, so the call stays pending.
            failed = StreamC.fail_cause(cause)
            return StreamC.unwrap(
                outcomes.of_failure(tool, cause).flat_map(
                    lambda outcome: (
                        fx.succeed(failed)
                        if outcome is None
                        else ledger.complete(key, outcome).as_(failed)
                    )
                )
            )

        handled = self.guarded.inner.handle(tool.name, self.params, self.id, self.options)
        return handled.map(
            lambda stream: (
                stream.catch_cause(record_failure) if tool.failure_mode == "error" else stream
            ).map_effect(record)
        )

    def unknown(self) -> Effect[Stream[HandlerResult, Any, Any], ToolOutcomeUnknown]:
        unknown = ToolOutcomeUnknown(tool_call_id=self.id, tool_name=self.tool.name)
        if self.guarded.on_unknown == "fail":
            return fx.fail(unknown)
        encoded = S.encode_unknown_sync(ToolOutcomeUnknown)(unknown)
        return fx.succeed(StreamC.make(HandlerResult(unknown, encoded, True, False, "handler")))

    def replay(self, outcome: Outcome) -> Effect[Stream[HandlerResult, Any, Any], Any, Any]:
        return outcomes.replay(
            self.tool,
            outcome,
            lambda error: ToolLedgerError(
                f"The recorded result of {self.id} no longer decodes: {error.message}",
                "replay",
                self.id,
                error,
            ),
            failures=self.guarded.inner.call_failure_schema(self.tool.name),
        )


@overload
def guard[N: LiteralString, RP, HE, R, EE, RR](
    toolkit: Effect[WithHandler[N, RP, HE, R], EE, RR], *, on_unknown: Literal["tell_model"]
) -> Effect[
    WithHandler[N, RP | ToolResultFailure[N, ToolOutcomeUnknown], HE | ToolLedgerError, R],
    EE,
    RR | ToolLedger,
]: ...
@overload
def guard[N: LiteralString, RP, HE, R, EE, RR](
    toolkit: Effect[WithHandler[N, RP, HE, R], EE, RR], *, on_unknown: Literal["fail"]
) -> Effect[
    WithHandler[N, RP, HE | ToolLedgerError | ToolOutcomeUnknown, R], EE, RR | ToolLedger
]: ...
def guard(toolkit: Effect[Any, Any, Any], *, on_unknown: OnUnknown) -> Effect[Any, Any, Any]:
    """``toolkit`` with its calls recorded in the ``ToolLedger`` (see the module
    docstring). Pass it as ``toolkit=`` where the toolkit would go."""
    require_effect(toolkit, "toolkit")

    def wrap(kit: WithHandler[Any, Any, Any, Any], ledger: ToolLedgerService) -> _Guarded:
        return _Guarded(kit.tools, kit.services, kit, ledger, on_unknown)

    return ToolLedger().flat_map(lambda ledger: toolkit.map(lambda kit: wrap(kit, ledger)))


__all__ = [
    "Begun",
    "Claimed",
    "Completed",
    "Entry",
    "OnUnknown",
    "Outcome",
    "Pending",
    "ToolLedger",
    "ToolLedgerError",
    "ToolLedgerService",
    "ToolOutcomeUnknown",
    "guard",
    "layer_memory",
    "layer_sql",
    "memory",
]
