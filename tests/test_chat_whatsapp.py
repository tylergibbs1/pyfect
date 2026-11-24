"""Port of Effect's ``packages/chat/whatsapp/test/WhatsAppChat.test.ts``: posts
over a fake Graph API, the signed webhook, the normaliser and the keys."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from typing import Any

from _whatsapp_fake import (
    BSUID,
    PHONE,
    PHONE_NUMBER_ID,
    THREAD,
    Graph,
    Status,
    graph_error,
    inbound,
    statuses,
    whatsapp_layer,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.byte_size import ByteSize
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_markdown
from pyfect.chat.chat import Chat
from pyfect.chat.chat_adapter import File
from pyfect.chat.chat_error import AnyReason, ChatError, Unsupported
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.chat_thread import ChatThread, make
from pyfect.chat.chat_ui import Action, Button, LinkButton, Select, SelectOption
from pyfect.chat.whatsapp import _webhook, whatsapp_chat
from pyfect.chat.whatsapp.whatsapp_chat import Template, WhatsAppChat
from pyfect.chat.whatsapp.whatsapp_update import UserIdChanged, WhatsAppUpdate
from pyfect.crypto.native import layer_mac
from pyfect.deferred import Deferred
from pyfect.duration import Duration, millis, seconds, zero
from pyfect.http import request as http_request
from pyfect.http import server_request
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def post(
    markdown: str,
    *,
    actions: Sequence[Action] = (),
    files: Sequence[File] = (),
    to: ChatThread = THREAD,
) -> Effect[Any, ChatError, Chat]:
    return Chat().flat_map(
        lambda chat: chat.post(to, markdown=markdown, actions=actions, files=files)
    )


def run[A](graph: Graph, effect: Effect[A, Any, Any]) -> A:
    return fx.run_blocking(effect.pipe(fx.provide(whatsapp_layer(graph))))


def failure(graph: Graph, effect: Effect[Any, ChatError, Any]) -> AnyReason:
    return run(graph, effect.flip()).reason


def file(name: str, content_type: str, size: int = 8) -> File:
    return File(name, content_type, bytes(size))


def button(id: str, label: str, value: str | None = None) -> Button:
    return Button(id=id, label=label, value=value)


# --- post ---------------------------------------------------------------------------------


def test_sends_rendered_text_to_a_bsuid_as_recipient_and_a_phone_number_as_to_without_a_preview():
    """post / sends rendered text to a BSUID as recipient and a phone number as to, without a
    preview"""
    graph = Graph()
    run(graph, post("**hi** [docs](https://e.com)"))
    run(graph, post("hi", to=whatsapp_chat.thread(phone_number_id=PHONE_NUMBER_ID, user=PHONE)))
    first, second = graph.sent()
    assert first == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "recipient": BSUID,
        "type": "text",
        "text": {"body": "*hi* docs (https://e.com)", "preview_url": False},
    }
    assert second["to"] == PHONE


def test_lays_out_reply_buttons_a_link_button_a_list_and_appended_links():
    """post / lays out reply buttons, a link button, a list and appended links"""
    graph = Graph()
    run(graph, post("", actions=[button("a", "Yes"), button("b", "No", "v")]))
    run(graph, post("x", actions=[LinkButton(label="Docs", url="https://e.com")]))
    run(
        graph,
        post(
            "x",
            actions=[
                button("a", "Yes"),
                Select(
                    id="env",
                    placeholder="Environment",
                    options=(SelectOption(label="Prod", value="p"),),
                ),
                LinkButton(label="Docs", url="https://e.com"),
            ],
        ),
    )
    reply, cta, listed = (body["interactive"] for body in graph.sent())
    assert reply == {
        "type": "button",
        "body": {"text": "Yes, No"},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": "ba", "title": "Yes"}},
                {"type": "reply", "reply": {"id": "bb␟v", "title": "No"}},
            ]
        },
    }
    assert cta["action"] == {
        "name": "cta_url",
        "parameters": {"display_text": "Docs", "url": "https://e.com"},
    }
    assert listed == {
        "type": "list",
        "body": {"text": "x\n\nDocs: https://e.com"},
        "action": {
            "button": "Environment",
            "sections": [
                {"title": "Actions", "rows": [{"id": "ba", "title": "Yes"}]},
                {"title": "Environment", "rows": [{"id": "senv␟p", "title": "Prod"}]},
            ],
        },
    }


def test_refuses_before_any_call():
    """post / refuses before any call"""
    graph = Graph()
    rows = [button(f"b{i}", f"b{i}") for i in range(6)]
    select = Select(
        id="s", options=tuple(SelectOption(label=f"o{i}", value=f"o{i}") for i in range(5))
    )
    refusals: list[tuple[Effect[Any, ChatError, Chat], str, str]] = [
        (post("x", actions=[*rows, select]), "TooLarge", "list_rows"),
        (post("x", actions=[button("a", "x" * 25)]), "TooLarge", "label_too_long"),
        (
            post("x", actions=[button("a", "Same"), button("b", "Same")]),
            "InvalidRequest",
            "duplicate_label",
        ),
        (post("x", actions=[button("a␟", "A")]), "InvalidRequest", "invalid_action_id"),
        # The body is the text, "\n\n" and "Docs: https://example.com": 1,027 units, over the
        # 1,024 of reply buttons.
        (
            post(
                "x" * 1000,
                actions=[button("a", "Yes"), LinkButton(label="Docs", url="https://example.com")],
            ),
            "TooLarge",
            "message_too_long",
        ),
        # The wire id "bx␟" + 126 "é" is 257 UTF-8 bytes, though within action_data_length.
        (post("x", actions=[button("x", "Yes", "é" * 126)]), "TooLarge", "action_data_too_long"),
        (
            post("x", to=make("whatsapp", f"{PHONE_NUMBER_ID}/u/not-a-user")),
            "InvalidRequest",
            "invalid_thread",
        ),
        (
            post("x", to=make("whatsapp", f"{PHONE_NUMBER_ID}/g/120363")),
            "InvalidRequest",
            "group_unsupported",
        ),
        (
            post("x", files=[file("a.txt", "text/plain"), file("b.txt", "text/plain")]),
            "TooLarge",
            "file_refused",
        ),
        (post("x", files=[file("a.webp", "image/webp")]), "TooLarge", "file_refused"),
        (
            post("x", files=[file("a.png", "image/png", 5 * 1024 * 1024 + 1)]),
            "TooLarge",
            "file_refused",
        ),
        (post("x", files=[file("a.ogg", "audio/ogg")]), "TooLarge", "file_refused"),
        (post("x" * 1025, files=[file("a.txt", "text/plain")]), "TooLarge", "file_refused"),
        (
            post("x", actions=rows[:4], files=[file("a.txt", "text/plain")]),
            "TooLarge",
            "file_refused",
        ),
    ]
    for effect, tag, detail in refusals:
        reason = failure(graph, effect)
        assert (type(reason).__name__, reason.detail) == (tag, detail)
    assert graph.calls == []


def test_names_the_messaging_account_on_every_send_when_one_is_configured():
    """post / names the messaging account on every send when one is configured"""
    graph = Graph()

    @fx.gen
    def program() -> Gen[None]:
        yield from post("hi")
        whatsapp = yield from WhatsAppChat()
        yield from whatsapp.send_template(THREAD, Template(name="hello", language="en_US"))

    fx.run_blocking(program.pipe(fx.provide(whatsapp_layer(graph, messaging_account_id="ma-1"))))
    assert [body["messaging_account_id"] for body in graph.sent()] == ["ma-1", "ma-1"]


def test_uploads_a_file_as_the_header_of_reply_buttons_and_markdown_as_text_plain():
    """post / uploads a file as the header of reply buttons, and Markdown as text/plain"""
    graph = Graph()
    run(graph, post("notes", actions=[button("a", "Ok")], files=[file("a.md", "text/markdown")]))
    upload, send = graph.calls
    assert upload.body["type"] == "text/plain"
    assert upload.body["file"].name == "a.md"
    assert send.body["interactive"]["header"] == {
        "type": "document",
        "document": {"id": "media-1", "filename": "a.md"},
    }


def test_posts_the_text_alone_when_meta_refuses_the_upload():
    """post / posts the text alone when Meta refuses the upload"""
    graph = Graph()
    graph.next[f"{PHONE_NUMBER_ID}/media"] = graph_error(131053)
    run(
        graph,
        chat_markdown.post(
            THREAD,
            "Report",
            files=[file("a.txt", "text/plain")],
            unattached_note=lambda _: " (not attached)",
            min_write_interval=zero,
        ),
    )
    assert [body["text"]["body"] for body in graph.sent()] == ["Report (not attached)"]


def test_maps_131047_to_forbidden_outside_the_window():
    """post / maps 131047 to Forbidden outside the window"""
    graph = Graph()
    graph.next[f"{PHONE_NUMBER_ID}/messages"] = graph_error(131047)
    reason = failure(graph, post("x"))
    assert (type(reason).__name__, reason.detail) == ("Forbidden", whatsapp_chat.OUTSIDE_WINDOW)


# --- webhook ------------------------------------------------------------------------------

SECRET = "app-secret"
FOUR_SECONDS = seconds(4)
ONE_MIB = ByteSize(1024 * 1024)


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class Delivered:
    status: int
    seen: list[str] = field(default_factory=list[str])
    clicks: list[ci.ButtonClicked | ci.SelectChanged] = field(
        default_factory=list["ci.ButtonClicked | ci.SelectChanged"]
    )
    refused: list[ChatError] = field(default_factory=list[ChatError])


def deliver(
    envelope: object,
    *,
    signature: str | None = None,
    refuse: Callable[[ChatEvent], bool] | None = None,
    handle: Callable[[ChatEvent], Effect[None, NotAccepted]] | None = None,
    on_click: ci.ClickReply = ci.ack,
    on_refused: Callable[[ChatError], Effect[None]] | None = None,
    deadline: Duration = FOUR_SECONDS,
    max_body_size: ByteSize = ONE_MIB,
    read_first: bool = False,
) -> Effect[Delivered, Any]:
    body = json.dumps(envelope).encode()
    seen: list[str] = []
    clicks: list[ci.ButtonClicked | ci.SelectChanged] = []
    refused: list[ChatError] = []

    def handled(event: ChatEvent) -> Effect[None, NotAccepted]:
        if refuse is not None and refuse(event):
            return fx.fail(NotAccepted())
        if handle is not None:
            return handle(event)
        return fx.sync(lambda: seen.append(type(event).__name__))

    def on_update(update: WhatsAppUpdate) -> Effect[None, NotAccepted]:
        return fx.sync(lambda: seen.append(type(update).__name__))

    def clicked(event: ci.ButtonClicked | ci.SelectChanged) -> Effect[ci.ClickReply]:
        def record() -> ci.ClickReply:
            seen.append(type(event).__name__)
            clicks.append(event)
            return on_click

        return fx.sync(record)

    def refusal(_event: object, error: ChatError) -> Effect[None]:
        recorded = fx.sync(lambda: refused.append(error))
        return recorded if on_refused is None else recorded.and_then(on_refused(error))

    handler = ci.HandlerService(
        click=clicked,
        submit=lambda _: fx.succeed(ci.close),
        command=lambda _: fx.succeed(ci.ack),
        refused=refusal,
    )

    @fx.gen
    def program() -> Gen[Delivered]:
        verify = yield from _webhook.make_verifier(redacted(SECRET)).pipe(fx.provide(layer_mac))
        client = http_request.post(
            "http://localhost/whatsapp",
            headers={"x-hub-signature-256": sign(body) if signature is None else signature},
        ).body_bytes(body, "application/json")
        request = server_request.from_client_request(client)
        if read_first:
            yield from request.bytes_
        response = yield from _webhook.handle_request(
            request,
            _webhook.Options(
                verify=verify,
                normalize=lambda envelope: whatsapp_chat.normalize(
                    envelope, phone_number_id=PHONE_NUMBER_ID
                ),
                handle=handled,
                on_update=on_update,
                deadline=deadline,
                max_body_size=max_body_size,
            ),
        ).pipe(fx.provide_service(ci.Handler, handler))
        return Delivered(response.status, seen, clicks, refused)

    return program


TEXT = inbound({"type": "text", "text": {"body": "hi"}})


def _verification(token: str) -> int:
    request = server_request.from_client_request(
        http_request.get(
            f"http://localhost/whatsapp?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=42"
        )
    )
    return _webhook.handle_verification(request, redacted("verify")).status


@testing.effect
def test_checks_the_signature_and_answers_metas_subscription_check():
    """webhook / checks the signature and answers Meta's subscription check"""

    @fx.gen
    def program() -> Gen[None]:
        assert (yield from deliver(TEXT, signature="sha256=00")).status == 401
        assert (yield from deliver(TEXT)).status == 200
        assert [_verification("verify"), _verification("other")] == [200, 403]

    return program


