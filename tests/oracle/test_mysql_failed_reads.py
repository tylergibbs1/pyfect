"""(pyfect) A failure part way through reading a result never leaves the pool a connection
out of step.

A value asyncmy could not decode (bytes that are not UTF-8, echoed back as text by a prepared
``SELECT ? AS b``) failed while the rest of the result was still unread, and the session was
not marked broken, so the next statement on the connection read the old result's packets
("Packet sequence number wrong"). Here a failure is injected at every packet the client reads
for a statement, and into the row parser, on each path (prepared, text, stream); after each,
the next statement on the pool of one connection must run. Against the session's MySQL
container (``_mysql.mysql_server``; skipped without Docker).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import asyncmy.connection

import pyfect as fx
from pyfect.sql import SqlClient, mysql

from ._mysql import MysqlServer

_ROWS = (
    "SELECT n, CONCAT('row ', n) AS label FROM (SELECT 1 AS n UNION ALL SELECT 2) t WHERE n > {}"
)
_MAX_STAGES = 40


class _Injected(RuntimeError):
    pass


class _FailAt:
    """Fails the ``at``-th call of what it wraps, counting from when it is armed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._at = 0
        self._calls = 0
        self.fired = False

    def arm(self, at: int) -> None:
        with self._lock:
            self._at, self._calls, self.fired = at, 0, False

    def disarm(self) -> None:
        with self._lock:
            self._at = 0

    def tick(self) -> None:
        with self._lock:
            if self._at == 0:
                return
            self._calls += 1
            if self._calls == self._at:
                self.fired = True
                raise _Injected(f"injected at call {self._at}")


@pytest.fixture
def read_packet(monkeypatch: pytest.MonkeyPatch) -> _FailAt:
    fail = _FailAt()
    connection: Any = asyncmy.connection.Connection
    original: Any = connection.read_packet

    async def read_packet(self: Any, *args: Any, **kwargs: Any) -> Any:
        fail.tick()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(asyncmy.connection.Connection, "read_packet", read_packet)
    return fail


@pytest.fixture
def row_parser(monkeypatch: pytest.MonkeyPatch) -> _FailAt:
    fail = _FailAt()
    for name in ("parse_rows_from_buffer", "parse_binary_rows_from_buffer"):
        original = getattr(asyncmy.connection, name)

        def parse(*args: Any, _original: Any = original) -> Any:
            fail.tick()
            return _original(*args)

        monkeypatch.setattr(asyncmy.connection, name, parse)
    return fail


def _prepared(sql: Any) -> fx.Effect[Any, Any]:
    return sql(_ROWS, 0)


def _stream(sql: Any) -> fx.Effect[Any, Any]:
    return sql(_ROWS, 0).stream.run_collect()


_PATHS: list[tuple[str, Callable[[Any], fx.Effect[Any, Any]], bool]] = [
    ("prepared", _prepared, False),
    ("text", _prepared, True),
    ("stream", _stream, False),
]


def _sweep(
    server: MysqlServer, fail: _FailAt, path: Callable[[Any], fx.Effect[Any, Any]], text: bool
) -> int:
    """Fail the statement at each stage in turn; the next statement must run every time.
    How many stages failed."""
    config = mysql.MysqlClientConfig(
        url=server.url, max_connections=1, disable_prepared_statements=text
    )
    expected = [{"n": 1, "label": "row 1"}, {"n": 2, "label": "row 2"}]

    def body() -> Generator[Any, Any, int]:
        sql = yield from SqlClient()
        for at in range(1, _MAX_STAGES):
            fail.arm(at)
            result: fx.Exit[Any, Any] = yield from path(sql).timeout("10 seconds").exit()
            fail.disarm()
            if not fail.fired:
                assert isinstance(result, fx.Success)
                rows: list[Any] = result.value
                assert [dict(row) for row in rows] == expected
                return at - 1
            assert isinstance(result, fx.Failure), f"stage {at} failed nothing"
            after = yield from sql("SELECT 1 AS one").timeout("10 seconds")
            assert after == [{"one": 1}], f"after a failure at stage {at}"
        raise AssertionError("the statement read more packets than expected")

    effect = fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config)))
    return fx.run_blocking(effect.timeout("2 minutes").or_die())


@pytest.mark.parametrize(("name", "path", "text"), _PATHS, ids=[p[0] for p in _PATHS])
def test_a_failure_at_any_packet_of_a_result_leaves_the_pool_usable(
    mysql_server: MysqlServer, read_packet: _FailAt, name: str, path: Any, text: bool
):
    """(pyfect) mysql: a failure at any packet read for a result leaves the next statement
    on the pool working"""
    assert _sweep(mysql_server, read_packet, path, text) > 0, name


@pytest.mark.parametrize(("name", "path", "text"), _PATHS, ids=[p[0] for p in _PATHS])
def test_a_failure_parsing_rows_leaves_the_pool_usable(
    mysql_server: MysqlServer, row_parser: _FailAt, name: str, path: Any, text: bool
):
    """(pyfect) mysql: a failure while parsing a result's rows leaves the next statement on
    the pool working"""
    stages = _sweep(mysql_server, row_parser, path, text)
    if name != "stream":  # an unbuffered result reads its rows one packet at a time
        assert stages > 0, name
