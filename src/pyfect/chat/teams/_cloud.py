"""The configuration a Teams layer is built from: the cloud and the
credentials. Nothing here is ever read from an activity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from pyfect._core import Effect
from pyfect.chat.chat_error import ChatError
from pyfect.redacted import Redacted


@dataclass(frozen=True, kw_only=True)
class Cloud:
    """The endpoints and host allowlists of one Microsoft cloud.

    - ``connector_url`` is where thread ops go, such as
      ``https://smba.trafficmanager.net/teams``. Ops tied to an inbound
      activity (an invoke's answer, a command's answer, ``follow_up``) go to
      that activity's ``serviceUrl``, which must be ``https:`` on the
      default port with a host exactly in ``connector_hosts``, checked
      before a token is attached. There is no fallback from one to the
      other.
    - ``open_id_metadata_url`` and ``issuer`` check inbound tokens. The
      metadata's ``jwks_uri`` must be on the metadata's own host.
    - ``login_url`` is the Entra authority without the tenant, and
      ``connector_scope`` the scope of a Connector token.
    - ``file_host_suffixes`` (matched at a label boundary) and
      ``redirect_hosts`` (exact) bound downloads.
    """

    connector_url: str
    connector_hosts: tuple[str, ...]
    open_id_metadata_url: str
    issuer: str
    login_url: str
    connector_scope: str
    file_host_suffixes: tuple[str, ...]
    redirect_hosts: tuple[str, ...] = field(default=())


PUBLIC_CLOUD = Cloud(
    connector_url="https://smba.trafficmanager.net/teams",
    connector_hosts=("smba.trafficmanager.net",),
    open_id_metadata_url="https://login.botframework.com/v1/.well-known/openidconfiguration",
    issuer="https://api.botframework.com",
    login_url="https://login.microsoftonline.com",
    connector_scope="https://api.botframework.com/.default",
    file_host_suffixes=("sharepoint.com",),
)
"""The public Azure cloud: Connector ``smba.trafficmanager.net``, Bot
Framework's OpenID metadata, Entra at ``login.microsoftonline.com``, and
``sharepoint.com`` for files. No extra redirect hosts."""


@dataclass(frozen=True)
class TokenGrant:
    """A Connector token from a credentials provider. A grant without
    ``expires_at`` is not cached."""

    token: Redacted[str]
    expires_at: datetime | None = None


type Credentials = Redacted[str] | Callable[[str], Effect[TokenGrant, ChatError]]
"""The bot's client secret, for client credentials against the tenant, or a
provider that gets a token for a scope, for certificates or managed
identities. A token is cached until five minutes before it expires."""


@dataclass(frozen=True, kw_only=True)
class Unverified:
    """Capabilities whose live checks have not passed. Each is off by default
    and, when off, is absent from the descriptor and its op fails
    ``Unsupported``.

    - ``buttons``: buttons and link buttons on a card. Needs
      ``interaction_keys``. Selects are never supported.
    - ``modals``: dialogs opened by the buttons named in ``modal_buttons``,
      with field errors. Needs ``buttons``.
    - ``commands``: agent slash commands, answered in private or in public,
      and ``follow_up`` for 24 hours. Also turns on ``ephemeral``.
    - ``start_thread``: the reply chain under a channel post.
    - ``download``: files on inbound messages.
    """

    buttons: bool = False
    modals: bool = False
    commands: bool = False
    start_thread: bool = False
    download: bool = False