@testing.effect
def test_answers_413_past_the_body_limit_also_for_a_body_read_earlier():
    """webhook / answers 413 past the body limit, also for a body read earlier"""

    @fx.gen
    def program() -> Gen[None]:
        for read_first in (False, True):
            result = yield from deliver(TEXT, max_body_size=ByteSize(100), read_first=read_first)
            assert (result.status, result.seen) == (413, []), read_first

    return program


@testing.effect
def test_runs_updates_in_order_drops_a_removed_reaction_and_stops_at_not_accepted_with_a_503():
    """webhook / runs updates in order, drops a removed reaction and stops at NotAccepted with
    a 503"""
    batch = inbound({"type": "text", "text": {"body": "hi"}})
    value = batch["entry"][0]["changes"][0]["value"]
    first = value["messages"][0]
    value["messages"].extend(
        [
            {
                **first,
                "id": "wamid.r1",
                "type": "reaction",
                "reaction": {"message_id": "wamid.out1", "emoji": ""},
            },
            {
                **first,
                "id": "wamid.r2",
                "type": "reaction",
                "reaction": {"message_id": "wamid.out1", "emoji": "👍"},
            },
        ]
    )
    value["statuses"] = [
        {
            "id": "wamid.out1",
            "status": "read",
            "timestamp": "1794600001",
            "recipient_id": PHONE,
            "recipient_user_id": BSUID,
        }
    ]

    @fx.gen
    def program() -> Gen[None]:
        ok = yield from deliver(batch)
        assert (ok.status, ok.seen) == (200, ["MessageCreated", "ReactionAdded", "Status", "Alias"])
        refused = yield from deliver(
            batch, refuse=lambda event: type(event).__name__ == "MessageCreated"
        )
        assert (refused.status, refused.seen) == (503, [])

    return program


