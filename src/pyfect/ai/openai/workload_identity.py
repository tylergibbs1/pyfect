"""Workload identity federation for OpenAI (Effect's
``OpenAiWorkloadIdentity``): authenticate the ``HttpClient`` with access
tokens exchanged for the workload's identity token at OpenAI's token
endpoint (RFC 8693 token exchange), for a registered identity provider
and service account::

    from pyfect.ai.openai import client, workload_identity

    client.layer().pipe(
        L.provide(
            workload_identity.layer(
                identity_token=read_token,
                identity_provider_id="idp_...",
                service_account_id="...",
            )
        )
    )

WebSocket mode authenticates each connection when it opens, and keeps
using it after its token expires.
"""

from __future__ import annotations

from typing import Final, Literal, Never

from pyfect import layer as L
from pyfect._js import or_default
from pyfect.ai import workload_identity
from pyfect.ai._provider import ClientTransform
from pyfect.effect import Effect
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import Redacted

DEFAULT_TOKEN_URL: Final = "https://auth.openai.com/oauth/token"

type IdentityTokenType = Literal["jwt", "id_token"]


def make[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    identity_provider_id: str,
    service_account_id: str,
    identity_token_type: IdentityTokenType | None = None,
    token_url: str | None = None,
) -> Effect[ClientTransform, Never, HttpClient | R]:
    """A transform of an ``HttpClient`` that authenticates each request with
    an access token for the service account ``service_account_id``, given
    for the identity token (a JWT, or an OpenID Connect ID token with
    ``identity_token_type="id_token"``) of the identity provider
    ``identity_provider_id``. ``identity_token`` runs again for every
    exchange, made at ``token_url`` (``https://auth.openai.com/oauth/token``);
    a token whose response has no ``expires_in`` lives an hour. Tokens are
    cached and exchanged as ``pyfect.ai.workload_identity.make`` says."""
    token_type = or_default(identity_token_type, "jwt")

    def exchange_request(request: HttpClientRequest, subject_token: str) -> HttpClientRequest:
        return request.body_json_unsafe(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": subject_token,
                "subject_token_type": f"urn:ietf:params:oauth:token-type:{token_type}",
                "identity_provider_id": identity_provider_id,
                "service_account_id": service_account_id,
            }
        )

    return workload_identity.make(
        token_url=or_default(token_url, DEFAULT_TOKEN_URL),
        identity_token=identity_token,
        exchange_request=exchange_request,
        default_expires_in="1 hour",
    )


def layer[E = Never, R = Never](
    *,
    identity_token: Effect[Redacted[str], E, R],
    identity_provider_id: str,
    service_account_id: str,
    identity_token_type: IdentityTokenType | None = None,
    token_url: str | None = None,
) -> L.Layer[HttpClient, Never, HttpClient | R]:
    """The ``HttpClient`` service, authenticated as ``make`` says."""
    transform = make(
        identity_token=identity_token,
        identity_provider_id=identity_provider_id,
        service_account_id=service_account_id,
        identity_token_type=identity_token_type,
        token_url=token_url,
    )
    return L.effect(
        HttpClient, HttpClient().flat_map(lambda client: transform.map(lambda t: t(client)))
    )


__all__ = ["IdentityTokenType", "layer", "make"]
