"""Port of Effect's ``packages/chat/discord/test/interactions.test.ts``: the
interaction normaliser, the gateway interaction entry's deadline and answers,
``command_requests`` and ``follow_up`` on a 429."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from _discord_fake import (
    BOT_USER_ID,
    GUILD,
    RECORDED_COMMANDS,
    SCRATCH,
    TIM,
    Fake,
    Status,
    discord_layer,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.discord import discord_chat
from pyfect.chat.discord.discord_chat import DiscordPostOptions
from pyfect.duration import Duration, seconds, zero

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

MESSAGE = {"id": "1570700000000000001", "channel_id": SCRATCH}


def click(data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "1570700000000000100",
        "application_id": BOT_USER_ID,
        "type": 3,
        "token": "token",
        "version": 1,
        "guild_id": GUILD,
        "channel_id": SCRATCH,
        "member": {"user": {"id": TIM}},
        "message": MESSAGE,
        "data": data,
        **extra,
    }


def submit(components: list[Any]) -> dict[str, Any]:
    return click({"custom_id": "form", "components": components}, type=5)


def slash(name: str, options: list[Any] | None = None, **data: Any) -> dict[str, Any]:
    return {
        **RECORDED_COMMANDS["commands"]["private"],
        "id": "1570700000000000100",
        "token": "token",
        "data": {
            "id": "1570700000000000900",
            "name": name,
            "type": 1,
            **({} if options is None else {"options": options}),
            **data,
        },
    }


def some(raw: object) -> ci.Interaction:
    found = discord_chat.normalize_interaction(raw)
    assert found is not None
    return found


# --- normalizeInteraction --------------------------------------------------------------


def test_a_button_splits_its_custom_id_into_id_and_value_at_the_first_join() -> None:
    """normalizeInteraction / a button splits its custom_id into id and value at the first join,
    from a member or a direct's user"""
    raw = click({"custom_id": "go␟a␟b", "component_type": 2})
    direct = {key: value for key, value in raw.items() if key != "member"}
    for found in (raw, {**direct, "user": {"id": TIM}}):
        clicked = some(found)
        assert clicked == ci.ButtonClicked(
            id="go",
            value="a␟b",
            thread=discord_chat.thread(SCRATCH),
            message_id=MESSAGE["id"],
            user_id=TIM,
            raw=clicked.raw,
        )


def test_a_submit_reads_each_input_a_labels_or_an_action_rows_and_leaves_an_empty_one_out() -> None:
    """normalizeInteraction / a submit reads each input, a Label's or an action row's, and leaves
    an empty one out"""
    submitted = some(
        submit(
            [
                {"type": 10},
                {"type": 18, "component": {"type": 4, "custom_id": "name", "value": "Tim"}},
                {"type": 18, "component": {"type": 4, "custom_id": "note", "value": ""}},
                {"type": 18, "component": {"type": 3, "custom_id": "size", "values": ["l"]}},
                {"type": 18, "component": {"type": 3, "custom_id": "none", "values": []}},
                {"type": 1, "components": [{"type": 4, "custom_id": "old", "value": "row"}]},
            ]
        )
    )
    assert isinstance(submitted, ci.ModalSubmitted)
    assert dict(submitted.values) == {"name": "Tim", "size": "l", "old": "row"}


def test_a_submit_keeps_an_input_whose_id_is_proto_as_its_own_field() -> None:
    """normalizeInteraction / a submit keeps an input whose id is __proto__ as its own field"""
    submitted = some(
        submit(
            [
                {
                    "type": 18,
                    "component": {"type": 4, "custom_id": "__proto__", "value": "answered"},
                },
                {"type": 18, "component": {"type": 4, "custom_id": "name", "value": "Tim"}},
            ]
        )
    )
    assert isinstance(submitted, ci.ModalSubmitted)
    assert list(submitted.values.items()) == [("__proto__", "answered"), ("name", "Tim")]


def test_anything_not_from_an_element_the_adapter_built_or_a_command_it_cant_express_is_none() -> (
    None
):
    """normalizeInteraction / anything not from an element the adapter built, or a command it can't
    express, is None"""
    no_message = {
        key: value
        for key, value in click({"custom_id": "go", "component_type": 2}).items()
        if key != "message"
    }
    for raw in [
        # A user command, and a slash command with an integer option.
        slash("profile", None, type=2),
        slash("roll", [{"type": 4, "name": "sides", "value": 6}]),
        # Autocomplete for a command.
        {
            **slash("deploy", [{"type": 3, "name": "version", "value": "v", "focused": True}]),
            "type": 4,
        },
        # A user select, and a click with no message.
        click({"custom_id": "users", "component_type": 5, "values": [TIM]}),
        no_message,
    ]:
        assert discord_chat.normalize_interaction(raw) is None


# --- interaction -----------------------------------------------------------------------


