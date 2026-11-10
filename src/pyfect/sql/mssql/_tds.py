"""SQL Server connections on pytds (pure-Python TDS, as tedious is in
Node): the driver ``MssqlClient`` uses unless a test replaces ``connect``.

Every call but ``cancel`` and ``close`` runs on the connection's worker
thread. The socket is read through ``_Transport``, which waits on it with
``select`` and on a wake-up socket ``cancel`` writes to: woken while a
request is in flight, it sends the request's attention (cancel) packet
from the reading thread itself, so the TLS layer is never used by two
threads. A cancel the server leaves unanswered for ``cancel_timeout``
closes the connection, as tedious does.

Statements go through ``sp_executesql`` with ``@1``, ``@2``, ... (tedious's
``execSql``); transactions through the TDS transaction manager, savepoints
as ``SAVE TRANSACTION``. After the login, the session settings tedious
sends are set (ANSI options on, ``READ COMMITTED``, ``XACT_ABORT OFF``).
"""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAttributeAccessIssue=false

from __future__ import annotations

import contextlib
import os
import select
import socket
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Generator, Sequence
from typing import Any

import OpenSSL.SSL
import pytds  # pyright: ignore[reportMissingTypeStubs]
from pytds import tds_base, tls  # pyright: ignore[reportMissingTypeStubs]
from pytds.tds_base import PreLoginEnc  # pyright: ignore[reportMissingTypeStubs]

from pyfect.sql.mssql import _tds_params
from pyfect.sql.mssql._driver import ConnectOptions, Rows, TypedValue

_TRANSIENT = frozenset({4060, 10928, 10929, 40197, 40501, 40613})
"""Login errors tedious retries (Microsoft's SqlClient list)."""

_READ_COMMITTED = 2
_INITIAL_SQL = "\n".join(
    (
        "set ansi_nulls on",
        "set ansi_null_dflt_on on",
        "set ansi_padding on",
        "set ansi_warnings on",
        "set arithabort on",
        "set concat_null_yields_null on",
        "set datefirst 7",
        "set dateformat mdy",
        "set implicit_transactions off",
        "set language us_english",
        "set numeric_roundabort off",
        "set quoted_identifier on",
        "set textsize 2147483647",
        "set transaction isolation level read committed",
        "set xact_abort off",
    )
)
_ROW_TOKENS = frozenset({tds_base.TDS_ROW_TOKEN, tds_base.TDS_NBC_ROW_TOKEN})


class RequestCancelled(Exception):
    """The request was cancelled."""

    def __init__(self) -> None:
        super().__init__("Canceled.")


class CancelTimeout(OSError):
    """The server did not answer a cancel in time; the connection closed."""


class _Transport:
    """The socket pytds reads and writes, waiting for data with ``select``
    so a cancel can interrupt the wait (see the module)."""

    __slots__ = ("_closed", "_deadline", "_on_wake", "_sock", "_timeout", "_wake_r", "_wake_w")

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._wake_r, self._wake_w = socket.socketpair()
        self._wake_r.setblocking(False)
        self._timeout: float | None = None
        self._deadline: float | None = None
        self._on_wake: Callable[[], None] = lambda: None
        self._closed = False

    def on_wake(self, call: Callable[[], None]) -> None:
        self._on_wake = call

    def wake(self) -> None:
        with contextlib.suppress(OSError):
            self._wake_w.send(b"\0")

    def expect_answer_within(self, seconds: float | None) -> None:
        """Close the connection unless data comes within ``seconds``."""
        self._deadline = None if seconds is None else time.monotonic() + seconds

    def _wait(self) -> None:
        started = time.monotonic()
        while True:
            now = time.monotonic()
            limits = [] if self._timeout is None else [started + self._timeout - now]
            if self._deadline is not None:
                limits.append(self._deadline - now)
            wait = max(0.0, min(limits)) if limits else None
            ready, _, _ = select.select([self._sock, self._wake_r], [], [], wait)
            if self._sock in ready:
                self._deadline = None
                return
            if self._wake_r in ready:
                with contextlib.suppress(OSError):
                    self._wake_r.recv(64)
                if self._closed:
                    raise tds_base.ClosedConnectionError()
                self._on_wake()
                continue
            if self._deadline is not None and time.monotonic() >= self._deadline:
                self.close()
                raise CancelTimeout("the server did not answer the cancel in time")
            if self._timeout is not None and time.monotonic() - started >= self._timeout:
                raise TimeoutError("timed out")

    def recv_into(self, buffer: bytearray | memoryview, size: int = 0, flags: int = 0) -> int:
        self._wait()
        return self._sock.recv_into(buffer, size, flags)

    def recv(self, size: int) -> bytes:
        self._wait()
        return self._sock.recv(size)

    def sendall(self, data: bytes, flags: int = 0) -> None:
        self._sock.sendall(data, flags)

    def gettimeout(self) -> float | None:
        return self._timeout

    def settimeout(self, timeout: float | None) -> None:
        self._timeout = timeout

    def setsockopt(self, *args: Any) -> None:
        self._sock.setsockopt(*args)

    def close(self) -> None:
        self._closed = True
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()
        self.wake()

    def release(self) -> None:
        self._wake_r.close()
        self._wake_w.close()


