"""Port of Effect's ``packages/chat/discord/test/conformance.test.ts``: the
conformance rules for files, buttons, modals and commands, against the adapter
over a stubbed REST API that keeps what was posted. Clicks and submits are
built from the posted components and go through ``DiscordChatService.interaction``,
so the callback answers are tested too."""

from __future__ import annotations

import pytest
from _discord_fake import SCRATCH, Discord, discord_layer

import pyfect as fx
from pyfect import testing
from pyfect.chat import chat_test
from pyfect.chat.discord import discord_chat


def portable(name: str) -> bool:
    return (
        name == "post/refusedFile"
        or name.startswith(("actions/", "modal/", "command/"))
        or (name.startswith("edit/") and name.endswith("Actions"))
        or (name.startswith("descriptor/measure") and name.endswith("Actions"))
        or name
        in (
            "unsupported/buttons",
            "unsupported/selects",
            "unsupported/modals",
            "unsupported/commands",
            "unsupported/ephemeral",
        )
    )


def rules(discord: Discord) -> dict[str, chat_test.Rule]:
    return chat_test.conformance(
        platform="discord",
        thread=discord_chat.thread(SCRATCH),
        user_posts=lambda _thread, _text: fx.die("unused"),
        parse_mention=discord_chat.parse_mention,
        refuse_files=discord.refuse_files,
        interactions=discord.interactions,
    )


NAMES = [name for name in rules(Discord()) if portable(name)]


@pytest.mark.parametrize("name", NAMES)
@testing.effect
def test_conformance_over_the_stubbed_discord_rest(name: str):
    """conformance over the stubbed DiscordREST / {name}"""
    discord = Discord()
    return discord.bind.flat_map(lambda _: rules(discord)[name]).pipe(
        fx.provide(discord_layer(discord.fake))
    )
