"""Port of Effect's ``packages/chat/slack/test/commands.test.ts``: slash
commands against what Slack sent and what it took, from
``fixtures/chat_slack/recorded/commands.json``."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from urllib.parse import urlsplit

from _slack_fake import AUTH_TEST, TEAM, Fake, Status, fixture, slack_layer

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat
from pyfect.chat import chat_interaction as ci
from pyfect.chat.slack import slack_chat
from pyfect.duration import seconds

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

RECORDED: dict[str, Any] = fixture("recorded", "commands")
CHANNEL = "C0CJMJ5UMUY"

# The definitions the capture ran.
ACTIONS = [
    ci.button("cap-ack", label="Ack").of(),
    ci.button("cap-open", label="Open modal", style="primary").of(),
]


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
        case "defer":
            return ci.defer(command)
        case _:
            return ci.respond(
                markdown=(
                    "**Private answer** with _Markdown_, a list:\n\n- one\n- two\n\nand buttons"
                ),
                actions=ACTIONS,
            )


HANDLER = layer.succeed(
    ci.Handler,
    ci.HandlerService(
        click=lambda _: fx.die("unused"),
        submit=lambda _: fx.die("unused"),
        command=lambda command: fx.succeed(reply(command)),
        refused=lambda _, error: fx.die(error),
    ),
)


def normalize(payload: object) -> ci.Interaction:
    event = slack_chat.normalize_interaction(payload, team_id=TEAM)
    assert event is not None
    return event


def interact(fake: Fake, payload: object) -> Effect[Any, Any]:
    return (
        slack_chat.SlackChat()
        .flat_map(lambda slack: slack.interaction(payload, deadline=seconds(1)))
        .pipe(fx.provide(HANDLER))
        .pipe(fx.provide(slack_layer(fake)))
    )


@testing.live
def test_answers_each_command_with_the_body_slack_rendered():
    """recorded slash commands / answers each command with the body Slack rendered"""

    @fx.gen
    def program() -> Gen[None]:
        fake = Fake({"auth.test": AUTH_TEST})
        for what in ["private", "public", "mention", "defer"]:
            answer = yield from interact(fake, RECORDED["commands"][what])
            assert answer == RECORDED["answers"].get(what), what

    return program


def test_takes_a_click_on_a_private_answer_which_has_no_message_from_its_container() -> None:
    """recorded slash commands / takes a click on a private answer, which has no message, from its
    container"""
    payload = RECORDED["clicks"]["privateAnswer"]
    assert "message" not in payload
    click = normalize(payload)
    assert isinstance(click, ci.ButtonClicked)
    # The id names where the click came from. chat.update on it answered
    # message_not_found: a private answer is not a message Chat can reach.
    assert (click.id, click.message_id, click.thread.id) == (
        "cap-ack",
        payload["container"]["message_ts"],
        f"{TEAM}/{CHANNEL}",
    )


@testing.effect
def test_follows_up_with_the_body_slack_rendered_and_maps_a_spent_and_an_expired_response_url():
    """recorded slash commands / follows up with the body Slack rendered, and maps a spent and an
    expired response_url"""

    @fx.gen
    def program() -> Gen[None]:
        command = normalize(RECORDED["commands"]["defer"])
        assert isinstance(command, ci.CommandInvoked)
        deferred = ci.defer(command)

        def follow_up(answer: dict[str, Any]) -> tuple[Fake, Effect[None, Any]]:
            fake = Fake(
                {
                    "auth.test": AUTH_TEST,
                    "response_url": Status(
                        answer["status"], answer["body"], {"content-type": answer["contentType"]}
                    ),
                }
            )
            sent = (
                chat.Chat()
                .flat_map(
                    lambda service: service.follow_up(
                        deferred,
                        markdown="**Deferred answer** to defer, with buttons",
                        actions=ACTIONS,
                    )
                )
                .pipe(fx.provide(slack_layer(fake)))
            )
            return fake, sent

        fake, sent = follow_up(RECORDED["responseUrl"]["followUp"]["response"])
        yield from sent
        [call] = fake.called("response_url")
        body = dict(call.params)
        url = body.pop("url")
        assert isinstance(command.raw, dict)
        assert url == urlsplit(str(command.raw["response_url"])).geturl()
        assert body == RECORDED["responseUrl"]["followUp"]["request"]

        for answer in [
            RECORDED["responseUrl"]["spent"]["response"],
            RECORDED["responseUrl"]["expired"]["responses"][0],
        ]:
            error = yield from follow_up(answer)[1].flip()
            assert (
                error.op,
                type(error.reason).__name__,
                error.reason.detail,
                error.reason.cause,
            ) == (
                "followUp",
                "NotFound",
                "interaction_expired",
                answer["body"],
            )

    return program