def _trust_any(*_args: object) -> bool:
    return True


def _tls_context(trust_server: bool) -> OpenSSL.SSL.Context:
    context = OpenSSL.SSL.Context(OpenSSL.SSL.TLS_CLIENT_METHOD)
    context.set_min_proto_version(OpenSSL.SSL.TLS1_2_VERSION)
    if trust_server:
        context.set_verify(OpenSSL.SSL.VERIFY_NONE, _trust_any)
    else:
        context.set_verify(OpenSSL.SSL.VERIFY_PEER, tls.verify_cb)
        context.set_default_verify_paths()
    return context


def _login(options: ConnectOptions) -> Any:
    login = tds_base._TdsLogin()
    login.client_host_name = socket.gethostname()[:128]
    login.library = "pyfect"
    login.app_name = "pyfect"
    login.user_name = options.username or ""
    login.password = options.password or ""
    login.port = options.port
    login.database = options.database or ""
    login.tds_version = tds_base.TDS74
    login.client_lcid = 1033
    login.pid = os.getpid()
    login.client_id = uuid.getnode()
    login.bytes_to_unicode = True
    login.option_flag2 = tds_base.TDS_ODBC_ON
    login.connect_timeout = options.connect_timeout
    login.query_timeout = None
    # tedious encrypts the whole session, or (encrypt: false) the login.
    login.tls_ctx = _tls_context(options.trust_server)
    login.validate_host = not options.trust_server
    login.enc_login_only = not options.encrypt
    login.enc_flag = PreLoginEnc.ENCRYPT_ON if options.encrypt else PreLoginEnc.ENCRYPT_OFF
    login.servers = deque([(options.server, options.port, options.instance_name or "")])
    return login


def _open(options: ConnectOptions) -> tuple[Any, _Transport]:
    host = options.server
    port = pytds.instance_browser_client.resolve_instance_port(
        server=host,
        port=options.port,
        instance=options.instance_name or "",
        timeout=options.connect_timeout.to_seconds(),
    )
    raw = socket.create_connection((host, port), options.connect_timeout.to_seconds())
    transport = _Transport(raw)
    connect: Any = pytds._connect
    try:
        conn = connect(
            login=_login(options),
            host=host,
            port=port,
            instance=options.instance_name or "",
            timeout=options.connect_timeout.to_seconds(),
            pooling=False,
            key=None,
            autocommit=True,
            isolation_level=0,
            tzinfo_factory=None,
            sock=transport,
            use_tz=None,
            row_strategy=pytds.tuple_row_strategy,
        )
    except BaseException:
        transport.close()
        transport.release()
        raise
    return conn, transport


