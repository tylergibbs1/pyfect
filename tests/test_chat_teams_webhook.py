"""Port of Effect's ``packages/chat/teams/test/webhook.test.ts``: the
messaging endpoint through ``layer_webhook``, with tokens signed by a key in
a stubbed Bot Framework key set."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from _teams_fake import (
    APP_ID,
    INTERACTION_KEY,
    KEYS_URL,
    TENANT_ID,
    Gen,
    activity,
    crypto,
    setup,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_ui as U
from pyfect.chat.chat_error import ChatError, TooLarge
from pyfect.chat.chat_event import MessageCreated
from pyfect.chat.teams import _envelope, _interactions, teams_chat
from pyfect.chat.teams._cloud import Unverified


@testing.live
def test_answers_413_past_max_body_bytes_also_for_a_body_middleware_read_first():
    """layerWebhook / answers 413 past maxBodyBytes, also for a body middleware read first"""

    @fx.gen
    def program() -> Gen[None]:
        for read_first in (False, True):
            endpoint = yield from setup(max_body_bytes=100, read_first=read_first)
            status = yield from endpoint.send(activity(), (yield from endpoint.bearer()))
            assert status == 413, f"read_first: {read_first}"
            assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_answers_403_without_a_valid_token_and_for_a_token_bound_to_another_service_url():
    """layerWebhook / answers 403 without a valid token, and for a token bound to another
    serviceUrl"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        assert (yield from endpoint.send(activity())) == 403
        assert (yield from endpoint.send(activity(), "Bearer not.a.token")) == 403
        other = yield from endpoint.bearer("https://smba.trafficmanager.net/amer/")
        assert (yield from endpoint.send(activity(), other)) == 403
        wrong_tenant = activity(
            conversation={"id": "a:direct", "conversationType": "personal", "tenantId": "x"}
        )
        assert (yield from endpoint.send(wrong_tenant, (yield from endpoint.bearer()))) == 403
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_hands_a_verified_message_to_the_chat_handler_and_drops_a_targeted_one():
    """layerWebhook / hands a verified message to the ChatHandler, and drops a targeted one"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        bearer = yield from endpoint.bearer()
        assert (yield from endpoint.send(activity(), bearer)) == 200
        targeted = activity(
            id="1800000000002", recipient={"id": f"28:{APP_ID}", "isTargeted": True}
        )
        assert (yield from endpoint.send(targeted, bearer)) == 200
        assert len(endpoint.events) == 1
        assert isinstance(endpoint.events[0], MessageCreated)

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_fetches_the_metadata_and_the_key_set_with_redirects_off():
    """layerWebhook / fetches the metadata and the key set with redirects off"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup()
        assert (yield from endpoint.send(activity(), (yield from endpoint.bearer()))) == 200
        discovery = [
            sent
            for sent in endpoint.bot.sent
            if sent.url.href.startswith("https://login.botframework.com/")
        ]
        assert [sent.url.href for sent in discovery] == [
            "https://login.botframework.com/v1/.well-known/openidconfiguration",
            KEYS_URL,
        ]
        assert all(sent.follow_redirects is False for sent in discovery)

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_answers_503_for_metadata_whose_jwks_uri_is_not_a_url():
    """layerWebhook / answers 503 for metadata whose jwks_uri is not a URL"""

    @fx.gen
    def program() -> Gen[None]:
        endpoint = yield from setup(jwks_uri="not a URL")
        assert (yield from endpoint.send(activity(), (yield from endpoint.bearer()))) == 503
        assert endpoint.events == []

    return fx.scoped(program).pipe(fx.provide(crypto))


# --- dialogs through layer_webhook ---------------------------------------------------

CHANNEL = "19:abc@thread.tacv2"
# A click on a card posted as a channel post: the root of its own reply chain.
CLICKED = f"{CHANNEL};messageid=123"
MODAL = U.Modal(
    id="deploy",
    title="Deploy",
    elements=(
        U.TextInput(id="constructor", label="Name", initial="first"),
        U.TextInput(id="note", label="Note", initial="draft"),
    ),
)


@dataclass
class Opened:
    dialog: str | None
    refusals: list[ChatError]
    submits: list[ci.ModalSubmitted]
    submit: Callable[[dict[str, str]], Effect[Any, Any]]


