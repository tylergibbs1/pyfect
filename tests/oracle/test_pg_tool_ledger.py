"""(pyfect) ``tool_ledger.layer_sql`` keeps the ledger contract (``_tool_ledger_contract``) on
the session's container (``_postgres.pg_server``; skipped without Docker), each case in a
new table."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("psycopg")

from _tool_ledger_contract import DURABLE

import pyfect as fx
from pyfect.ai import tool_ledger
from pyfect.sql import pg

from ._postgres import PgServer


@pytest.mark.parametrize("case", list(DURABLE))
def test_contract(pg_server: PgServer, case: str) -> None:
    server = pg_server
    client = pg.layer(pg.PgPoolConfig(url=server.url))
    table = f"tool_ledger_{uuid.uuid4().hex[:12]}"
    DURABLE[case](lambda: tool_ledger.layer_sql(table=table).pipe(fx.provide(client)))
