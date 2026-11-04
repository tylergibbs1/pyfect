"""Settings of a Cloudflare D1 client (Effect's ``@effect/sql-d1``
``D1ClientConfig``).

Effect's client takes a Workers ``D1Database`` binding; pyfect's reaches
the database through D1's HTTP API, so it names the account, the database
and an API token with the ``D1 Edit`` permission instead. The HTTP API has
no prepared statements, so there is no prepare cache to configure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pyfect.redacted import Redacted

DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"
"""Cloudflare's API."""


@dataclass(frozen=True, slots=True, kw_only=True)
class D1ClientConfig:
    """Which database, and what the client does with rows and names.

    - ``account_id`` / ``database_id``: the database's account and its id
      (``wrangler d1 info``)
    - ``api_token``: a Cloudflare API token allowed to edit D1
    - ``base_url``: the API's root (Cloudflare's by default)
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename result
      columns / identifiers (``fx.case`` has the usual ones)
    """

    account_id: str
    database_id: str
    api_token: Redacted[str]
    base_url: str = DEFAULT_BASE_URL
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        for name in ("account_id", "database_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")

    @property
    def database_url(self) -> str:
        """The database's endpoint, to which ``/query`` and ``/raw`` are
        appended."""
        root = self.base_url.rstrip("/")
        return f"{root}/accounts/{self.account_id}/d1/database/{self.database_id}"


__all__ = ["DEFAULT_BASE_URL", "D1ClientConfig"]
