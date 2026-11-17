"""(pyfect) A statement that fails before any of it is written leaves its connection in use.

The session tells a failure before a command was written (the connection still in step, so it
goes on) from one after (the connection closed and replaced) by watching what asyncmy writes. It
once told them apart by writing -1 into asyncmy's ``_next_seq_id``, which asyncmy 0.2.18 typed as
an unsigned int, so every statement failed. Against the session's MySQL container
(``_mysql.mysql_server``; skipped without Docker); ``test_mysql_failed_reads`` covers failures
after a command was written.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect.sql import SqlClient, mysql

from ._mysql import MysqlServer


@pytest.mark.parametrize("text", [False, True], ids=["prepared", "text"])
def test_a_statement_that_cannot_be_encoded_keeps_the_connection(
    mysql_server: MysqlServer, text: bool
):
    """(pyfect) mysql: a statement asyncmy cannot encode fails, and the next statement runs
    on the same connection"""
    config = mysql.MysqlClientConfig(
        url=mysql_server.url, max_connections=1, disable_prepared_statements=text
    )

    def body() -> Generator[Any, Any]:
        sql = yield from SqlClient()
        before = yield from sql("SELECT CONNECTION_ID() AS id")
        failed: fx.Exit[Any, Any] = yield from sql("SELECT '\ud800' AS lone").exit()
        assert isinstance(failed, fx.Failure)
        after = yield from sql("SELECT CONNECTION_ID() AS id")
        assert after == before

    effect = fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config)))
    fx.run_blocking(effect.timeout("1 minute").or_die())