def _dig(value: object, *path: str | int) -> object:
    for step in path:
        if isinstance(step, int):
            items = cast("list[object]", value) if isinstance(value, list) else []
            value = items[step] if len(items) > step else None
        else:
            value = cast("dict[str, object]", value).get(step) if isinstance(value, dict) else None
    return value


def open_dialog(opens: U.Modal) -> Effect[Opened, Any, Any]:
    @fx.gen
    def run() -> Gen[Opened]:
        submits: list[ci.ModalSubmitted] = []
        refusals: list[ChatError] = []

        def submit_handler(event: ci.ModalSubmitted) -> Effect[ci.SubmitReply]:
            def record() -> ci.SubmitReply:
                submits.append(event)
                return ci.errors({"note": "Too short"})

            return fx.sync(record)

        endpoint = yield from setup(
            teams={
                "interaction_keys": [INTERACTION_KEY],
                "modal_buttons": ["open"],
                "unverified": Unverified(buttons=True, modals=True),
            },
            interactions=ci.HandlerService(
                click=lambda _: fx.succeed(ci.OpenModal(modal=opens)),
                submit=submit_handler,
                command=lambda _: fx.succeed(ci.ack),
                refused=lambda _, error: fx.sync(lambda: refusals.append(error)),
            ),
        )
        bearer = yield from endpoint.bearer()

        def invoke(**overrides: object) -> Effect[Any, Any]:
            body = activity(
                type="invoke",
                conversation={"id": CLICKED, "conversationType": "channel", "tenantId": TENANT_ID},
                **overrides,
            )
            return endpoint.exchange(body, bearer).flat_map(lambda response: response.json)

        envelope = yield from _envelope.make(
            app_id=APP_ID, tenant_id=TENANT_ID, keys=[INTERACTION_KEY]
        )
        button = yield from envelope.sign_button(CHANNEL, _envelope.Button("open"))
        opened = yield from invoke(
            name="task/fetch", replyToId="123", value={"data": {"effect": button}}
        )
        found = _dig(opened, "task", "value", "card", "content", "actions", 0, "data", "effect")
        dialog = found if isinstance(found, str) else None

        def submit(values: dict[str, str]) -> Effect[Any, Any]:
            return invoke(name="task/submit", value={"data": {"effect": dialog, **values}})

        return Opened(dialog, refusals, submits, submit)

    return run


@testing.live
def test_opens_a_dialog_only_when_its_whole_signed_token_fits_modal_metadata_length():
    """dialogs through layerWebhook / opens a dialog only when its whole signed token fits
    modalMetadataLength"""

    # Short id and no metadata: the definition alone makes the token long.
    def with_text(length: int) -> U.Modal:
        return U.Modal(
            id=MODAL.id,
            title=MODAL.title,
            elements=(U.Text(text="x" * length), *MODAL.elements),
        )

    @fx.gen
    def program() -> Gen[None]:
        big = yield from open_dialog(with_text(3_500))
        assert big.dialog is None
        assert isinstance(big.refusals[0].reason, TooLarge)

        small = yield from open_dialog(with_text(1_000))
        assert isinstance(small.dialog, str)
        assert len(small.dialog) <= _interactions.MODAL_METADATA_LENGTH
        assert small.refusals == []

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_a_submit_keeps_the_thread_and_message_of_the_click():
    """dialogs through layerWebhook / a submit keeps the thread and message of the click"""

    @fx.gen
    def program() -> Gen[None]:
        opened = yield from open_dialog(MODAL)
        yield from opened.submit({"constructor": "a", "note": "b"})
        assert len(opened.submits) == 1
        assert opened.submits[0].thread == teams_chat.thread(CHANNEL)
        assert opened.submits[0].message_id == "123"

    return fx.scoped(program).pipe(fx.provide(crypto))


@testing.live
def test_an_error_reply_keeps_what_the_user_entered_and_reads_no_inherited_key():
    """dialogs through layerWebhook / an error reply keeps what the user entered, and reads no
    inherited key"""

    @fx.gen
    def program() -> Gen[None]:
        opened = yield from open_dialog(MODAL)
        reply = yield from opened.submit({"constructor": "edited", "note": "b"})
        body: list[dict[str, Any]] = reply["task"]["value"]["card"]["content"]["body"]
        inputs = [element for element in body if element["type"] == "Input.Text"]
        assert [element["value"] for element in inputs] == ["edited", "b"]
        texts = [element["text"] for element in body if element["type"] == "TextBlock"]
        assert texts == ["Too short"]

    return fx.scoped(program).pipe(fx.provide(crypto))
