"""Settings of a ClickHouse client (Effect's ``ClickhouseClientConfig``, the
options of ``@clickhouse/client``'s ``createClient``).

The URL is parsed when the config is made, with ``@clickhouse/client``'s
rules: ``http[s]://[username:password@]host:port[/database]``, its query
naming settings (``clickhouse_setting_<name>`` or ``ch_<name>``), headers
(``http_header_<name>``), ``application``, ``pathname``, ``session_id``,
``request_timeout`` (milliseconds) and ``access_token``; its agent and
logger options (``compression_*``, ``keep_alive_enabled``,
``max_open_connections``, ``log_level``) fail as not offered, any other
parameter as unknown. What the URL says overrides the fields of the same
name. ``connection`` is the result.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, unquote, urlsplit

from pyfect._js import text_encode
from pyfect.duration import Duration, Seconds, from_millis, to_seconds
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as redacted_value
from pyfect.sql.clickhouse.params import Setting, Settings

if TYPE_CHECKING:
    from pyfect.http.client import HttpClientService
    from pyfect.http.error import HttpClientError

DEFAULT_URL = "http://localhost:8123"
DEFAULT_REQUEST_TIMEOUT = Seconds(30.0)

_SETTING_PREFIXES = ("clickhouse_setting_", "ch_")
_HEADER_PREFIX = "http_header_"
_NOT_OFFERED = frozenset(
    {
        "max_open_connections",
        "compression_request",
        "compression_response",
        "log_level",
        "keep_alive_enabled",
    }
)
"""``@clickhouse/client``'s URL options for its own HTTP agent and logger."""


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
    request_timeout: Seconds


@dataclass(slots=True)
class _FromUrl:
    username: str | None = None
    password: str | None = None
    access_token: str | None = None
    database: str | None = None
    pathname: str | None = None
    application: str | None = None
    session_id: str | None = None
    request_timeout: Seconds | None = None
    settings: dict[str, Setting] = field(default_factory=dict[str, Setting])
    headers: dict[str, str] = field(default_factory=dict[str, str])


def _timeout(value: str) -> Seconds:
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
    return from_millis(millis)


def _query(query: str, found: _FromUrl) -> None:
    unknown: list[str] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        prefix = next((p for p in _SETTING_PREFIXES if key.startswith(p)), None)
        if prefix is not None:
            found.settings[key.removeprefix(prefix)] = value
        elif key.startswith(_HEADER_PREFIX):
            found.headers[key.removeprefix(_HEADER_PREFIX)] = value
        elif key == "application":
            found.application = value
        elif key == "pathname":
            found.pathname = value
        elif key == "session_id":
            found.session_id = value
        elif key == "request_timeout":
            found.request_timeout = _timeout(value)
        elif key == "access_token":
            found.access_token = value
        else:
            unknown.append(key)
    offered = [key for key in unknown if key in _NOT_OFFERED]
    if offered:
        raise ValueError(
            f"@clickhouse/client URL parameters not offered here: {', '.join(offered)}"
        )
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
    - ``http_client``: the ``HttpClient`` to send requests with; by default
      ``make`` creates one on httpx (``pyfect-dev[httpx]``), closed with
      the client
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
    request_timeout: Duration | None = None
    http_client: HttpClientService[HttpClientError] | None = field(default=None, compare=False)
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None
    connection: Connection = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        base, found = _parse_url(self.url)
        pathname = found.pathname if found.pathname is not None else self.pathname
        if pathname:
            base += "/" + pathname.strip("/")
        role = self.role
        timeout = (
            found.request_timeout
            if found.request_timeout is not None
            else DEFAULT_REQUEST_TIMEOUT
            if self.request_timeout is None
            else to_seconds(self.request_timeout)
        )
        connection = Connection(
            url=base,
            database=found.database or self.database or "default",
            authorization=_authorization(
                found.username if found.username is not None else self.username,
                found.password if found.password is not None else _plain(self.password),
                found.access_token if found.access_token is not None else _plain(self.access_token),
            ),
            clickhouse_settings={**self.clickhouse_settings, **found.settings},
            http_headers={**self.http_headers, **found.headers},
            application=found.application or self.application,
            session_id=found.session_id or self.session_id,
            role=() if role is None else (role,) if isinstance(role, str) else tuple(role),
            request_timeout=timeout,
        )
        object.__setattr__(self, "connection", connection)


__all__ = ["DEFAULT_REQUEST_TIMEOUT", "DEFAULT_URL", "ClickhouseClientConfig", "Connection"]
