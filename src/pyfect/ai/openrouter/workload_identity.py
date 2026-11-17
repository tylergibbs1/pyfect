"""Workload identity federation for OpenRouter (Effect's
``OpenRouterWorkloadIdentity``): authenticate the ``HttpClient`` with
access tokens exchanged for the workload's identity token at OpenRouter's
``/oauth/token`` (RFC 8693 token exchange, scope ``inference``), through a
federation policy::

    from pyfect.ai.openrouter import client, workload_identity

    client.layer().pipe(
        L.provide(
            workload_identity.layer(identity_token=read_token, federation_policy_id="...")
        )
    )
"""

from __future__ import annotations

from typing import Final, Never

from pyfect import layer as L
from pyfect._js import or_default
from pyfect.ai import workload_identity
from pyfect.ai._provider import ClientTransform
from pyfect.effect import Effect
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import Redacted

DEFAULT_API_URL: Final = "https://openrouter.ai/api/v1"


def make[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    federation_policy_id: str,
    api_url: str | None = None,
) -> Effect[ClientTransform, Never, HttpClient | R]:
    """A transform of an ``HttpClient`` that authenticates each request with
    an access token for the federation policy ``federation_policy_id``.
    ``identity_token`` (a JWT) runs again for every exchange, made at
    ``api_url`` (pass the client's own; ``https://openrouter.ai/api/v1``,
    a trailing ``/`` allowed). Tokens are cached and exchanged as
    ``pyfect.ai.workload_identity.make`` says."""

    def exchange_request(request: HttpClientRequest, subject_token: str) -> HttpClientRequest:
        return request.body_url_params(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
                "federation_policy_id": federation_policy_id,
                "scope": "inference",
            }
        )

    base = or_default(api_url, DEFAULT_API_URL)
    return workload_identity.make(
        token_url=f"{base.removesuffix('/')}/oauth/token",
        identity_token=identity_token,
        exchange_request=exchange_request,
    )


def layer[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    federation_policy_id: str,
    api_url: str | None = None,
) -> L.Layer[HttpClient, Never, HttpClient | R]:
    """The ``HttpClient`` service, authenticated as ``make`` says."""
    transform = make(
        identity_token=identity_token, federation_policy_id=federation_policy_id, api_url=api_url
    )
    return L.effect(
        HttpClient, HttpClient().flat_map(lambda client: transform.map(lambda t: t(client)))
    )


__all__ = ["layer", "make"]