@testing.live
def test_answers_503_at_the_deadline_without_waiting_for_a_slow_finalizer():
    """webhook / answers 503 at the deadline without waiting for a slow finalizer"""

    @fx.gen
    def program() -> Gen[None]:
        # The finalizer sleeps past the test's own timeout, so waiting for it fails the test.
        result = yield from deliver(
            TEXT,
            handle=lambda _: fx.never.ensuring(fx.sleep("5 seconds")),
            deadline=millis(50),
        )
        assert result.status == 503

    return program


@testing.live
def test_interrupts_the_worker_when_the_request_is_cancelled():
    """webhook / interrupts the worker when the request is cancelled at any step"""
    state = {"started": False, "stopped": False}

    def verify(_headers: object, _body: bytes) -> Effect[bool]:
        def mark(key: str) -> Effect[None]:
            return fx.sync(lambda: state.__setitem__(key, True))

        return mark("started").and_then(fx.never.on_interrupt(mark("stopped")))

    @fx.gen
    def program() -> Gen[None]:
        request = server_request.from_client_request(
            http_request.post("http://localhost/whatsapp").body_text("{}", "application/json")
        )
        handled = _webhook.handle_request(
            request,
            _webhook.Options(
                verify=verify,
                normalize=lambda _: [],
                handle=lambda _: fx.void,
                on_update=None,
                deadline=seconds(4),
                max_body_size=ByteSize(1024),
            ),
        )
        fiber = yield from handled.fork(start_immediately=True)
        yield from fx.sleep("20 millis")
        yield from fiber.interrupt()
        yield from fx.sleep("20 millis")
        assert state["started"]
        assert state["stopped"]

    return program


