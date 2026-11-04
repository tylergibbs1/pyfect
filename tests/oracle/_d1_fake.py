"""A stand-in for D1's HTTP API (Effect's tests use Miniflare's D1): an
``HttpClient`` (``http_client.layer_test``) answering ``POST .../query`` and
``.../raw`` from a real in-memory SQLite database, as D1 does: one statement
or a ``batch`` run in one transaction, results with D1's ``meta``, blobs as
arrays of bytes, and failures as Cloudflare's error envelope (HTTP 400,
code 7500, the SQLite message with its ``SQLITE_*`` code).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect.http import body as http_body
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted
from pyfect.sql import d1

ACCOUNT = "acc"
DATABASE = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
TOKEN = "token"
BASE = "https://d1.test/client/v4"


def _value(value: object) -> object:
    return list(value) if isinstance(value, bytes) else value


def _split(sql: str) -> list[str]:
    """``sql``'s statements, cut where SQLite says one is complete."""
    statements: list[str] = []
    current = ""
    for char in sql:
        current += char
        if char == ";" and sqlite3.complete_statement(current):
            statements.append(current)
            current = ""
    if current.strip():
        statements.append(current)
    return statements


class _D1Failure(Exception):
    pass


@dataclass
class FakeD1:
    """The database and the requests it answered."""

    db: sqlite3.Connection = field(
        default_factory=lambda: sqlite3.connect(
            ":memory:", autocommit=True, check_same_thread=False
        )
    )
    requests: list[HttpClientRequest] = field(default_factory=list[HttpClientRequest])
    bodies: list[Any] = field(default_factory=list[Any])

    def _run(self, sql: str, params: list[object]) -> dict[str, Any]:
        before = self.db.total_changes
        try:
            cursor = self.db.execute(sql, params)
        except sqlite3.ProgrammingError:
            raise
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorname", "SQLITE_ERROR")
            raise _D1Failure(f"{error}: {code}") from error
        columns = [d[0] for d in cursor.description or ()]
        rows = [[_value(v) for v in row] for row in cursor.fetchall()]
        changes = self.db.total_changes - before
        return {
            "columns": columns,
            "rows": rows,
            "meta": {
                "changed_db": changes > 0,
                "changes": changes,
                "duration": 0.1,
                "last_row_id": cursor.lastrowid or 0,
                "rows_read": len(rows),
                "rows_written": changes,
                "served_by_primary": True,
                "served_by_region": "WEUR",
                "size_after": 8192,
            },
        }

    def _statements(self, sql: str, params: list[object]) -> list[dict[str, Any]]:
        try:
            return [self._run(sql, params)]
        except sqlite3.ProgrammingError:
            # Several statements in one: D1 runs each (without parameters).
            return [self._run(statement, []) for statement in _split(sql)]

    def _execute(self, queries: list[dict[str, Any]], batch: bool) -> list[dict[str, Any]]:
        if not batch:
            return self._statements(queries[0]["sql"], queries[0].get("params", []))
        self.db.execute("BEGIN")
        try:
            results = [self._run(q["sql"], q.get("params", [])) for q in queries]
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return results

    def answer(self, request: HttpClientRequest) -> HttpClientResponse:
        self.requests.append(request)
        prefix = f"{BASE}/accounts/{ACCOUNT}/d1/database/{DATABASE}/"
        endpoint = request.url.removeprefix(prefix)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return self._error(request, 10000, "Authentication error", status=403)
        if not request.url.startswith(prefix) or endpoint not in ("query", "raw"):
            return self._error(request, 7404, "No route for that URI", status=404)
        body = request.body
        assert isinstance(body, http_body.Bytes)
        payload = json.loads(body.body)
        self.bodies.append(payload)
        batch = "batch" in payload
        try:
            results = self._execute(payload["batch"] if batch else [payload], batch)
        except _D1Failure as error:
            return self._error(request, 7500, str(error))
        entries = [
            {
                "results": {"columns": r["columns"], "rows": r["rows"]}
                if endpoint == "raw"
                else [dict(zip(r["columns"], row, strict=True)) for row in r["rows"]],
                "success": True,
                "meta": r["meta"],
            }
            for r in results
        ]
        envelope = {"result": entries, "success": True, "errors": [], "messages": []}
        return http_response.make(request, json.dumps(envelope), status=200)

    def _error(
        self, request: HttpClientRequest, code: int, message: str, *, status: int = 400
    ) -> HttpClientResponse:
        envelope = {
            "result": [],
            "success": False,
            "errors": [{"code": code, "message": message}],
            "messages": [],
        }
        return http_response.make(request, json.dumps(envelope), status=status)

    def handle(self, request: HttpClientRequest) -> fx.Effect[HttpClientResponse, HttpClientError]:
        return fx.sync(lambda: self.answer(request))

    @property
    def layer(self) -> fx.Layer[http_client.HttpClient]:
        return http_client.layer_test(self.handle)

    def config(self, **fields: Any) -> d1.D1ClientConfig:
        return d1.D1ClientConfig(
            account_id=ACCOUNT,
            database_id=DATABASE,
            api_token=redacted(TOKEN),
            base_url=BASE,
            **fields,
        )

    def client_layer(self, **fields: Any) -> fx.Layer[d1.D1Client | fx.sql.SqlClient]:
        return d1.layer(self.config(**fields)).pipe(fx.provide(self.layer))


__all__ = ["FakeD1"]
