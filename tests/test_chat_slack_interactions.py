"""Port of Effect's ``packages/chat/slack/test/interactions.test.ts``:
Interactivity, from the normaliser on built payloads to the answers
``SlackChatService.interaction`` gives, ``layer_interactivity`` over HTTP and a
command's ``follow_up``. The recorded command payloads are in
``test_chat_slack_commands.py``."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Generator
from typing import Any
from urllib.parse import urlencode

from _slack_fake import (
    APP_ID,
    AUTH_TEST,
    CHANNEL,
    RESPONSE_URL,
    TEAM,
    Fake,
    command_fields,
    slack_layer,
    unix_now,
)

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat, chat_ui
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat_error import ChatError
from pyfect.chat.slack import slack_chat
from pyfect.crypto.native import layer_mac
from pyfect.duration import millis
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

JOIN = "␟"
USER = {"id": "U080YLYB277", "username": "tim", "team_id": TEAM}


def click(action: dict[str, Any], message: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "block_actions",
        "api_app_id": APP_ID,
        "token": "verification",
        "trigger_id": "trigger-1",
        "user": USER,
        "team": {"id": TEAM},
        "container": {"type": "message", "message_ts": "1794600001.000100", "channel_id": CHANNEL},
        "channel": {"id": CHANNEL},
        "message": {"ts": "1794600001.000100", **(message or {})},
        "actions": [{"block_id": "chat1", **action}],
    }


def submit(private_metadata: str, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "view_submission",
        "api_app_id": APP_ID,
        "user": USER,
        "team": {"id": TEAM},
        "trigger_id": "trigger-2",
        "view": {
            "id": "V1",
            "callback_id": "form",
            "private_metadata": private_metadata,
            "state": {"values": values},
        },
        "response_urls": [],
    }


def input_(value: str | None) -> dict[str, Any]:
    return {"field": {"type": "plain_text_input", "value": value}}


def normalize(payload: object) -> ci.Interaction | None:
    return slack_chat.normalize_interaction(payload, team_id=TEAM)


def test_ignores_what_the_adapter_did_not_build() -> None:
    """normalizeInteraction / ignores what the adapter did not build"""
    assert (
        normalize(click({"type": "button", "action_id": JOIN + "0", "url": "https://x.test"}))
        is None
    )
    assert normalize(click({"type": "button", "action_id": "go", "block_id": "theirs"})) is None
    assert normalize(submit("theirs", {})) is None


def test_gives_a_click_on_a_threads_root_the_channel_and_a_raw_payload_without_the_token() -> None:
    """normalizeInteraction / gives a click on a thread's root the channel, and a raw payload
    without the token"""
    event = normalize(
        click({"type": "button", "action_id": "go"}, {"thread_ts": "1794600001.000100"})
    )
    assert event is not None
    assert event.thread.id == f"{TEAM}/{CHANNEL}"
    assert isinstance(event.raw, dict)
    assert "token" not in event.raw


def test_gives_a_submit_the_consumers_metadata_which_may_hold_the_join_and_own_keys_only() -> None:
    """normalizeInteraction / gives a submit the consumer's metadata, which may hold the join, and
    own keys only"""
    metadata = f"a{JOIN}b"
    packed = JOIN.join(["chat1", CHANNEL, "1794600000.000100", "1794600001.000100", metadata])
    # As JSON.parse gives it, with `__proto__` an own key.
    values = json.loads(
        json.dumps(
            {
                "proto": input_("own"),
                "empty": input_(None),
                "pick": {"pick": {"type": "static_select", "selected_option": {"value": "b"}}},
                "none": {"none": {"type": "static_select", "selected_option": None}},
            }
        ).replace('"proto"', '"__proto__"')
    )
    event = normalize(submit(packed, values))
    assert isinstance(event, ci.ModalSubmitted)
    assert event.metadata == metadata
    assert event.values["__proto__"] == "own"
    assert sorted(event.values) == ["__proto__", "pick"]


class Recording:
    """A ``Handler`` whose replies a test sets, recording what it refuses."""

    def __init__(self) -> None:
        self.refused: list[ChatError] = []
        self.click: Callable[[], Effect[ci.ClickReply]] = lambda: fx.succeed(ci.ack)
        self.submit: Callable[[], Effect[ci.SubmitReply]] = lambda: fx.succeed(ci.close)
        self.command: Callable[[ci.CommandInvoked], Effect[ci.CommandReply]] = lambda _: fx.succeed(
            ci.ack
        )

    def _command(self, event: ci.CommandInvoked) -> Effect[ci.CommandReply]:
        return self.command(event)

    @property
    def layer(self) -> layer.Layer[ci.Handler]:
        return layer.succeed(
            ci.Handler,
            ci.HandlerService(
                click=lambda _: self.click(),
                submit=lambda _: self.submit(),
                command=self._command,
                refused=lambda _, error: fx.sync(lambda: self.refused.append(error)),
            ),
        )


MODAL = chat_ui.Modal(
    id="form", title="Form", elements=(chat_ui.TextInput(id="field", label="Field"),)
)

PACKED = JOIN.join(["chat1", CHANNEL, "", "1794600001.000100", ""])
"""What the adapter packs for a modal a click on a channel message opened."""


def interact(fake: Fake, handler: Recording, payload: object) -> Effect[Any, Any]:
    @fx.gen
    def run() -> Gen[Any]:
        slack = yield from slack_chat.SlackChat()
        return (yield from slack.interaction(payload, deadline=millis(50)))

    return run.pipe(fx.provide(handler.layer)).pipe(fx.provide(slack_layer(fake)))


@testing.live
def test_gives_late_for_a_late_submit_and_nothing_for_a_late_click():
    """SlackChat.interaction / gives Late for a late submit and nothing for a late click"""

    @fx.gen
    def program() -> Gen[None]:
        fake = Fake({"auth.test": AUTH_TEST})
        handler = Recording()
        handler.submit = lambda: fx.never.as_(ci.close)
        handler.click = lambda: fx.never.as_(ci.ack)
        late = yield from interact(fake, handler, submit(PACKED, {}))
        assert late == ci.Late()
        assert (
            yield from interact(fake, handler, click({"type": "button", "action_id": "go"}))
        ) is None

    return program


@testing.effect
def test_refuses_a_modal_slack_refuses_to_handler_refused_still_acking():
    """SlackChat.interaction / refuses a modal Slack refuses to Handler.refused, still acking"""

    @fx.gen
    def program() -> Gen[None]:
        fake = Fake(
            {"auth.test": AUTH_TEST, "views.open": {"ok": False, "error": "expired_trigger_id"}}
        )
        handler = Recording()
        handler.click = lambda: fx.succeed(ci.OpenModal(modal=MODAL))
        assert (
            yield from interact(fake, handler, click({"type": "button", "action_id": "go"}))
        ) is None
        assert [(e.op, type(e.reason).__name__, e.reason.detail) for e in handler.refused] == [
            ("openModal", "NotFound", "interaction_expired")
        ]

    return program


@testing.effect
def test_refuses_a_response_url_off_slack_before_any_call():
    """followUp / refuses a response_url off Slack before any call"""

    @fx.gen
    def program() -> Gen[None]:
        fake = Fake({"auth.test": AUTH_TEST})

        def failure(url: str) -> Effect[ChatError, Any]:
            command = ci.CommandInvoked(
                id="summarize",
                text="",
                thread=slack_chat.thread(team=TEAM, channel=CHANNEL),
                user_id="U080YLYB277",
                raw={"response_url": url},
            )
            return (
                chat.Chat()
                .flat_map(lambda service: service.follow_up(ci.defer(command), markdown="x"))
                .flip()
                .pipe(fx.provide(slack_layer(fake)))
            )

        for url in [
            "https://hooks.slack.com.evil.test/commands/1",
            RESPONSE_URL.replace("https:", "http:"),
        ]:
            error = yield from failure(url)
            assert (error.op, type(error.reason).__name__, error.reason.detail) == (
                "followUp",
                "InvalidRequest",
                "invalid_response_url",
            )
        assert fake.called("response_url") == []

    return program


SECRET = "8f742231b10e8888abcd99yyyzzz85a5"


def _post_headers(body: str, signature: str | None) -> dict[str, str]:
    timestamp = unix_now()
    digest = hmac.new(SECRET.encode(), f"v0:{timestamp}:{body}".encode(), hashlib.sha256)
    return {
        "content-type": "application/x-www-form-urlencoded",
        "x-slack-request-timestamp": timestamp,
        "x-slack-signature": "v0=" + digest.hexdigest() if signature is None else signature,
    }


def serve(handler: Recording) -> Effect[Callable[..., Effect[Any, Any]], Any, Any]:
    app = (
        slack_chat.layer_interactivity(
            path="/slack/interactivity",
            signing_secret=redacted(SECRET),
            app_id=APP_ID,
            deadline=millis(50),
        )
        .pipe(
            layer.provide(
                slack_chat.layer(bot_token=redacted("xoxb-test"), team_id=TEAM)
                .pipe(layer.provide(chat.layer))
                .pipe(layer.provide(Fake({"auth.test": AUTH_TEST}).layer))
            )
        )
        .pipe(layer.provide(layer.merge(layer_mac, handler.layer)))
    )

    @fx.gen
    def build() -> Gen[Callable[..., Effect[Any, Any]]]:
        http = yield from router.in_memory_client(app)

        def send(
            payload: object = None,
            *,
            signature: str | None = None,
            form: list[tuple[str, str]] | None = None,
        ) -> Effect[Any, Any]:
            body = urlencode(form if form is not None else [("payload", json.dumps(payload))])
            return http.post(
                "http://localhost/slack/interactivity",
                body=http_request.post("http://x")
                .body_text(body, "application/x-www-form-urlencoded")
                .body,
                headers=_post_headers(body, signature),
            )

        return send

    return build


@testing.live
def test_takes_a_commands_form_keeping_a_repeated_fields_first_value_and_answers_a_late_one_503():
    """layerInteractivity / takes a command's form, keeping a repeated field's first value, and
    answers a late one 503"""

    @fx.gen
    def program() -> Gen[None]:
        handler = Recording()
        send = yield from serve(handler)
        seen: list[str] = []
        handler.command = lambda event: fx.sync(lambda: seen.append(event.text)).as_(
            ci.respond(markdown="Hi", visibility="public")
        )

        def form(text: str) -> list[tuple[str, str]]:
            return [*command_fields("/deploy", text).items(), ("text", "second")]

        answered = yield from send(form=form("first"))
        assert answered.status == 200
        assert (yield from answered.json)["response_type"] == "in_channel"
        assert seen == ["first"]

        handler.command = lambda _: fx.never.as_(ci.ack)
        assert (yield from send(form=form("late"))).status == 503

    return fx.scoped(program)


@testing.live
def test_answers_errors_as_json_and_a_bad_signature_401():
    """layerInteractivity / answers errors as JSON, and a bad signature 401"""

    @fx.gen
    def program() -> Gen[None]:
        handler = Recording()
        send = yield from serve(handler)
        handler.submit = lambda: fx.succeed(ci.errors({"field": "Too short"}))
        errors = yield from send(submit(PACKED, {}))
        assert errors.status == 200
        assert (yield from errors.json) == {
            "response_action": "errors",
            "errors": {"field": "Too short"},
        }

        assert (yield from send(submit(PACKED, {}), signature="v0=00")).status == 401

    return fx.scoped(program)
