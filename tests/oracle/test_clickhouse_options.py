"""``(pyfect)`` tests of the ``@clickhouse/client`` options the ClickHouse
client takes (``pyfect.sql.clickhouse.options``): ``compression``,
``keep_alive``, ``max_open_connections``, ``tls``, ``use_multipart_params``
(and ``_auto``), ``log`` and ``json``, with their URL parameters.

Effect passes its config through to ``@clickhouse/client`` 1.24.1; what a
request carries for each option is read from that client's source
(``node_base_connection.js``, ``socket_pool.js``, ``node_https_connection.js``)
and pinned on the fake server (``_clickhouse_fake``). On the real server
(``_clickhouse``): every codec compresses requests and responses that
round-trip, parameters go in a multipart body, TLS with a CA and with a
client certificate.
"""

from __future__ import annotations

import gzip
import re
import sys
import uuid
from collections.abc import Callable, Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import redacted
from pyfect.http import body as http_body
from pyfect.logger import CurrentLogAnnotations
from pyfect.sql import clickhouse
from pyfect.sql.clickhouse.options import Compression

from ._clickhouse import CERT_USER, PASSWORD, TLS, USER, ClickhouseServer
from ._clickhouse_fake import Call, FakeClickhouse

type Body = Callable[[], Generator[Any, Any, Any]]


def _run_fake(fake: FakeClickhouse, body: Body, **fields: Any) -> Any:
    program = fx.scoped(fx.gen(body)).pipe(fx.provide(clickhouse.layer(fake.config(**fields))))
    return fx.run_blocking(program.timeout("10 seconds").or_die())


def _header(call: Call, name: str) -> str | None:
    return call.request.headers.get(name.lower())


def _settings_order(call: Call) -> list[str]:
    return [key for key, _ in call.request.url_params]


# --- the config and its URL --------------------------------------------------


def test_the_url_sets_the_transport_options():
    """(pyfect) the URL sets compression, keep-alive, connections and the log level"""
    config = clickhouse.ClickhouseClientConfig(
        url="http://h?compression_request=1&compression_response=true&keep_alive_enabled=false"
        "&keep_alive_idle_socket_ttl=100&max_open_connections=3&log_level=ERROR"
    )
    connection = config.connection
    assert connection.compress_request == clickhouse.options.RequestCodec("gzip")
    assert connection.decompress_response == "gzip"
    assert connection.keep_alive is False
    assert connection.idle_socket_ttl == fx.duration.millis(100)
    assert connection.max_open_connections == 3
    assert connection.log_level == 4
    defaults = clickhouse.ClickhouseClientConfig().connection
    assert (defaults.compress_request, defaults.decompress_response) == (None, None)
    assert (defaults.keep_alive, defaults.idle_socket_ttl) == (True, fx.duration.millis(2500))
    assert (defaults.max_open_connections, defaults.log_level) == (10, 3)


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("compression_request=yes", '"compression_request" has invalid boolean value: yes. '),
        ("keep_alive_enabled=2", '"keep_alive_enabled" has invalid boolean value: 2. '),
        ("max_open_connections=0", '"max_open_connections" value 0 is less than min allowed 1'),
        ("max_open_connections=x", '"max_open_connections" has invalid numeric value: x'),
        (
            "keep_alive_idle_socket_ttl=-1",
            '"keep_alive_idle_socket_ttl" value -1 is less than min allowed 0',
        ),
        (
            "log_level=LOUD",
            '"log_level" has invalid value: LOUD. Expected one of: TRACE, DEBUG, INFO, WARN, '
            "ERROR, OFF.",
        ),
    ],
)
def test_a_bad_url_option_fails_as_clickhouse_client_says(query: str, message: str):
    """(pyfect) a bad URL option fails with @clickhouse/client's message"""
    with pytest.raises(ValueError, match=f"^{message}".replace(".", r"\.")):
        clickhouse.ClickhouseClientConfig(url=f"http://h?{query}")


def test_the_url_overriding_the_config_is_warned_about():
    """(pyfect) what the URL overrides is warned about, as mergeConfigs does"""
    config = clickhouse.ClickhouseClientConfig(
        url="http://h/db?compression_request=0&ch_a=1&request_timeout=90000",
        database="other",
        compression={"request": True},
        clickhouse_settings={"a": 0, "b": 1},
    )
    warnings = config.connection.warnings
    assert warnings[:3] == (
        '"database" is overridden by a URL parameter.',
        '"compression.request" is overridden by a URL parameter.',
        '"clickhouse_settings.a" is overridden by a URL parameter.',
    )
    assert warnings[3].startswith(
        "request_timeout is set to 90000ms, but send_progress_in_http_headers is not enabled."
    )
    assert config.connection.compress_request is None
    quiet = clickhouse.ClickhouseClientConfig(request_timeout="90 seconds", log={"level": "ERROR"})
    assert quiet.connection.warnings == ()


