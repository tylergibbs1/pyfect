"""(pyfect) ``tool_ledger.layer_sql`` keeps the ledger contract (``_tool_ledger_contract``) on
the session's container (``_mysql.mysql_server``; skipped without Docker), each case in a
new table."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("asyncmy")

from _tool_ledger_contract import DURABLE

import pyfect as fx
from pyfect.ai import tool_ledger
from pyfect.sql import mysql

from ._mysql import MysqlServer


@pytest.mark.parametrize("case", list(DURABLE))
def test_contract(mysql_server: MysqlServer, case: str) -> None:
    server = mysql_server
    client = mysql.layer(mysql.MysqlClientConfig(url=server.url))
    table = f"tool_ledger_{uuid.uuid4().hex[:12]}"
    DURABLE[case](lambda: tool_ledger.layer_sql(table=table).pipe(fx.provide(client)))
