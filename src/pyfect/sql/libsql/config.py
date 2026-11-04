"""Settings of a libSQL client (Effect's ``LibsqlClientConfig``):
``LibsqlClientConfig`` opens a database from a URL, ``LibsqlLiveConfig``
uses a client the caller owns.

URLs are those of ``@libsql/client``, checked when the config is made:

- ``:memory:`` or ``file::memory:`` (``?cache=shared`` / ``private``): an
  in-memory database
- ``file:path.db``, ``file:///absolute/path.db``: a local file
- ``libsql://host``: a server over HTTPS (``?tls=0`` for HTTP, with an
  explicit port); ``https://`` / ``http://`` as they say. ``wss://`` /
  ``ws://`` are served over HTTPS / HTTP too, which sqld and Turso accept
  on the same address.
- ``?authToken=...`` on a remote URL overrides ``auth_token``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote, urlsplit

from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.sql.libsql._targets import LocalTarget, RemoteTarget, Target
from pyfect.sql.libsql.sdk import LibsqlSdk

_MEMORY = ":memory:"
_REMOTE_SCHEMES = {"http": "http", "https": "https", "ws": "http", "wss": "https"}


def _query(query: str) -> list[tuple[str, str]]:
    return parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query))


def _local(path: str, query: str, netloc: str, port: int | None) -> LocalTarget:
    if path == _MEMORY and not netloc:
        params: list[str] = []
        for key, value in _query(query):
            if key != "cache":
                raise ValueError(f"Unsupported URL query parameter {key!r}")
            if value not in ("shared", "private"):
                raise ValueError(
                    f'Unknown value for the "cache" query argument: {value!r}. '
                    'Supported values are: ["shared", "private"]'
                )
            params.append(f"{key}={value}")
        database = "file::memory:" + (f"?{'&'.join(params)}" if params else "")
        return LocalTarget(database, uri=True, in_memory=True)
    for key, _value in _query(query):
        if key not in ("tls", "authToken"):
            raise ValueError(f"Unsupported URL query parameter {key!r}")
    host, _, _ = netloc.rpartition("@")[2].partition(":")
    if host.lower() not in ("", "localhost"):
        raise ValueError(
            f"Invalid host in file URL: {host!r}. A file: URL with an absolute path should "
            'start with one slash ("file:/absolute/path.db") or with three slashes '
            '("file:///absolute/path.db")'
        )
    if port is not None:
        raise ValueError("File URL cannot have a port")
    if "@" in netloc:
        raise ValueError("File URL cannot have username and password")
    return LocalTarget(unquote(path), uri=False, in_memory=False)


def _remote_query(
    query: str, auth_token: str | None, tls: bool | None
) -> tuple[str | None, bool | None]:
    """``tls`` and ``authToken`` as the query sets them."""
    for key, value in _query(query):
        if key == "tls":
            if value not in ("0", "1"):
                raise ValueError(
                    f'Unknown value for the "tls" query argument: {value!r}. '
                    'Supported values are: ["0", "1"]'
                )
            tls = value == "1"
        elif key == "authToken":
            auth_token = value
        else:
            raise ValueError(f"Unsupported URL query parameter {key!r}")
    return auth_token, tls


def _http_scheme(scheme: str, tls: bool | None, port: int | None) -> str:
    if scheme == "libsql":
        if tls is not False:
            return "https"
        if port is None:
            raise ValueError('A "libsql:" URL with ?tls=0 must specify an explicit port')
        return "http"
    http = _REMOTE_SCHEMES.get(scheme)
    if http is None:
        raise ValueError(
            'The client supports only "libsql:", "wss:", "ws:", "https:", "http:" and "file:" '
            f"URLs, got {scheme + ':'!r}"
        )
    if http == "http" and tls is True:
        raise ValueError(f'A "{scheme}:" URL cannot opt into TLS by using ?tls=1')
    if http == "https" and tls is False:
        raise ValueError(f'A "{scheme}:" URL cannot opt out of TLS by using ?tls=0')
    return http


def parse_target(url: str, auth_token: str | None, tls: bool | None) -> Target:
    """Where ``url`` points; ``ValueError`` when ``@libsql/client`` would
    refuse it."""
    if url == _MEMORY:
        url = "file::memory:"
    parts = urlsplit(url)
    if not parts.scheme:
        raise ValueError(f"The URL {url!r} has no scheme (use file:, libsql:, https: or http:)")
    if parts.fragment:
        raise ValueError(f"URL fragments are not supported: {'#' + parts.fragment!r}")
    scheme = parts.scheme.lower()
    if scheme == "file":
        return _local(parts.path, parts.query, parts.netloc, parts.port)
    auth_token, tls = _remote_query(parts.query, auth_token, tls)
    http = _http_scheme(scheme, tls, parts.port)
    if parts.username is not None or parts.password is not None:
        raise ValueError(
            "This client does not support HTTP Basic authentication with a username and "
            'password. Use auth_token or the "authToken" URL query parameter.'
        )
    if not parts.hostname:
        raise ValueError(f"The URL {url!r} names no host")
    return RemoteTarget(f"{http}://{parts.netloc}{parts.path.rstrip('/')}", auth_token)


@dataclass(frozen=True, slots=True, kw_only=True)
class LibsqlClientConfig:
    """A database to open (Effect's ``LibsqlClientConfig.Full``).

    - ``url``: the database (see the module)
    - ``auth_token``: the token a remote server wants
    - ``tls``: ``False`` makes a ``libsql:`` URL use HTTP
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)

    ``target`` is where the URL points, parsed when the config is made.
    """

    url: str
    auth_token: Redacted[str] | None = None
    tls: bool | None = None
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None
    target: Target = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        token = None if self.auth_token is None else redacted_value(self.auth_token)
        object.__setattr__(self, "target", parse_target(self.url, token, self.tls))


@dataclass(frozen=True, slots=True, kw_only=True)
class LibsqlLiveConfig:
    """A client the caller owns and closes (Effect's
    ``LibsqlClientConfig.Live``); its coroutines run on pyfect's SQL loop
    thread."""

    live_client: LibsqlSdk
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None


__all__ = ["LibsqlClientConfig", "LibsqlLiveConfig", "Target", "parse_target"]