def test_codecs_are_checked_when_the_config_is_made():
    """(pyfect) an unknown or unavailable codec fails when the config is made"""
    bad: Any = {"request": {"codec": "lz4"}}
    with pytest.raises(
        ValueError,
        match=re.escape(
            'Unknown request compression codec "lz4". Supported codecs: gzip, zstd, br.'
        ),
    ):
        clickhouse.ClickhouseClientConfig(compression=bad)
    bad = {"response": {"codec": "xz"}}
    with pytest.raises(ValueError, match='Unknown response compression codec "xz"'):
        clickhouse.ClickhouseClientConfig(compression=bad)
    # httpx decodes zstd only with ``zstandard``; another HttpClient may.
    zstd: Compression = {"response": {"codec": "zstd"}}
    fake = FakeClickhouse()
    assert fake.config(compression=zstd).connection.decompress_response == "zstd"
    with pytest.raises(ValueError, match="zstd compression is not supported here"):
        clickhouse.ClickhouseClientConfig(compression=zstd)


# --- what requests carry -----------------------------------------------------


def test_requests_carry_the_compression_headers_and_settings_per_operation():
    """(pyfect) compression: queries, commands and exec ask for a compressed
    response, inserts, commands and exec send a compressed body"""
    fake = FakeClickhouse()

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql("SELECT {}", 1)
        yield from sql.client.command("CREATE TABLE t (a Int8) ENGINE = Memory")
        yield from sql.client.insert(table="t", values=[[1]])
        yield from sql.client.exec("SELECT 1 FORMAT CSV")

    _run_fake(fake, body, compression={"request": True, "response": {"codec": "br"}})
    query, command, insert, exec_ = fake.calls[1:]
    assert _settings_order(query)[:3] == ["query_id", "param_p1", "enable_http_compression"]
    assert _header(query, "Accept-Encoding") == "br"
    assert _header(query, "Content-Encoding") is None
    for call in (command, exec_):
        assert call.url_params["enable_http_compression"] == "1"
        assert _header(call, "Accept-Encoding") == "br"
        assert _header(call, "Content-Encoding") == "gzip"
    assert "enable_http_compression" not in insert.url_params
    assert _header(insert, "Accept-Encoding") is None
    assert _header(insert, "Content-Encoding") == "gzip"
    sent = insert.request.body
    assert isinstance(sent, http_body.Bytes)
    assert gzip.decompress(sent.body) == b"[1]\n"
    sent = command.request.body
    assert isinstance(sent, http_body.Bytes)
    assert gzip.decompress(sent.body) == b"CREATE TABLE t (a Int8) ENGINE = Memory"


def test_a_query_asking_for_compression_in_its_settings_accepts_gzip():
    """(pyfect) a query with enable_http_compression=1 of its own sends Accept-Encoding: gzip"""
    fake = FakeClickhouse()

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql("SELECT 1")
        yield from sql.with_clickhouse_settings(sql("SELECT 2"), {"enable_http_compression": 1})
        yield from sql.with_clickhouse_settings(sql("SELECT 3"), {"enable_http_compression": "1"})

    _run_fake(fake, body)
    plain, asked, text = fake.calls[1:]
    assert _header(plain, "Accept-Encoding") is None
    assert _header(asked, "Accept-Encoding") == "gzip"
    # ``=== 1``: a string setting asks the server, not the client.
    assert _header(text, "Accept-Encoding") is None


def test_keep_alive_sets_the_connection_header():
    """(pyfect) keep_alive.enabled is the Connection header"""
    for enabled, header in ((True, "keep-alive"), (False, "close")):
        fake = FakeClickhouse()

        def body():
            sql = yield from clickhouse.ClickhouseClient()
            yield from sql("SELECT 1")

        _run_fake(fake, body, keep_alive={"enabled": enabled})
        assert {_header(call, "Connection") for call in fake.calls} == {header}


def test_multipart_params_send_the_query_and_its_parameters_as_parts():
    """(pyfect) use_multipart_params: the query and its parameters are parts"""
    fake = FakeClickhouse()

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql("SELECT {} AS a, {} AS b", 1, "x")
        yield from sql("SELECT 1")

    _run_fake(fake, body, use_multipart_params=True)
    with_params, without = fake.calls[1:]
    content_type = _header(with_params, "Content-Type") or ""
    boundary = content_type.removeprefix("multipart/form-data; boundary=")
    assert boundary.startswith("----clickhouse-js-")
    assert not any(key.startswith("param_") for key, _ in with_params.request.url_params)
    sent = with_params.request.body
    assert isinstance(sent, http_body.Bytes)
    part = 'Content-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'
    assert sent.body.decode() == (
        f"--{boundary}\r\n"
        + part.format("query", "SELECT {p1: Int64} AS a, {p2: String} AS b \nFORMAT JSON")
        + f"--{boundary}\r\n"
        + part.format("param_p1", "1")
        + f"--{boundary}\r\n"
        + part.format("param_p2", "x")
        + f"--{boundary}--\r\n"
    )
    assert _header(without, "Content-Type") == "text/plain; charset=UTF-8"


