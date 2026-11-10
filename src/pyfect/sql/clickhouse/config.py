"""Settings of a ClickHouse client (Effect's ``ClickhouseClientConfig``, the
options of ``@clickhouse/client``'s ``createClient``).

The URL is parsed when the config is made, with ``@clickhouse/client``'s
rules: ``http[s]://[username:password@]host:port[/database]``, its query
naming settings (``clickhouse_setting_<name>`` or ``ch_<name>``), headers
(``http_header_<name>``), ``application``, ``pathname``, ``session_id``,
``request_timeout`` (milliseconds), ``access_token``,
``max_open_connections``, ``compression_request`` / ``compression_response``
(booleans), ``keep_alive_enabled``, ``keep_alive_idle_socket_ttl`` and
``log_level``; any other parameter fails as unknown. What the URL says
overrides the fields of the same name (with a warning logged when the client
is made). ``connection`` is the result.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote, urlsplit

from pyfect._js import js_number, js_string, text_encode
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.duration import millis as duration_millis
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as redacted_value
from pyfect.sql.clickhouse import options as _options
from pyfect.sql.clickhouse.options import (
    LOG_LEVELS,
    Compression,
    CompressionCodec,
    Json,
    JsonHandling,
    KeepAlive,
    Log,
    LogLevel,
    RequestCodec,
    Tls,
    TlsContext,
)
from pyfect.sql.clickhouse.params import Setting, Settings

if TYPE_CHECKING:
    from pyfect.http.client import HttpClientService
    from pyfect.http.error import HttpClientError

DEFAULT_URL = "http://localhost:8123"
DEFAULT_REQUEST_TIMEOUT = duration_millis(30_000)

_SETTING_PREFIXES = ("clickhouse_setting_", "ch_")
_HEADER_PREFIX = "http_header_"
DEFAULT_IDLE_SOCKET_TTL = duration_millis(2500)
_TIMEOUT_WARNING_MILLIS = 60_000
_LONG_RUNNING = (
    "https://github.com/ClickHouse/clickhouse-js/blob/main/docs/howto/long_running_queries.md"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Connection:
    """Where and as whom requests go, as the config and its URL say."""

    url: str
    """The server's base URL, ``pathname`` included, without a trailing
    ``/``."""
    database: str
    authorization: Redacted[str]
    clickhouse_settings: Settings
    http_headers: Mapping[str, str]
    application: str | None
    session_id: str | None
    role: tuple[str, ...]
    request_timeout: Duration
    max_open_connections: float = 10
    """At most this many connections at once (``math.inf``: no limit)."""
    compress_request: RequestCodec | None = None
    decompress_response: CompressionCodec | None = None
    keep_alive: bool = True
    idle_socket_ttl: Duration = DEFAULT_IDLE_SOCKET_TTL
    tls: TlsContext | None = None
    """The ``tls`` option on an ``https`` URL."""
    tls_credentials: tuple[str, Redacted[str]] | None = None
    """The user and password sent in ``X-ClickHouse-User`` / ``-Key``
    instead of ``Authorization``: with ``tls`` on an ``https`` URL, and no
    ``http_client`` of the config's."""
    log_level: int = LOG_LEVELS["WARN"]
    json: Json = field(default_factory=Json)
    use_multipart_params: bool = False
    use_multipart_params_auto: bool = False
    warnings: tuple[str, ...] = ()
    """What the config logs as ``Config`` warnings when the client is
    made."""

    def logs(self, level: LogLevel) -> bool:
        return self.log_level <= LOG_LEVELS[level]


@dataclass(slots=True)
class _FromUrl:
    username: str | None = None
    password: str | None = None
    access_token: str | None = None
    database: str | None = None
    pathname: str | None = None
    application: str | None = None
    session_id: str | None = None
    request_timeout: Duration | None = None
    max_open_connections: float | None = None
    compression_request: bool | None = None
    compression_response: bool | None = None
    keep_alive_enabled: bool | None = None
    idle_socket_ttl: Duration | None = None
    log_level: LogLevel | None = None
    settings: dict[str, Setting] = field(default_factory=dict[str, Setting])
    headers: dict[str, str] = field(default_factory=dict[str, str])


