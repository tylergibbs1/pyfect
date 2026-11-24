"""Port of Effect's ``packages/chat/discord/test/commands.test.ts``: slash
commands against what Discord sent and what it took, recorded in #test of
guild 840178841540362250: ``fixtures/chat_discord/recorded/commands.json``."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from _discord_fake import (
    BOT_USER_ID,
    RECORDED_COMMANDS,
    Fake,
    discord_layer,
    error_response,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.discord import discord_chat

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

RECORDED: Any = RECORDED_COMMANDS

TOKEN = "recorded-token"
"""The fixtures' tokens are ``<redacted>``, which the adapter refuses to put in
a path: a real one is URL-safe, so the payloads here carry this one."""


def with_token(payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "token": TOKEN}


# The definitions the capture ran, from eff-3802-capture.ts.
ACTIONS = [
    ci.button("cap-ack", label="Ack").of(),
    ci.button("cap-open", label="Open modal", style="primary").of(),
]
MODAL = ci.modal(
    "cap-modal",
    title="Capture",
    submit_label="Send",
    fields={"note": ci.text_input(label="Note (type err for a field error)")},
)


def reply(command: ci.CommandInvoked) -> ci.CommandReply:
    """The capture's handler, by the command's text."""
    match command.text:
        case "public":
            return ci.respond(
                markdown="**Public answer** with _Markdown_ and buttons",
                actions=ACTIONS,
                visibility="public",
            )
        case "mention":
            return ci.respond(markdown=f"Private answer mentioning <@{command.user_id}>")
        case "modal":
            return MODAL.open()
        case "defer":
            return ci.defer(command)
        case "defer-public":
            return ci.defer(command, visibility="public")
        case _:
            return ci.respond(
                markdown=(
                    "**Private answer** with _Markdown_, a list:\n\n- one\n- two\n\nand buttons"
                ),
                actions=ACTIONS,
            )


HANDLER = ci.HandlerService(
    click=lambda _: fx.succeed(ci.ack),
    submit=lambda submitted: fx.succeed(
        ci.errors(note="That is the error you asked for")
        if submitted.values.get("note") == "err"
        else ci.close
    ),
    command=lambda command: fx.succeed(reply(command)),
    refused=lambda _, error: fx.die(error),
)


def normalize(payload: object) -> ci.Interaction:
    event = discord_chat.normalize_interaction(payload)
    assert event is not None
    return event


@testing.effect
def test_answers_each_command_and_the_submits_of_its_modal_with_the_callback_discord_took():
    """recorded slash commands / answers each command, and the submits of its modal, with the
    callback Discord took"""
    answered = [
        *(
            (what, with_token(RECORDED["commands"][what]), RECORDED["callbacks"][what]["payload"])
            for what in ["private", "public", "mention", "modal", "defer", "deferPublic"]
        ),
        # Discord has no field errors, so the errors go out as a private message that
        # notifies nobody.
        (
            "submitErrors",
            with_token(RECORDED["commandModal"]["submitErrors"]),
            RECORDED["commandModal"]["errorsCallback"]["payload"],
        ),
        (
            "submitClose",
            with_token(RECORDED["commandModal"]["submitClose"]),
            RECORDED["commandModal"]["closeCallback"]["payload"],
        ),
    ]

    @fx.gen
    def program() -> Gen[None]:
        for what, payload, callback in answered:
            fake = Fake({"createInteractionResponse": lambda *_: None})
            yield from (
                discord_chat.DiscordChat()
                .flat_map(lambda discord, payload=payload: discord.interaction(payload))
                .pipe(fx.provide_service(ci.Handler, HANDLER))
                .pipe(fx.provide(discord_layer(fake)))
            )
            assert fake.called("createInteractionResponse") == [(payload["id"], TOKEN, callback)], (
                what
            )

    return program


@testing.effect
def test_follows_up_with_the_edit_discord_took_and_is_interaction_expired_once_the_token_is_spent():
    """recorded slash commands / follows up with the edit Discord took, and is interaction_expired
    once the token is spent"""
    payload = with_token(RECORDED["commands"]["defer"])
    command = normalize(payload)
    assert isinstance(command, ci.CommandInvoked)
    deferred = ci.defer(command)

    def follow_up(fake: Fake) -> Effect[None, Any]:
        return (
            chat.Chat()
            .flat_map(
                lambda service: service.follow_up(
                    deferred, markdown="**Deferred answer** to defer, with buttons", actions=ACTIONS
                )
            )
            .pipe(fx.provide(discord_layer(fake)))
        )

    issued = (int(payload["id"]) >> 22) + 1420070400000

    @fx.gen
    def program() -> Gen[None]:
        yield from testing.set_time(issued + 4_000)
        edited = Fake(
            {"updateOriginalWebhookMessage": lambda *_: RECORDED["followUp"]["response"]["body"]}
        )
        yield from follow_up(edited)
        assert edited.called("updateOriginalWebhookMessage") == [
            (BOT_USER_ID, TOKEN, RECORDED["followUp"]["request"])
        ]
        # The edit goes with no bot token.
        assert "authorization" not in edited.requests[-1].headers

        # What Discord answered at 15.5 minutes, 401 with 50027, returned here early;
        # past 15 minutes the adapter refuses without a call.
        spent = Fake(
            {
                "updateOriginalWebhookMessage": lambda *_: error_response(
                    RECORDED["expired"]["edit"]["status"], RECORDED["expired"]["edit"]["body"]
                )
            }
        )
        mapped = yield from follow_up(spent).flip()
        yield from testing.set_time(issued + 15 * 60_000 + 30_000)
        refused = yield from follow_up(spent).flip()
        assert [
            (error.op, type(error.reason).__name__, error.reason.detail)
            for error in (mapped, refused)
        ] == [
            ("followUp", "NotFound", "interaction_expired"),
            ("followUp", "NotFound", "interaction_expired"),
        ]
        assert len(spent.called("updateOriginalWebhookMessage")) == 1

    return program