def test_multipart_params_auto_moves_long_parameters_out_of_the_url():
    """(pyfect) use_multipart_params_auto: parameters over 4096 URL characters go in parts"""
    fake = FakeClickhouse()
    # 4083 characters, "param_p1=" 9 more: 4092; "é" is 6 encoded.
    fits, long = "x" * 4083, "x" * 4082 + "é"

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql("SELECT {}", fits)
        yield from sql("SELECT {}", long)

    _run_fake(fake, body, use_multipart_params_auto=True)
    short, multipart = fake.calls[1:]
    assert _settings_order(short)[:2] == ["param_p1", "query_id"]
    assert (_header(short, "Content-Type") or "").startswith("text/plain")
    assert "param_p1" not in multipart.url_params
    assert (_header(multipart, "Content-Type") or "").startswith("multipart/form-data")


def test_json_reads_and_writes_rows():
    """(pyfect) json: parse reads result rows, stringify writes inserted rows"""
    import json

    parsed: list[str] = []

    def parse(text: str) -> object:
        parsed.append(text)
        return json.loads(text)

    fake = FakeClickhouse(query=lambda call: call.answer('{"data": [{"a": 1}]}'))

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        rows = yield from sql("SELECT 1 AS a")
        yield from sql.client.insert(table="t", values=[{"a": 1}], format="JSONEachRow")
        return rows

    def stringify(row: object) -> str:
        return f"<{json.dumps(row)}>"

    rows = _run_fake(fake, body, json={"parse": parse, "stringify": stringify})
    assert rows == [{"a": 1}]
    assert parsed == ['{"data": [{"a": 1}]}']
    sent = fake.inserts[0].request.body
    assert isinstance(sent, http_body.Bytes)
    assert sent.body == b'<{"a": 1}>\n'


def _logged(
    fake: FakeClickhouse, body: Body, **fields: Any
) -> list[tuple[str, str, dict[str, Any]]]:
    entries: list[tuple[str, str, dict[str, Any]]] = []

    def record(options: Any) -> None:
        annotations = options.fiber.get_ref(CurrentLogAnnotations)
        entries.append((options.log_level.name, str(options.message[0]), dict(annotations)))

    program = fx.scoped(fx.gen(body)).pipe(fx.provide(clickhouse.layer(fake.config(**fields))))
    fx.run_blocking(
        program.exit()
        .pipe(fx.provide(fx.logger.layer([fx.Logger.make(record)])))
        .timeout("10 seconds")
        .or_die()
    )
    return entries


def test_failed_requests_are_logged_at_error_and_a_failed_ping_at_warn():
    """(pyfect) log: a failed request is logged at ERROR, a failed ping at WARN"""
    fake = FakeClickhouse(query=lambda call: call.error(62, "Syntax error"))

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql("SELEC 1").exit()

    entries = _logged(fake, body)
    assert [(level, message) for level, message, _ in entries] == [
        ("ERROR", "Query: HTTP request error.")
    ]
    annotations = entries[0][2]
    assert annotations["module"] == "Connection"
    assert annotations["operation"] == "Query"
    assert uuid.UUID(annotations["query_id"])
    assert _logged(fake, body, log={"level": "OFF"}) == []

    down = FakeClickhouse(ping=lambda call: call.error(516, "denied"))
    entries = _logged(down, body)
    assert [(level, message) for level, message, _ in entries] == [
        ("WARN", "Ping: HTTP request error.")
    ]
    assert _logged(down, body, log={"level": "ERROR"}) == []


def test_config_warnings_are_logged_when_the_client_is_made():
    """(pyfect) log: the config's warnings are logged when the client is made"""
    fake = FakeClickhouse()

    def body():
        yield from clickhouse.ClickhouseClient()

    entries = _logged(fake, body, url="http://localhost:8123?ch_a=1", clickhouse_settings={"a": 0})
    assert [(level, message, a["module"]) for level, message, a in entries] == [
        ("WARN", '"clickhouse_settings.a" is overridden by a URL parameter.', "Config")
    ]


# --- on a real server ----------------------------------------------------------