def _timeout(value: str) -> Duration:
    text = value.strip()
    try:
        # As JavaScript's ``Number``: no ``_`` separators, ``NaN`` invalid.
        millis = math.nan if "_" in text else float(text)
    except ValueError:
        millis = math.nan
    if math.isnan(millis):
        raise ValueError(f'"request_timeout" has invalid numeric value: {text}')
    if millis < 0:
        raise ValueError(f'"request_timeout" value {text} is less than min allowed 0')
    return duration_millis(millis)


_URL_OPTIONS: dict[str, Callable[[str, str], object]] = {
    "application": lambda _key, value: value,
    "pathname": lambda _key, value: value,
    "session_id": lambda _key, value: value,
    "access_token": lambda _key, value: value,
    "request_timeout": lambda _key, value: _timeout(value),
    "max_open_connections": lambda key, value: _options.url_number(key, value, 1),
    "compression_request": _options.url_boolean,
    "compression_response": _options.url_boolean,
    "keep_alive_enabled": _options.url_boolean,
    "keep_alive_idle_socket_ttl": lambda key, value: duration_millis(
        _options.url_number(key, value, 0)
    ),
    "log_level": _options.url_log_level,
}
"""The URL parameters with an option of their own, read into the
``_FromUrl`` field of that name (``keep_alive_idle_socket_ttl`` into
``idle_socket_ttl``)."""


def _query(query: str, found: _FromUrl) -> None:
    unknown: list[str] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        prefix = next((p for p in _SETTING_PREFIXES if key.startswith(p)), None)
        if prefix is not None:
            found.settings[key.removeprefix(prefix)] = value
        elif key.startswith(_HEADER_PREFIX):
            found.headers[key.removeprefix(_HEADER_PREFIX)] = value
        elif key in _URL_OPTIONS:
            name = "idle_socket_ttl" if key == "keep_alive_idle_socket_ttl" else key
            setattr(found, name, _URL_OPTIONS[key](key, value))
        else:
            unknown.append(key)
    if unknown:
        raise ValueError(f"Unknown URL parameters: {', '.join(unknown)}")


