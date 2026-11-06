"""Ports of Effect's ``sql-clickhouse/test/SqlErrorClassification.test.ts``.

Each test's docstring is the Effect test title. The failures come from the
fake HTTP server of ``_clickhouse_fake``: an error response carrying the
code, as ClickHouse sends one (Effect's mock rejects with ``{ code }``).
"""

from __future__ import annotations

import json
from typing import Any

import pyfect as fx
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import clickhouse
from pyfect.sql.error import SqlError, UnknownError

from ._clickhouse_fake import Call, FakeClickhouse


def _run(effect: fx.Effect[Any, Any, Any]) -> Any:
    return fx.run_blocking(fx.scoped(effect).pipe(fx.provide(reactivity_layer)).timeout(5).or_die())


def _connect_failure_reason_tag(code: int) -> str:
    fake = FakeClickhouse(ping=lambda call: call.error(code))
    error = _run(clickhouse.make(fake.config()).flip())
    assert isinstance(error, SqlError)
    return type(error.reason).__name__


def _query_failure_reason_tag(code: int) -> str:
    fake = FakeClickhouse(query=lambda call: call.error(code))
    error = _run(clickhouse.make(fake.config()).flat_map(lambda sql: sql("SELECT 1").flip()))
    assert isinstance(error, SqlError)
    return type(error.reason).__name__


def test_maps_representative_native_codes_to_reasons():
    """maps representative native codes to reasons"""
    cases = [
        (516, "AuthenticationError"),
        (497, "AuthorizationError"),
        (62, "SqlSyntaxError"),
        (159, "StatementTimeoutError"),
    ]
    for code, expected in cases:
        assert _connect_failure_reason_tag(code) == expected


def test_falls_back_to_unknown_error_for_unmapped_codes_during_execution():
    """falls back to UnknownError for unmapped codes during execution"""
    assert _query_failure_reason_tag(999) == "UnknownError"


def test_maps_result_decoding_failures_to_sql_error():
    """maps result decoding failures to SqlError"""

    def query(call: Call) -> fx.Effect[Any, Any]:
        return call.answer("{ not json")

    fake = FakeClickhouse(query=query)
    error = _run(clickhouse.make(fake.config()).flat_map(lambda sql: sql("SELECT 1").flip()))
    assert isinstance(error, SqlError)
    assert isinstance(error.reason, UnknownError)
    assert isinstance(error.reason.cause, json.JSONDecodeError)
    assert error.reason.operation == "parseResult"


def test_a_string_code_is_read_as_a_number():
    """(pyfect) a string code is read as JavaScript's ``Number`` reads digits"""

    class Coded(Exception):
        def __init__(self, code: object) -> None:
            super().__init__("coded")
            self.code = code

    def reason(code: object) -> str:
        found = clickhouse.error.classify(Coded(code), message="m", operation="execute")
        return type(found).__name__

    assert [reason(c) for c in (" 62 ", "62", 62)] == ["SqlSyntaxError"] * 3
    assert [reason(c) for c in ("6_2", "٦٢", True, None)] == ["UnknownError"] * 4
