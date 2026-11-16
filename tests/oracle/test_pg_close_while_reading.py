"""Closing a session while a statement on it is reading waits for the
read to end, against a throwaway local PostgreSQL (``_postgres.pg_server``;
skipped without one): the read ends with its reply or a connection error,
and the process exits normally.

The scenario runs in a child process (``_pg_close_while_reading``) so an
abnormal exit fails the test instead of ending the run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("psycopg")

from _subprocess import SUBPROCESS_TIMEOUT

import pyfect as fx
from pyfect import testing
from pyfect.scope import Scope
from pyfect.sql import pg

from ._postgres import PgServer

_CHILD = Path(__file__).with_name("_pg_close_while_reading.py")


@pytest.mark.parametrize("attempt", range(5))
@pytest.mark.parametrize("mode", ["statement", "stream"])
def test_closing_a_session_while_a_read_waits_on_it(pg_server: PgServer, mode: str, attempt: int):
    env = {**os.environ, "MallocScribble": "1", "MALLOC_PERTURB_": "85"}
    done = subprocess.run(
        [sys.executable, str(_CHILD), pg_server.uri, mode],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=env,
        timeout=SUBPROCESS_TIMEOUT,
        check=False,
    )
    report = done.stdout + done.stderr
    assert done.returncode == 0, report
    assert "connection pointer is NULL" not in report
    # The read ends: its reply was read before the close, or the close ended
    # it with a connection error. A defect (the setup timing out) is not a pass.
    assert done.stdout.startswith(("Success", "SqlError")), report


@testing.live
def test_closing_a_session_with_an_idle_open_stream_does_not_wait_for_it(pg_server: PgServer):
    # The stream is open, past its first chunk, and never pulled again: no
    # read uses the session, so closing it waits for nothing.
    session_scope = fx.CloseableScope()
    config = pg.PgConnectionConfig(url=pg_server.url)
    connection = yield from pg.connection.make(config).pipe(
        fx.provide_service(Scope, session_scope)
    )
    stream_scope = fx.CloseableScope()
    pull = yield from (
        connection.stream("SELECT generate_series(1, 100000) AS n")
        .to_pull()
        .pipe(fx.provide_service(Scope, stream_scope))
    )
    first = yield from pull
    assert first[0] == {"n": 1}
    yield from session_scope.close(fx.Success(None))
    assert connection.is_dead
    assert isinstance((yield from pull.exit()), fx.Failure)
    yield from stream_scope.close(fx.Success(None))
