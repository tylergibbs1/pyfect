"""A stand-in for the SQL Server driver (``pyfect.sql.mssql._tds.connect``),
as Effect's mssql tests ``vi.mock("tedious")``: ``install`` replaces the
driver's ``connect`` for one test with ``Fake.connect``, whose connections
record their queries and answer ``[{"value": 42}]``.

- ``complete_requests = False`` or the query ``SELECT pending`` leaves a
  request pending until it is cancelled (``pending_started`` is set once one
  is waiting)
- ``request_causes``: errors the next requests raise, in turn
- ``connect_cause``: the error connecting raises
- ``error_after_connect``: the next connection ends as it is made, before
  the client has it (tedious's error right after the connect callback)
- ``respond``: answers every statement instead (its SQL and parameters)
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

import pytest

from pyfect.sql.mssql import _tds
from pyfect.sql.mssql._driver import ConnectOptions, Rows, TypedValue


class ServerError(Exception):
    """An error with tedious's ``number`` / ``message`` / ``constraint``
    properties; only those given are set."""

    def __init__(self, **properties: object) -> None:
        super().__init__()
        for name, value in properties.items():
            setattr(self, name, value)


class FakeConnection:
    def __init__(self, fake: Fake, on_end: Callable[[], None]) -> None:
        self._fake = fake
        self._on_end = on_end
        self.closed = False
        self.closed_signal = threading.Event()
        self.cancellations = 0
        self.queries: list[str] = []
        self.params: list[list[TypedValue]] = []
        self._pending: threading.Event | None = None
        self._cancel_next = False
        self._lock = threading.Lock()

    def end(self) -> None:
        """The driver's ``end`` (and ``error``) events."""
        try:
            self._on_end()
        except BaseException as error:  # the client's listener must not raise
            self._fake.emission_error = error

    def _request(self, sql: str) -> Rows:
        fake = self._fake
        self.queries.append(sql)
        if self.closed:
            raise ServerError(
                message="Requests can only be made in the LoggedIn state, not the Final state"
            )
        if fake.request_causes:
            cause = fake.request_causes.pop(0)
            if cause is not None:
                raise cause
            return []
        if sql == "SELECT pending" or not fake.complete_requests:
            with self._lock:
                pending = threading.Event()
                if self._cancel_next:
                    self._cancel_next = False
                    pending.set()
                self._pending = pending
            fake.pending_started.set()
            pending.wait()
            raise ServerError(message="Canceled.")
        return [[("value", 42)]]

    def execute(self, sql: str, params: Sequence[TypedValue], /) -> Rows:
        self.params.append(list(params))
        if self._fake.respond is not None:
            self.queries.append(sql)
            return self._fake.respond(sql, params)
        return self._request(sql)

    def call_procedure(
        self, name: str, params: Sequence[TypedValue], outputs: Sequence[TypedValue], /
    ) -> tuple[Rows, dict[str, object]]:
        if self._fake.request_causes:
            self._request(name)
        return [], {"answer": 42}

    def begin(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def save(self, name: str, /) -> None:
        return None

    def rollback(self, name: str | None, /) -> None:
        return None

    def cancel(self) -> None:
        # Count only an actual in-flight cancellation in ``cancellations``.
        with self._lock:
            self._fake.cancel_calls += 1
            pending, self._pending = self._pending, None
            if pending is None:
                self._cancel_next = True
            else:
                self.cancellations += 1
                pending.set()

    def forget_cancel(self) -> None:
        with self._lock:
            self._cancel_next = False

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.end()
        self.closed_signal.set()


class Fake:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.complete_requests = True
        self.connections: list[FakeConnection] = []
        self.pending_started = threading.Event()
        self.error_after_connect = False
        self.emission_error: BaseException | None = None
        self.connect_cause: BaseException | None = None
        self.request_causes: list[BaseException | None] = []
        self.options: list[ConnectOptions] = []
        self.respond: Callable[[str, Sequence[TypedValue]], Rows] | None = None

    def connect(self, options: ConnectOptions, on_end: Callable[[], None]) -> FakeConnection:
        self.options.append(options)
        if self.connect_cause is not None:
            raise self.connect_cause
        connection = FakeConnection(self, on_end)
        self.connections.append(connection)
        if self.error_after_connect:
            self.error_after_connect = False
            connection.closed = True
            connection.end()
        return connection


def install(monkeypatch: pytest.MonkeyPatch) -> Fake:
    fake = Fake()
    monkeypatch.setattr(_tds, "connect", fake.connect)
    return fake


__all__ = ["Fake", "FakeConnection", "ServerError", "install"]
