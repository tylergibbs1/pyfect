"""Workload identity federation for Anthropic (Effect's
``AnthropicWorkloadIdentity``): authenticate the ``HttpClient`` with
OAuth access tokens exchanged for the workload's identity token at
Anthropic's ``/v1/oauth/token``, through a federation rule::

    from pyfect.ai.anthropic import client, workload_identity

    client.layer().pipe(
        L.provide(
            workload_identity.layer(
                identity_token=read_token,
                federation_rule_id="fdrl_...",
                organization_id="...",
            )
        )
    )
"""

from __future__ import annotations

from typing import Final, Never

from pyfect import layer as L
from pyfect._js import or_default, trim
from pyfect.ai import workload_identity
from pyfect.ai._provider import ClientTransform
from pyfect.effect import Effect
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import Redacted

OAUTH_BETA: Final = "oauth-2025-04-20"
FEDERATION_BETA: Final = "oidc-federation-2026-04-01"
DEFAULT_API_URL: Final = "https://api.anthropic.com"


def _with_oauth_beta(request: HttpClientRequest) -> HttpClientRequest:
    header = request.headers.get("anthropic-beta")
    betas = [] if header is None else [beta for beta in map(trim, header.split(",")) if beta]
    if OAUTH_BETA in betas:
        return request
    return request.set_header("anthropic-beta", ",".join([*betas, OAUTH_BETA]))


def make[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    federation_rule_id: str,
    organization_id: str,
    service_account_id: str | None = None,
    workspace_id: str | None = None,
    api_url: str | None = None,
) -> Effect[ClientTransform, Never, HttpClient | R]:
    """A transform of an ``HttpClient`` that authenticates each request with
    an access token for the federation rule ``federation_rule_id``
    (``fdrl_...``) of the organization ``organization_id``, acting as the
    service account ``service_account_id`` (``svac_...``) and scoped to the
    workspace ``workspace_id`` (``wrkspc_...``, needed when the rule covers
    several), and adds the OAuth beta to its ``anthropic-beta`` header.
    ``identity_token`` runs again for every exchange, made at ``api_url``
    (pass the client's own; ``https://api.anthropic.com``). Tokens are
    cached and exchanged as ``pyfect.ai.workload_identity.make`` says."""
    ids = {"service_account_id": service_account_id, "workspace_id": workspace_id}

    def exchange_request(request: HttpClientRequest, assertion: str) -> HttpClientRequest:
        body = {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
            "federation_rule_id": federation_rule_id,
            "organization_id": organization_id,
            **{name: value for name, value in ids.items() if value is not None},
        }
        return request.set_header(
            "anthropic-beta", f"{OAUTH_BETA},{FEDERATION_BETA}"
        ).body_json_unsafe(body)

    transform = workload_identity.make(
        token_url=f"{or_default(api_url, DEFAULT_API_URL)}/v1/oauth/token",
        identity_token=identity_token,
        exchange_request=exchange_request,
    )
    return transform.map(
        lambda authenticate: lambda client: authenticate(client.map_request(_with_oauth_beta))
    )


def layer[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    federation_rule_id: str,
    organization_id: str,
    service_account_id: str | None = None,
    workspace_id: str | None = None,
    api_url: str | None = None,
) -> L.Layer[HttpClient, Never, HttpClient | R]:
    """The ``HttpClient`` service, authenticated as ``make`` says."""
    transform = make(
        identity_token=identity_token,
        federation_rule_id=federation_rule_id,
        organization_id=organization_id,
        service_account_id=service_account_id,
        workspace_id=workspace_id,
        api_url=api_url,
    )
    return L.effect(
        HttpClient, HttpClient().flat_map(lambda client: transform.map(lambda t: t(client)))
    )


__all__ = ["FEDERATION_BETA", "OAUTH_BETA", "layer", "make"]