def handler(*, delay: Duration = zero, command: ci.CommandReply | None = None) -> ci.HandlerService:
    return ci.HandlerService(
        click=lambda _: fx.sleep(delay).as_(ci.ack),
        submit=lambda _: fx.succeed(ci.close),
        command=lambda _: fx.succeed(command if command is not None else ci.ack),
        refused=lambda _, error: fx.die(error),
    )


def deliver(
    fake: Fake, raw: object, service: ci.HandlerService, deadline: Duration | None = None
) -> Effect[None, Any]:
    return (
        discord_chat.DiscordChat()
        .flat_map(
            lambda discord: (
                discord.interaction(raw)
                if deadline is None
                else discord.interaction(raw, deadline=deadline)
            )
        )
        .pipe(fx.provide_service(ci.Handler, service))
        .pipe(fx.provide(discord_layer(fake)))
    )


def answering() -> Fake:
    return Fake({"createInteractionResponse": lambda *_: None})


def payloads(fake: Fake) -> list[Any]:
    return [payload for _id, _token, payload in fake.called("createInteractionResponse")]


@testing.effect
def test_sends_nothing_when_the_handler_misses_its_deadline_2_seconds_by_default():
    """interaction / sends nothing when the handler misses its deadline, 2 seconds by default"""

    @fx.gen
    def program() -> Gen[None]:
        fake = answering()
        late = handler(delay=seconds(3))
        fiber = yield from deliver(
            fake, click({"custom_id": "go", "component_type": 2}), late
        ).fork()
        yield from testing.adjust("2 seconds")
        yield from fiber.join()
        assert payloads(fake) == []
        longer = yield from deliver(
            fake, click({"custom_id": "go", "component_type": 2}), late, seconds(5)
        ).fork()
        yield from testing.adjust("3 seconds")
        yield from longer.join()
        assert payloads(fake) == [{"type": 6}]

    return program


@testing.effect
def test_with_post_options_does_not_reach_a_commands_answer_which_notifies_nobody():
    """interaction / withPostOptions does not reach a command's answer, which notifies nobody"""

    @fx.gen
    def program() -> Gen[None]:
        fake = answering()
        yield from deliver(
            fake,
            slash("summarize"),
            handler(command=ci.respond(markdown="Hi", visibility="public")),
        ).pipe(
            discord_chat.with_post_options(
                DiscordPostOptions(suppress_embeds=False, notify_everyone=True)
            )
        )
        assert payloads(fake) == [
            {
                "type": 4,
                "data": {
                    "content": "Hi",
                    "allowed_mentions": {
                        "parse": [],
                        "users": [],
                        "roles": [],
                        "replied_user": False,
                    },
                    "flags": 4,
                },
            }
        ]

    return program


def test_command_requests_gives_a_chat_input_command_per_definition() -> None:
    """commandRequests gives a CHAT_INPUT command per definition, with one STRING option for an
    argument"""
    group = ci.group(
        ci.command("summarize", description="Summarize this thread"),
        ci.button("go", label="Go"),
        ci.command(
            "note",
            description="Add a note",
            argument=ci.CommandArgument(name="text", description="The note"),
        ),
    )
    assert discord_chat.command_requests(group) == [
        {"type": 1, "name": "summarize", "description": "Summarize this thread"},
        {
            "type": 1,
            "name": "note",
            "description": "Add a note",
            "options": [{"type": 3, "name": "text", "description": "The note", "required": False}],
        },
    ]


@testing.effect
def test_follow_up_sends_one_http_request_on_a_429_just_before_15_minutes_and_fails_rate_limited():
    """followUp sends one HTTP request on a 429 just before 15 minutes, and fails RateLimited"""
    command = some(slash("summarize"))
    assert isinstance(command, ci.CommandInvoked)
    deferred = ci.defer(command, visibility="public")
    issued = (1570700000000000100 >> 22) + 1420070400000
    fake = Fake(
        {
            "updateOriginalWebhookMessage": lambda *_: Status(
                429,
                {"message": "You are being rate limited.", "retry_after": 0.6, "global": False},
                {"retry-after": "0.6"},
            )
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        yield from testing.set_time(issued + 15 * 60_000 - 300)
        fiber = yield from (
            chat.Chat()
            .flat_map(lambda service: service.follow_up(deferred, markdown="Done"))
            .pipe(fx.provide(discord_layer(fake)))
            .flip()
            .fork()
        )
        yield from testing.adjust("10 seconds")
        error = yield from fiber.join()
        assert [error.op, type(error.reason).__name__] == ["followUp", "RateLimited"]
        [request] = [r for r in fake.requests if "/webhooks/" in r.url]
        assert request.url == (
            f"https://discord.com/api/v10/webhooks/{BOT_USER_ID}/token/messages/@original"
        )
        assert "authorization" not in request.headers
        assert len(fake.called("updateOriginalWebhookMessage")) == 1

    return program
