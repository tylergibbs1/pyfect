"""Cloudflare D1 (Effect's ``@effect/sql-d1``): an ``SqlClient`` with
SQLite's SQL over D1's HTTP API, sent with the ``HttpClient`` in context::

    from pyfect.http import httpx_client
    from pyfect.sql import d1

    layer = d1.layer(
        d1.D1ClientConfig(account_id=..., database_id=..., api_token=fx.redacted.make(token))
    ).pipe(fx.provide(httpx_client.layer))

- ``client``: ``D1Client`` (an ``SqlClient`` with ``batch``, its
  ``config`` and ``api``), ``make``, ``layer``, ``layer_config``,
  ``layer_from``
- ``config``: ``D1ClientConfig``
- ``api``: ``D1Api``, the HTTP API underneath (``query``, ``raw``), its
  results (``D1Result``, ``D1RawResult``, ``D1Meta``) and ``D1ApiError``
"""

from pyfect.sql.d1 import api, client, config
from pyfect.sql.d1.api import D1Api, D1ApiError, D1Message, D1Meta, D1RawResult, D1Result
from pyfect.sql.d1.client import (
    D1Client,
    D1ClientService,
    layer,
    layer_config,
    layer_from,
    make,
)
from pyfect.sql.d1.config import D1ClientConfig

__all__ = [
    "D1Api",
    "D1ApiError",
    "D1Client",
    "D1ClientConfig",
    "D1ClientService",
    "D1Message",
    "D1Meta",
    "D1RawResult",
    "D1Result",
    "api",
    "client",
    "config",
    "layer",
    "layer_config",
    "layer_from",
    "make",
]
