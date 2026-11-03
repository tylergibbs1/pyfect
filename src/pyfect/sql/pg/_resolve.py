"""From a ``PgConnectionConfig`` to libpq's connection parameters (Effect's
``internal/config``): the URL parsed, explicit fields over it, and every
check made before connecting."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qsl, unquote, urlsplit

from pyfect._core import Effect
from pyfect._digits import parse_digits
from pyfect.duration import Seconds, to_seconds
from pyfect.effect import fail, succeed
from pyfect.redacted import Redacted, make
from pyfect.redacted import value as redacted_value
from pyfect.sql.error import SqlError
from pyfect.sql.pg.config import Password, PgConnectionConfig
from pyfect.sql.pg.error import connection_error

_DEFAULT_TIMEOUT = 5.0
_MAX_KEEP_ALIVE = 0x7FFFFFFF
_RESERVED = frozenset(("user", "database", "replication", "options"))
_SOCKET_FILE = re.compile(r"^(.*)/\.s\.PGSQL\.([0-9]+)$")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """libpq's parameters (without the password), the password and the
    connect timeout."""

    params: dict[str, str]
    password: Password | None
    connect_timeout: Seconds
    host: str
    port: int


class _Invalid(Exception):
    pass


def _error(message: str) -> SqlError:
    return connection_error(f"PgConnection: {message}", "connect")


@dataclass(slots=True)
class _Url:
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    application_name: str | None = None
    options: str | None = None
    connect_timeout: Seconds | None = None
    ssl: bool | Literal["prefer"] | None = None


def _decode(value: str, what: str) -> str:
    if _BAD_PERCENT.search(value):
        raise _Invalid(f"Invalid percent-encoding in URL {what}")
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError as cause:
        raise _Invalid(f"Invalid percent-encoding in URL {what}") from cause


def _port(value: str, what: str) -> int:
    port = parse_digits(value)
    if port is None or not 1 <= port <= 65535:
        raise _Invalid(f'Invalid port in URL {what}: "{value}"')
    return port


_SSLMODES: dict[str, bool | Literal["prefer"]] = {
    "disable": False,
    "require": True,
    "verify-ca": True,
    "verify-full": True,
    "prefer": "prefer",
    "allow": "prefer",
}


def _query(url: _Url, key: str, value: str) -> None:
    match key:
        case "host":
            url.host = value
        case "port":
            url.port = _port(value, "port parameter")
        case "user":
            url.username = value
        case "password":
            url.password = value
        case "dbname":
            url.database = value
        case "application_name":
            url.application_name = value
        case "options":
            url.options = value
        case "connect_timeout":
            seconds = parse_digits(value)
            if seconds is None:
                raise _Invalid(f'Invalid connect_timeout in URL: "{value}"')
            url.connect_timeout = Seconds(math.inf if seconds == 0 else seconds)
        case "sslmode":
            if value not in _SSLMODES:
                raise _Invalid(f'Unrecognized sslmode in URL: "{value}"')
            url.ssl = _SSLMODES[value]
        case _:
            # Unknown parameters are ignored, as libpq ignores them.
            pass


def _parse_url(raw: str) -> _Url:
    try:
        parts = urlsplit(raw)
    except ValueError as cause:
        raise _Invalid("Invalid connection URL") from cause
    if parts.scheme not in ("postgres", "postgresql"):
        raise _Invalid(f'Unsupported connection URL protocol: "{parts.scheme}:"')
    url = _Url()
    userinfo, _, hostport = parts.netloc.rpartition("@")
    if hostport.startswith("["):
        host, _, rest = hostport[1:].partition("]")
        port = rest.removeprefix(":")
        url.host = host or None
    else:
        host, _, port = hostport.partition(":")
        if host:
            url.host = _decode(host, "host")
    if port:
        url.port = _port(port, "authority")
    if userinfo:
        username, _, password = userinfo.partition(":")
        if username:
            url.username = _decode(username, "username")
        if password:
            url.password = _decode(password, "password")
    database = _decode(parts.path.removeprefix("/"), "database")
    if database:
        url.database = database
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        _query(url, key, value)
    return url


def _keep_alive(config: PgConnectionConfig) -> int | None:
    if config.keep_alive is None:
        return None
    seconds = to_seconds(config.keep_alive)
    whole = math.floor(seconds) if math.isfinite(seconds) else 0
    if not 1 <= whole <= _MAX_KEEP_ALIVE:
        raise _Invalid("keep_alive must be between 1 and 2147483647 seconds")
    return whole


def _escape_option(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\ ")


def _startup_options(config: PgConnectionConfig, url: _Url) -> tuple[str | None, str | None]:
    """The session defaults as libpq ``options`` (``-c name=value`` each,
    then ``startup_options``), and the ``application_name`` among them."""
    named: dict[str, str] = {}
    for name, value in config.startup_parameters.items():
        key = name.lower()
        if key in _RESERVED:
            raise _Invalid(f'Reserved startup parameter: "{name}"')
        if key == "client_encoding":
            if value.upper() not in ("UTF8", "UTF-8"):
                raise _Invalid("Startup parameter client_encoding must be UTF8 or UTF-8")
            continue
        if not name or "\0" in name or "\0" in value:
            raise _Invalid(
                "Startup parameter names must be nonempty and names/values must not contain NUL"
            )
        named[key] = value
    application_name = named.pop("application_name", None)
    flags = [f"-c {_escape_option(f'{key}={value}')}" for key, value in named.items()]
    opaque = config.startup_options if config.startup_options is not None else url.options
    if opaque:
        flags.append(opaque)
    return (" ".join(flags) or None), application_name


def _ssl(config: PgConnectionConfig, url: _Url) -> dict[str, str]:
    ssl = config.ssl
    if ssl is None:
        match url.ssl:
            case None | False:
                return {"sslmode": "disable"}
            case "prefer":
                return {"sslmode": "prefer"}
            case True:
                ssl = True
    if ssl is False:
        return {"sslmode": "disable"}
    if ssl is True:
        return {"sslmode": "verify-full", "sslrootcert": "system"}
    return {"sslmode": "verify-full", **ssl}


def _place(config: PgConnectionConfig, url: _Url) -> tuple[str, int]:
    """libpq's host (a socket directory for a socket) and port."""
    port = config.port or url.port or 5432
    if config.path is None:
        return config.host or url.host or "localhost", port
    socket = _SOCKET_FILE.match(config.path)
    if socket is None:
        raise _Invalid(f'The socket path "{config.path}" is not named .s.PGSQL.<port>')
    return socket[1] or "/", int(socket[2])


