"""(pyfect) The in-memory ``ToolLedger`` and the SQL one over SQLite keep the same contract
(``_tool_ledger_contract``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _tool_ledger_contract import CASES, DURABLE, Store

import pyfect as fx
from pyfect.ai import tool_ledger as L
from pyfect.sql import sqlite


def _sqlite(path: Path, table: str = "effect_ai_tool_ledger") -> Store:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(path / "ledger.db")))
    return lambda: L.layer_sql(table=table).pipe(fx.provide(client))


@pytest.mark.parametrize("case", list(CASES))
def test_memory(case: str):
    ledger = L.memory()
    CASES[case](lambda: fx.layer.succeed(L.ToolLedger, ledger))


@pytest.mark.parametrize("case", list(DURABLE))
@pytest.mark.parametrize("table", ["effect_ai_tool_ledger", "agent_tool_calls"])
def test_sqlite(case: str, table: str, tmp_path: Path):
    DURABLE[case](_sqlite(tmp_path, table))


def test_each_memory_layer_build_starts_empty():
    begin = L.ToolLedger().flat_map(lambda ledger: ledger.begin("c1", "Pay"))
    assert [fx.run_blocking(begin.pipe(fx.provide(L.layer_memory)).or_die()) for _ in range(2)] == [
        L.Claimed(),
        L.Claimed(),
    ]