def _config(server: ClickhouseServer, **fields: Any) -> clickhouse.ClickhouseClientConfig:
    fields.setdefault("url", server.url)
    fields.setdefault("username", USER)
    fields.setdefault("password", redacted.make(PASSWORD))
    return clickhouse.ClickhouseClientConfig(**fields)


def _on_server(server: ClickhouseServer, body: Body, **fields: Any) -> Any:
    program = fx.scoped(fx.gen(body)).pipe(fx.provide(clickhouse.layer(_config(server, **fields))))
    return fx.run_blocking(program.timeout("1 minute").or_die())


_REQUEST_CODECS: list[Any] = [
    True,
    {"codec": "gzip", "level": 9},
    {"codec": "br"},
    pytest.param(
        {"codec": "zstd", "level": 3},
        marks=pytest.mark.skipif(sys.version_info < (3, 14), reason="compression.zstd"),
    ),
]


@pytest.mark.parametrize("request_codec", _REQUEST_CODECS)
@pytest.mark.parametrize("response_codec", [True, {"codec": "br"}])
def test_compressed_requests_and_responses_round_trip(
    clickhouse_server: ClickhouseServer, request_codec: Any, response_codec: Any
):
    """(pyfect) compressed requests and responses round-trip on a server"""
    table = f"compressed_{uuid.uuid4().hex[:8]}"
    rows: list[dict[str, Any]] = [{"id": i, "text": f"row {i} " * 20} for i in range(500)]

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql.client.command(
            f"CREATE TABLE {table} (id UInt32, text String) ENGINE = MergeTree ORDER BY id"
        )
        yield from sql.client.insert(table=table, values=rows, format="JSONEachRow")
        streamed = fx.stream.from_iterable(rows).map(lambda row: {**row, "id": row["id"] + 500})
        yield from sql.client.insert(table=table, values=streamed, format="JSONEachRow")
        result = yield from sql.client.query(f"SELECT id, text FROM {table} ORDER BY id")
        encoding = result.response_headers.get("content-encoding")
        document = yield from result.json()
        selected = yield from sql(
            "SELECT count() AS n FROM {} WHERE {} < id", sql.identifier(table), 10
        )
        yield from sql.client.command(f"DROP TABLE {table}")
        return encoding, document["data"], selected

    encoding, data, selected = _on_server(
        clickhouse_server, body, compression={"request": request_codec, "response": response_codec}
    )
    assert encoding == ("gzip" if response_codec is True else "br")
    assert data[:500] == rows
    assert data[500]["id"] == 500
    assert len(data) == 1000
    assert selected == [{"n": 989}]


def test_multipart_params_on_a_server(clickhouse_server: ClickhouseServer):
    """(pyfect) multipart parameters, forced and once long, on a server"""
    values = [f"user{i}@example.com" for i in range(2000)]

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        rows = yield from sql(
            "SELECT length({}) AS n, {} AS s", sql.param("Array(String)", values), "it's"
        )
        return rows

    for flag in ("use_multipart_params", "use_multipart_params_auto"):
        rows = _on_server(clickhouse_server, body, **{flag: True})
        assert rows == [{"n": 2000, "s": "it's"}]


def test_keep_alive_off_and_one_connection_on_a_server(clickhouse_server: ClickhouseServer):
    """(pyfect) keep_alive off and max_open_connections=1 serve concurrent queries"""

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        found = yield from fx.all(
            *[sql("SELECT {} AS n, sleep(0.2)", n) for n in range(4)], concurrency="unbounded"
        )
        return [rows[0]["n"] for rows in found]

    found = _on_server(
        clickhouse_server,
        body,
        keep_alive={"enabled": False, "idle_socket_ttl": 0},
        max_open_connections=1,
    )
    assert found == [0, 1, 2, 3]


def test_tls_with_a_ca_and_with_a_client_certificate(clickhouse_server: ClickhouseServer):
    """(pyfect) tls: a trusted CA, then a client certificate, on a server"""
    ca = (TLS / "cert.pem").read_bytes()

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        rows = yield from sql("SELECT currentUser() AS user")
        return rows[0]["user"]

    url = clickhouse_server.https_url
    assert _on_server(clickhouse_server, body, url=url, tls={"ca_cert": ca}) == USER
    mutual = {"ca_cert": ca, "cert": ca, "key": (TLS / "key.pem").read_bytes()}
    found = _on_server(
        clickhouse_server, body, url=url, username=CERT_USER, password=None, tls=mutual
    )
    assert found == CERT_USER
    # Without the CA the server's certificate is not trusted.
    program = fx.scoped(fx.gen(body)).pipe(
        fx.provide(clickhouse.layer(_config(clickhouse_server, url=url)))
    )
    failed = fx.run_blocking(program.timeout("1 minute").exit())
    assert fx.exit.is_failure(failed)
