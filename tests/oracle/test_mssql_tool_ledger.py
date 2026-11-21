"""(pyfect) ``tool_ledger.layer_sql`` keeps the ledger contract (``_tool_ledger_contract``) on
the session's container (``_mssql.mssql_server``; skipped without Docker), each case in a
new table."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("pytds")

from _tool_ledger_contract import DURABLE, Store

import pyfect as fx
from pyfect.ai import tool_ledger
from pyfect.exit import Failure
from pyfect.result import Ok
from pyfect.sql import mssql

from ._mssql import MssqlServer


def _store(server: MssqlServer) -> Store:
    client = mssql.layer(server.config())
    table = f"tool_ledger_{uuid.uuid4().hex[:12]}"
    return lambda: tool_ledger.layer_sql(table=table).pipe(fx.provide(client))


_SPACES = "trailing_spaces_keep_ids_apart"


@pytest.mark.parametrize("case", [case for case in DURABLE if case != _SPACES])
def test_contract(mssql_server: MssqlServer, case: str) -> None:
    DURABLE[case](_store(mssql_server))


def test_an_id_differing_only_in_trailing_spaces_is_refused(mssql_server: MssqlServer) -> None:
    """SQL Server's primary key ignores trailing spaces: the second call cannot be recorded,
    so it fails before its handler could run, and is never taken for the first."""

    @fx.gen
    def program():
        ledger = yield from tool_ledger.ToolLedger()
        yield from ledger.begin("c1", "Pay")
        second = yield from ledger.begin("c1 ", "Pay").exit()
        return second, (yield from ledger.lookup("c1 "))

    second, found = fx.run_blocking(program.pipe(fx.provide(_store(mssql_server)())).or_die())
    assert isinstance(second, Failure)
    error = second.cause.find_error()
    assert isinstance(error, Ok) and isinstance(error.value, tool_ledger.ToolLedgerError)
    assert found is None
