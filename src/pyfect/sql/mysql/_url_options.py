"""The mysql2 options a ``mysql://`` URL's query carries (Effect passes the URL to mysql2,
which reads each query value as JSON, or else as text, and skips the keys the URL itself
names). ``ssl`` and ``connectTimeout`` are read; any other key is refused when the config is
made, so an option is never silently dropped."""

from __future__ import annotations

import contextlib
import os
import ssl
import tempfile
from collections.abc import Generator, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qsl

from pyfect import _json_text as json_text
from pyfect.duration import Duration

_URL_KEYS = frozenset(("host", "port", "database", "user", "password"))
_TLS_VERSIONS = {
    "TLSv1": ssl.TLSVersion.TLSv1,
    "TLSv1.1": ssl.TLSVersion.TLSv1_1,
    "TLSv1.2": ssl.TLSVersion.TLSv1_2,
    "TLSv1.3": ssl.TLSVersion.TLSv1_3,
}
_TLS_KEYS = frozenset(
    (
        "ca",
        "cert",
        "key",
        "passphrase",
        "rejectUnauthorized",
        "verifyIdentity",
        "ciphers",
        "minVersion",
        "maxVersion",
    )
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Tls:
    """mysql2's ``ssl`` object: PEM ``ca`` / ``cert`` / ``key``, the server's certificate
    checked unless ``reject_unauthorized`` is false, its host name only with
    ``verify_identity``."""

    ca: tuple[str, ...] = ()
    cert: str | None = None
    key: str | None = None
    passphrase: str | None = None
    reject_unauthorized: bool = True
    verify_identity: bool = False
    ciphers: str | None = None
    min_version: ssl.TLSVersion | None = None
    max_version: ssl.TLSVersion | None = None

    def context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = self.verify_identity
        if not self.reject_unauthorized:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if self.ca:
            context.load_verify_locations(cadata="\n".join(self.ca))
        else:
            context.load_default_certs()
        if self.cert is not None:
            with _pem_files(self.cert, self.key) as (cert, key):
                context.load_cert_chain(cert, key, self.passphrase)
        if self.ciphers is not None:
            context.set_ciphers(self.ciphers)
        if self.min_version is not None:
            context.minimum_version = self.min_version
        if self.max_version is not None:
            context.maximum_version = self.max_version
        return context


@dataclass(frozen=True, slots=True)
class UrlOptions:
    tls: Tls | None = None
    connect_timeout: Duration | None = None


@contextlib.contextmanager
def _pem_files(cert: str, key: str | None) -> Generator[tuple[str, str | None]]:
    """``ssl`` loads a certificate chain only from files."""
    with tempfile.TemporaryDirectory() as directory:
        paths: list[str] = []
        for name, text in (("cert.pem", cert), ("key.pem", key)):
            if text is None:
                continue
            path = os.path.join(directory, name)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                file.write(text)
            paths.append(path)
        yield paths[0], paths[1] if len(paths) > 1 else None


def _json_or_text(value: str) -> object:
    try:
        return json_text.parse(value)
    except ValueError:
        return value


def _typeof(value: object) -> str:
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case _:
            return "object"


def _text(options: Mapping[str, object], name: str) -> str | None:
    value = options.get(name)
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"ssl.{name} in the MySQL URL must be a string")


def _version(options: Mapping[str, object], name: str) -> ssl.TLSVersion | None:
    value = _text(options, name)
    if value is None:
        return None
    if value not in _TLS_VERSIONS:
        raise ValueError(f"ssl.{name} in the MySQL URL is not a TLS version: {value!r}")
    return _TLS_VERSIONS[value]


def _tls(value: object) -> Tls | None:
    if isinstance(value, str) and value:
        if value == "Amazon RDS":
            raise ValueError(
                'the "Amazon RDS" SSL profile is not bundled; pass its CA as ssl={"ca": ...}'
            )
        raise ValueError(f"Unknown SSL profile '{value}'")
    # mysql2 reads ``options.ssl || false``: an empty object is truthy in JavaScript.
    if value is None or value in (False, 0, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError(f"SSL profile must be an object, instead it's a {_typeof(value)}")
    options: dict[str, object] = value  # pyright: ignore[reportUnknownVariableType]
    unknown = sorted(set(options) - _TLS_KEYS)
    if unknown:
        raise ValueError(f"ssl options in the MySQL URL are not supported: {', '.join(unknown)}")
    ca = options.get("ca")
    match ca:
        case None:
            cas: tuple[str, ...] = ()
        case str():
            cas = (ca,)
        case list():
            items = cast("list[object]", ca)
            if not all(isinstance(c, str) for c in items):
                raise ValueError("ssl.ca in the MySQL URL must be a string or a list of strings")
            cas = tuple(cast("list[str]", items))
        case _:
            raise ValueError("ssl.ca in the MySQL URL must be a string or a list of strings")
    cert = _text(options, "cert")
    key = _text(options, "key")
    if key is not None and cert is None:
        raise ValueError("ssl.key in the MySQL URL needs ssl.cert")
    return Tls(
        ca=cas,
        cert=cert,
        key=key,
        passphrase=_text(options, "passphrase"),
        reject_unauthorized=options.get("rejectUnauthorized") is not False,
        verify_identity=bool(options.get("verifyIdentity")),
        ciphers=_text(options, "ciphers"),
        min_version=_version(options, "minVersion"),
        max_version=_version(options, "maxVersion"),
    )


def _connect_timeout(value: object) -> Duration:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"connectTimeout in the MySQL URL must be milliseconds, got {value!r}")
    return Duration(value / 1000)


def parse_query(query: str) -> UrlOptions:
    """The options of a URL's query; ``ValueError`` for one that is not read."""
    values: dict[str, object] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key not in _URL_KEYS:
            values[key] = _json_or_text(value)
    unknown = sorted(set(values) - {"ssl", "connectTimeout"})
    if unknown:
        raise ValueError(f"MySQL URL options are not supported: {', '.join(unknown)}")
    timeout = values.get("connectTimeout")
    return UrlOptions(
        tls=_tls(values.get("ssl")),
        connect_timeout=None if timeout is None else _connect_timeout(timeout),
    )
