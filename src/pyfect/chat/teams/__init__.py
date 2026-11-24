"""The Microsoft Teams adapter for ``pyfect.chat`` (Effect's ``@effect/chat-teams``):
``teams_chat`` registers the adapter and serves the Bot Framework messaging endpoint."""

from pyfect.chat.teams import teams_chat
from pyfect.chat.teams.teams_chat import TeamsChat

__all__ = ["TeamsChat", "teams_chat"]
