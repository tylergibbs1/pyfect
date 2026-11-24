"""The Discord adapter for ``pyfect.chat`` (Effect's ``@effect/chat-discord``):
``discord_chat`` registers the adapter, feeds it gateway dispatches and
serves the HTTP interactions endpoint; ``discord_gateway`` is one shard of
Discord's Gateway over ``pyfect.socket``; ``discord_rest`` is the minimal REST
client the adapter is built on, for calls the adapter has no op for."""

from pyfect.chat.discord import discord_chat, discord_gateway, discord_rest
from pyfect.chat.discord.discord_chat import DiscordChat, DiscordPostOptions, MissingChannelType
from pyfect.chat.discord.discord_gateway import DiscordGateway
from pyfect.chat.discord.discord_rest import DiscordRest

__all__ = [
    "DiscordChat",
    "DiscordGateway",
    "DiscordPostOptions",
    "DiscordRest",
    "MissingChannelType",
    "discord_chat",
    "discord_gateway",
    "discord_rest",
]