class TdsConnection:
    """A ``RawConnection`` on a pytds connection."""

    __slots__ = (
        "_cancel_timeout",
        "_cancelled",
        "_conn",
        "_ended",
        "_lock",
        "_on_end",
        "_request",
        "_sent",
        "_transport",
    )

    def __init__(
        self, conn: Any, transport: _Transport, cancel_timeout: float, on_end: Callable[[], None]
    ) -> None:
        self._conn = conn
        self._transport = transport
        self._cancel_timeout = cancel_timeout
        self._on_end = on_end
        self._lock = threading.Lock()
        self._request = 0
        self._cancelled = 0
        self._sent = 0
        self._ended = False
        transport.on_wake(self._attention)

    @property
    def _session(self) -> Any:
        return self._conn._tds_socket.main_session

    # --- requests ---------------------------------------------------------------

    @contextlib.contextmanager
    def _requesting(self) -> Generator[Any]:
        """One request: a cancel asked for it from now on stops it, and a
        broken connection ends."""
        with self._lock:
            self._request += 1
        try:
            yield self._session
        except (OSError, EOFError, tds_base.ClosedConnectionError, tds_base.InterfaceError):
            self._end()
            raise
        finally:
            with self._lock:
                self._request += 1

    def _check_cancelled(self) -> None:
        with self._lock:
            if self._cancelled == self._request:
                raise RequestCancelled()

    def _attention(self) -> None:
        """On the reading thread, woken: send the cancel asked for."""
        session = self._session
        with self._lock:
            wanted = self._cancelled == self._request
        if (
            wanted
            and not session.in_cancel
            and session.state in (tds_base.TDS_PENDING, tds_base.TDS_READING)
        ):
            session.put_cancel()
            self._sent = self._request
            self._transport.expect_answer_within(self._cancel_timeout)

    def _read(self, session: Any, outputs: list[str] | None = None) -> Rows:
        """Read the response to the end: its rows; the first server error is
        raised once read."""
        session.begin_response()
        rows: Rows = []
        failure: BaseException | None = None
        while session.state != tds_base.TDS_IDLE:
            marker = session.get_token_id()
            try:
                session.process_token(marker)
            except tds_base.DatabaseError as error:
                failure = failure or error
            if session.in_cancel:
                session.process_cancel()
                break
            if marker in _ROW_TOKENS:
                names = [column[0] for column in session.res_info.description]
                rows.append(list(zip(names, list(session.row), strict=True)))
        if self._sent == self._request:
            raise RequestCancelled()
        if failure is not None:
            raise failure
        return rows

    def _run(self, submit: Callable[[Any], None]) -> Rows:
        with self._requesting() as session:
            self._check_cancelled()
            submit(session)
            return self._read(session)

    def execute(self, sql: str, params: Sequence[TypedValue], /) -> Rows:
        def submit(session: Any) -> None:
            types = [_tds_params.sql_type(p) for p in params]
            typed = [
                tds_base.Param(name=f"@{p.name}", type=t, value=_tds_params.value(p))
                for p, t in zip(params, types, strict=True)
            ]
            rpc = [session.make_param("", sql)]
            if typed:
                declaration = ",".join(
                    f"@{p.name} {t.get_declaration()}" for p, t in zip(params, types, strict=True)
                )
                rpc.append(session.make_param("", declaration))
            session.submit_rpc(tds_base.SP_EXECUTESQL, rpc + typed, 0)

        return self._run(submit)

    def call_procedure(
        self, name: str, params: Sequence[TypedValue], outputs: Sequence[TypedValue], /
    ) -> tuple[Rows, dict[str, object]]:
        with self._requesting() as session:
            self._check_cancelled()
            typed = [
                tds_base.Param(
                    name=f"@{p.name}", type=_tds_params.sql_type(p), value=_tds_params.value(p)
                )
                for p in params
            ] + [
                tds_base.Param(
                    name=f"@{p.name}",
                    type=_tds_params.sql_type(p),
                    value=None,
                    flags=tds_base.fByRefValue,
                )
                for p in outputs
            ]
            session.submit_rpc(name, typed, 0)
            rows = self._read(session)
            values = {
                typed[ordinal].name.removeprefix("@"): column.value
                for ordinal, column in session.output_params.items()
            }
            return rows, values

    def begin(self) -> None:
        self._run(lambda session: session.submit_begin_tran(isolation_level=_READ_COMMITTED))

    def commit(self) -> None:
        self._run(lambda session: session.submit_commit(cont=False))

    def save(self, name: str, /) -> None:
        self._run(lambda session: session.submit_plain_query(f"SAVE TRANSACTION {name}"))

    def rollback(self, name: str | None, /) -> None:
        if name is None:
            self._run(lambda session: session.submit_rollback(cont=False))
        else:
            self._run(lambda session: session.submit_plain_query(f"ROLLBACK TRANSACTION {name}"))

    def initialize(self) -> None:
        self._run(lambda session: session.submit_plain_query(_INITIAL_SQL))

    # --- any thread -------------------------------------------------------------

    def cancel(self) -> None:
        # Called while a worker call runs, so a request not yet sent is that
        # call's: it is cancelled before it starts.
        with self._lock:
            self._cancelled = self._request if self._request % 2 else self._request + 1
        self._transport.wake()

    def forget_cancel(self) -> None:
        with self._lock:
            self._cancelled = -1

    def close(self) -> None:
        self._transport.close()
        self._end()
        self._transport.release()

    def _end(self) -> None:
        with self._lock:
            ended, self._ended = self._ended, True
        if not ended:
            self._on_end()


def _connect_once(options: ConnectOptions, on_end: Callable[[], None]) -> TdsConnection:
    conn, transport = _open(options)
    connection = TdsConnection(conn, transport, options.cancel_timeout.to_seconds(), on_end)
    try:
        connection.initialize()
    except BaseException:
        connection.close()
        raise
    return connection


def connect(options: ConnectOptions, on_end: Callable[[], None]) -> TdsConnection:
    """A logged-in connection; a login failing with a transient error is
    retried (``max_retries_on_transient_errors`` times, waiting
    ``connection_retry_interval``)."""
    retries = options.max_retries_on_transient_errors
    while True:
        try:
            return _connect_once(options, on_end)
        except tds_base.Error as error:
            if retries == 0 or getattr(error, "number", None) not in _TRANSIENT:
                raise
            retries -= 1
            time.sleep(max(options.connection_retry_interval.to_seconds(), 0.0))


__all__ = ["CancelTimeout", "RequestCancelled", "TdsConnection", "connect"]