@testing.live
def test_hands_a_click_to_the_handler_and_refuses_a_modal_as_unsupported():
    """webhook / hands a click to the handler and refuses a modal as Unsupported"""
    click = inbound(
        {
            "type": "interactive",
            "context": {"from": "15550783881", "id": "wamid.out1"},
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "senv␟p␟q", "title": "Prod"},
            },
        }
    )
    modal = ci.modal("m", title="M", fields={}).open()

    @fx.gen
    def program() -> Gen[None]:
        refusal: Deferred[ChatError] = yield from Deferred[ChatError].make()
        # The refusal callback never finishes, and the click is still answered 200.
        result = yield from deliver(
            click,
            on_click=modal,
            on_refused=lambda error: refusal.succeed(error).and_then(fx.never),
            deadline=millis(500),
        )
        assert (result.status, result.seen) == (200, ["SelectChanged"])
        [event] = result.clicks
        assert isinstance(event, ci.SelectChanged)
        assert (event.id, event.value, event.message_id) == ("env", "p␟q", "wamid.out1")
        # The key is the webhook message's id, not the clicked card's.
        message_id = click["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
        assert whatsapp_chat.delivery_key(event) == f"{PHONE_NUMBER_ID}/{message_id}"
        error = yield from refusal.wait()
        assert isinstance(error.reason, Unsupported)

    return program


# --- normalize ----------------------------------------------------------------------------


def test_reports_a_changed_bsuid_that_arrives_with_no_sender_or_contact():
    """normalize / reports a changed BSUID that arrives with no sender or contact"""
    envelope = inbound(
        {
            "type": "system",
            "system": {"type": "user_changed_user_id", "user_id": "US.99", "body": "changed"},
        }
    )
    value = envelope["entry"][0]["changes"][0]["value"]
    del value["contacts"]
    del value["messages"][0]["from"]
    del value["messages"][0]["from_user_id"]
    [update] = whatsapp_chat.normalize(envelope, phone_number_id=PHONE_NUMBER_ID)
    assert isinstance(update, UserIdChanged)
    assert [update.thread.id, update.user_id, whatsapp_chat.update_key(update)] == [
        f"{PHONE_NUMBER_ID}/u/US.99",
        "US.99",
        f"{PHONE_NUMBER_ID}/user_changed/{value['messages'][0]['id']}",
    ]


# --- keys ---------------------------------------------------------------------------------


def test_keys_an_update_by_its_parts_escaped():
    """keys / keys an update by its parts, escaped"""
    updates = whatsapp_chat.normalize(
        statuses(
            {
                "id": "wamid.a/b",
                "status": "delivered",
                "recipient_id": PHONE,
                "recipient_user_id": BSUID,
            }
        ),
        phone_number_id=PHONE_NUMBER_ID,
    )
    assert [whatsapp_chat.update_key(update) for update in updates] == [  # pyright: ignore[reportArgumentType]
        f"{PHONE_NUMBER_ID}/status/wamid.a%2Fb/delivered",
        f"{PHONE_NUMBER_ID}/alias/wamid.a%2Fb/delivered/{PHONE}/{BSUID}",
    ]


# --- Retry-After --------------------------------------------------------------------------

MESSAGES = f"{PHONE_NUMBER_ID}/messages"


def _rate_limited(retry_after: str) -> Status:
    """Meta's 429 for too many messages, with its wait."""
    answer = graph_error(130429, 429)
    return Status(answer.status, answer.body, {"retry-after": retry_after})


@testing.effect
def test_waits_out_a_rate_limits_retry_after_before_sending_again():
    """WhatsApp backed off on its own schedule, half a second first, and
    sent again while Meta still refused."""
    graph = Graph()
    graph.next[MESSAGES] = _rate_limited("7")

    @fx.gen
    def program() -> Gen[None]:
        fiber = yield from post("alert").fork()
        yield from testing.adjust("6999 millis")
        assert len(graph.sent()) == 1
        yield from testing.adjust("1 millis")
        yield from fiber.join()
        assert len(graph.sent()) == 2

    return program.pipe(fx.provide(whatsapp_layer(graph)))


@testing.effect
def test_fails_at_once_with_the_wait_when_retry_after_passes_max_retry_after():
    graph = Graph()
    graph.next[MESSAGES] = _rate_limited("3600")

    @fx.gen
    def program() -> Gen[None]:
        error = yield from post("alert").flip()
        assert error.retry_after == seconds(3600)
        assert type(error.reason).__name__ == "RateLimited"
        assert len(graph.sent()) == 1

    return program.pipe(fx.provide(whatsapp_layer(graph, max_retry_after="1 minute")))