def _parse_url(url: str) -> tuple[str, _FromUrl]:
    """The base URL (scheme and host) and what the rest of ``url`` sets."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"ClickHouse URL protocol must be either http or https. Got: {parts.scheme}:"
        )
    if not parts.hostname:
        raise ValueError(
            "ClickHouse URL is malformed. Expected format: "
            "http[s]://[username:password@]hostname:port[/database][?param1=value1&param2=value2]"
        )
    found = _FromUrl()
    if parts.username:
        found.username = unquote(parts.username)
    if parts.password:
        found.password = unquote(parts.password)
    if len(parts.path.strip()) > 1:
        found.database = unquote(parts.path[1:])
    _query(parts.query, found)
    host = parts.netloc.rpartition("@")[2]
    return f"{parts.scheme}://{host}", found


def _authorization(
    username: str | None, password: str | None, access_token: str | None
) -> Redacted[str]:
    import base64

    if access_token is not None:
        if username is not None or password is not None:
            raise ValueError(
                "Both access token and username/password are provided in the configuration. "
                "Please use only one authentication method."
            )
        return redacted(f"Bearer {access_token}")
    credentials = text_encode(f"{username or 'default'}:{password or ''}")
    return redacted(f"Basic {base64.b64encode(credentials).decode('ascii')}")


def _plain(value: Redacted[str] | None) -> str | None:
    return None if value is None else redacted_value(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ClickhouseClientConfig:
    """A ClickHouse server to talk to over its HTTP interface.

    - ``url``: the server (default ``http://localhost:8123``; see the module)
    - ``pathname``: a path the server is behind (``/clickhouse``)
    - ``username`` / ``password`` (default user ``default``), or
      ``access_token`` (a JWT, sent as a bearer token)
    - ``database``: the default database (``default``)
    - ``clickhouse_settings``: settings sent with every request
    - ``http_headers``: headers sent with every request
    - ``application``: named in the ``User-Agent``
    - ``session_id`` / ``role``: the session and roles of every request
    - ``request_timeout``: how long a request may stay idle (30 s), as the
      timeout of the client ``make`` creates
    - ``max_open_connections``: connections open at once (10)
    - ``compression``, ``keep_alive``, ``tls``, ``log``, ``json``:
      ``@clickhouse/client``'s options of those names (``options``)
    - ``use_multipart_params``: a query's parameters, and the query, go in a
      ``multipart/form-data`` body instead of the URL;
      ``use_multipart_params_auto`` does so once the parameters would take
      more than 4096 characters of the URL
    - ``http_client``: the ``HttpClient`` to send requests with; by default
      ``make`` creates one on httpx (``pyfect-dev[httpx]``), closed with
      the client (``keep_alive``, ``max_open_connections`` and ``tls``
      configure that one only)
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)
    """

    url: str = DEFAULT_URL
    pathname: str | None = None
    username: str | None = None
    password: Redacted[str] | None = None
    access_token: Redacted[str] | None = None
    database: str | None = None
    clickhouse_settings: Settings = field(default_factory=dict[str, Setting])
    http_headers: Mapping[str, str] = field(default_factory=dict[str, str])
    application: str | None = None
    session_id: str | None = None
    role: str | Sequence[str] | None = None
    request_timeout: DurationInput | None = None
    max_open_connections: int | None = None
    compression: Compression | None = None
    keep_alive: KeepAlive | None = None
    tls: Tls | None = field(default=None, repr=False)
    log: Log | None = None
    json: JsonHandling | None = field(default=None, compare=False)
    use_multipart_params: bool = False
    use_multipart_params_auto: bool = False
    http_client: HttpClientService[HttpClientError] | None = field(default=None, compare=False)
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None
    connection: Connection = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        base, found = _parse_url(self.url)
        warnings = [
            f'"{name}" is overridden by a URL parameter.' for name in _overridden(self, found)
        ]
        pathname = found.pathname if found.pathname is not None else self.pathname
        if pathname:
            base += "/" + pathname.strip("/")
        role = self.role
        timeout = (
            found.request_timeout
            if found.request_timeout is not None
            else DEFAULT_REQUEST_TIMEOUT
            if self.request_timeout is None
            else from_input_unsafe(self.request_timeout)
        )
        compression = self.compression or {}
        keep_alive = self.keep_alive or {}
        log_level: LogLevel = _pick(found.log_level, (self.log or {}).get("level"), "WARN")
        if self.max_open_connections is not None and self.max_open_connections < 1:
            raise ValueError(
                f"max_open_connections must be at least 1, got {self.max_open_connections}"
            )
        ttl = keep_alive.get("idle_socket_ttl")
        https = base.startswith("https:")
        tls = None if self.tls is None or not https else _options.tls_context(self.tls)
        settings = {**self.clickhouse_settings, **found.settings}
        level = LOG_LEVELS[log_level]
        if level <= LOG_LEVELS["WARN"]:
            warnings += _timeout_warnings(timeout, settings)
        username = found.username if found.username is not None else self.username
        password = found.password if found.password is not None else _plain(self.password)
        access_token = (
            found.access_token if found.access_token is not None else _plain(self.access_token)
        )
        tls_credentials = None
        if tls is not None and self.http_client is None:
            if access_token is not None:
                raise ValueError(
                    "JWT auth is not supported with HTTPS connection using custom certificates"
                )
            tls_credentials = (username or "default", redacted(password or ""))
        connection = Connection(
            url=base,
            database=found.database or self.database or "default",
            authorization=_authorization(username, password, access_token),
            clickhouse_settings=settings,
            http_headers={**self.http_headers, **found.headers},
            application=found.application or self.application,
            session_id=found.session_id or self.session_id,
            role=() if role is None else (role,) if isinstance(role, str) else tuple(role),
            request_timeout=timeout,
            max_open_connections=_pick(found.max_open_connections, self.max_open_connections, 10),
            compress_request=_options.request_codec(
                _pick(found.compression_request, compression.get("request"), False)
            ),
            decompress_response=_options.response_codec(
                _pick(found.compression_response, compression.get("response"), False),
                default_client=self.http_client is None,
            ),
            keep_alive=_pick(found.keep_alive_enabled, keep_alive.get("enabled"), True),
            idle_socket_ttl=_pick(
                found.idle_socket_ttl,
                None if ttl is None else from_input_unsafe(ttl),
                DEFAULT_IDLE_SOCKET_TTL,
            ),
            tls=tls,
            tls_credentials=tls_credentials,
            log_level=level,
            json=_options.json_handling(self.json),
            use_multipart_params=self.use_multipart_params,
            use_multipart_params_auto=self.use_multipart_params_auto,
            warnings=tuple(warnings),
        )
        object.__setattr__(self, "connection", connection)


def _pick[A](from_url: A | None, given: A | None, default: A) -> A:
    return from_url if from_url is not None else given if given is not None else default


def _overridden(config: ClickhouseClientConfig, found: _FromUrl) -> list[str]:
    """The options the config sets that its URL sets again (``mergeConfigs``
    warns about each)."""
    compression = config.compression or {}
    keep_alive = config.keep_alive or {}
    pairs: list[tuple[str, object, object]] = [
        ("username", config.username, found.username),
        ("password", config.password, found.password),
        ("access_token", config.access_token, found.access_token),
        ("database", config.database, found.database),
        ("pathname", config.pathname, found.pathname),
        ("application", config.application, found.application),
        ("session_id", config.session_id, found.session_id),
        ("request_timeout", config.request_timeout, found.request_timeout),
        ("max_open_connections", config.max_open_connections, found.max_open_connections),
        ("compression.request", compression.get("request"), found.compression_request),
        ("compression.response", compression.get("response"), found.compression_response),
        ("log.level", (config.log or {}).get("level"), found.log_level),
        ("keep_alive.enabled", keep_alive.get("enabled"), found.keep_alive_enabled),
        ("keep_alive.idle_socket_ttl", keep_alive.get("idle_socket_ttl"), found.idle_socket_ttl),
    ]
    names = [name for name, given, from_url in pairs if given is not None and from_url is not None]
    names += [f"clickhouse_settings.{k}" for k in found.settings if k in config.clickhouse_settings]
    names += [f"http_headers.{k}" for k in found.headers if k in config.http_headers]
    return names


def _timeout_warnings(timeout: Duration, settings: Settings) -> list[str]:
    """``@clickhouse/client``'s warnings about a long ``request_timeout``
    without progress headers."""
    millis = timeout.to_millis()
    if millis <= _TIMEOUT_WARNING_MILLIS:
        return []
    shown = f"{js_number(millis)}ms"
    if js_string(settings.get("send_progress_in_http_headers")) != "1":
        return [
            f"request_timeout is set to {shown}, but send_progress_in_http_headers is not "
            "enabled. Long-running queries may fail with socket hang-up errors if they exceed "
            "the load balancer idle timeout. Consider enabling progress headers with "
            "clickhouse_settings: { send_progress_in_http_headers: 1, "
            "http_headers_progress_interval_ms: '<interval>' }. "
            f"See {_LONG_RUNNING} for more details."
        ]
    if "http_headers_progress_interval_ms" not in settings:
        return [
            f"request_timeout is set to {shown} and send_progress_in_http_headers is enabled, "
            "but http_headers_progress_interval_ms is not set. It is recommended to set "
            "http_headers_progress_interval_ms to a value slightly below your load balancer's "
            "idle timeout (e.g., '110000' for a 120s LB timeout). "
            f"See {_LONG_RUNNING} for more details."
        ]
    return []


__all__ = [
    "DEFAULT_IDLE_SOCKET_TTL",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_URL",
    "ClickhouseClientConfig",
    "Connection",
]
