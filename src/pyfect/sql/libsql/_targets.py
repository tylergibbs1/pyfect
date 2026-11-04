"""Where a libSQL database is, once its URL is parsed."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocalTarget:
    """A local database: ``sqlite3.connect``'s ``database`` and ``uri``."""

    database: str
    uri: bool
    in_memory: bool


@dataclass(frozen=True, slots=True)
class RemoteTarget:
    """A server's base URL (``http(s)://host[:port][/path]``) and token."""

    base_url: str
    auth_token: str | None


type Target = LocalTarget | RemoteTarget


__all__ = ["LocalTarget", "RemoteTarget", "Target"]