def _resolve(config: PgConnectionConfig) -> ResolvedConfig:
    url = _parse_url(redacted_value(config.url)) if config.url is not None else _Url()
    host, port = _place(config, url)
    username = (
        config.username or url.username or os.environ.get("USER") or os.environ.get("USERNAME")
    )
    if username is None:
        raise _Invalid("No username configured")
    keep_alive = _keep_alive(config)
    options, named_application = _startup_options(config, url)
    application_name = (
        config.application_name or named_application or url.application_name or "pyfect"
    )
    params = {
        "host": host,
        "port": str(port),
        "user": username,
        "dbname": config.database or url.database,
        "application_name": application_name,
        "options": options,
        "client_encoding": "UTF8",
    }
    for name, param in params.items():
        if param is not None and "\0" in param:
            raise _Invalid(f'Startup parameter "{name}" must not contain NUL')
    resolved = {name: param for name, param in params.items() if param is not None}
    resolved.update(_ssl(config, url))
    if keep_alive is not None:
        resolved.update(keepalives="1", keepalives_idle=str(keep_alive))
    password: Password | None = config.password
    if password is None and url.password is not None:
        password = make(url.password)
    timeout = (
        to_seconds(config.connect_timeout)
        if config.connect_timeout is not None
        else url.connect_timeout or Seconds(_DEFAULT_TIMEOUT)
    )
    return ResolvedConfig(resolved, password, timeout, host, port)


def resolve_password(password: Password | None) -> Effect[str | None]:
    """The password's text; an effect runs each time."""
    if password is None:
        return succeed(None)
    if isinstance(password, Redacted):
        return succeed(redacted_value(password))
    return password.map(redacted_value)


def resolve(config: PgConnectionConfig) -> Effect[ResolvedConfig, SqlError]:
    """The connection's parameters, or a ``ConnectionError`` saying what is
    wrong with ``config``."""

    def body() -> Effect[ResolvedConfig, SqlError]:
        try:
            return succeed(_resolve(config))
        except _Invalid as invalid:
            return fail(_error(str(invalid)))

    from pyfect.effect import suspend

    return suspend(body)


__all__ = ["ResolvedConfig", "resolve", "resolve_password"]
