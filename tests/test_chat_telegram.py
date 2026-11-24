"""Port of Effect's ``packages/chat/telegram/test/TelegramChat.test.ts``: the
adapter's own guarantees, over a fake Bot API, that the conformance suite
does not see: credentials stay out of errors, spans and logs, the webhook's
answers, private answers, clicks, excluded contexts, delivery keys, polling
and deadlines."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any

from _literal_markdown import literal
from _telegram_fake import (
    BOT_ID,
    CHAT_ID,
    CONTEXT,
    THREAD,
    TOKEN,
    FakeApi,
    api_error,
    callback_update,
    command_update,
    message_update,
    telegram_layer,
)

import pyfect as fx
from pyfect import layer, logger, testing
from pyfect._core import Effect
from pyfect.chat import chat_handler
from pyfect.chat import chat_interaction as ci
from pyfect.chat.chat import Chat
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_handler import NotAccepted
from pyfect.chat.telegram import telegram_chat
from pyfect.chat.telegram.telegram_chat import Outcome, ReceiveOptions, TelegramChat
from pyfect.deferred import Deferred
from pyfect.duration import seconds
from pyfect.exit import is_failure
from pyfect.http import request as http_request
from pyfect.http import router
from pyfect.redacted import make as redacted
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

SECRET = "s" * 32


@dataclass
class Recorder:
    """What reached the consumer, by kind."""

    command: Callable[[], Effect[ci.CommandReply]] | None = None
    click: Effect[None] | None = None
    handle: Effect[None, NotAccepted] | None = None
    events: list[ChatEvent] = field(default_factory=list[ChatEvent])
    clicks: list[ci.ButtonClicked | ci.SelectChanged] = field(
        default_factory=list["ci.ButtonClicked | ci.SelectChanged"]
    )
    commands: list[ci.CommandInvoked] = field(default_factory=list[ci.CommandInvoked])
    refused: list[ChatError] = field(default_factory=list[ChatError])
    unhandled: list[object] = field(default_factory=list[object])

    def on_event(self, event: ChatEvent) -> Effect[None, NotAccepted]:
        return (
            self.handle if self.handle is not None else fx.sync(lambda: self.events.append(event))
        )

    def interactions(self) -> ci.HandlerService:
        def click(event: ci.ButtonClicked | ci.SelectChanged) -> Effect[ci.ClickReply]:
            work = (
                self.click if self.click is not None else fx.sync(lambda: self.clicks.append(event))
            )
            return work.as_(ci.ack)

        def command(event: ci.CommandInvoked) -> Effect[ci.CommandReply]:
            reply = self.command() if self.command is not None else fx.succeed(ci.ack)
            return fx.sync(lambda: self.commands.append(event)).and_then(reply)

        return ci.HandlerService(
            click=click,
            submit=lambda _: fx.succeed(ci.close),
            command=command,
            refused=lambda _event, error: fx.sync(lambda: self.refused.append(error)),
        )

    def on_unhandled(self, update: object) -> Effect[None]:
        return fx.sync(lambda: self.unhandled.append(update))


def receive(api: FakeApi, recorder: Recorder, *updates: object) -> Effect[list[Outcome], Any]:
    """Runs updates through ``TelegramChatService.receive``, as the
    transports do."""

    @fx.gen
    def program() -> Gen[list[Outcome]]:
        telegram = yield from TelegramChat()
        options = ReceiveOptions(on_unhandled=recorder.on_unhandled)
        outcomes: list[Outcome] = []
        for update in updates:
            outcome: Outcome = yield from telegram.receive(update, options)
            outcomes.append(outcome)
        return outcomes

    return (
        program.pipe(fx.provide(chat_handler.layer(recorder.on_event)))
        .pipe(fx.provide_service(ci.Handler, recorder.interactions()))
        .pipe(fx.provide(telegram_layer(api)))
    )


def run[A](effect: Effect[A, Any, Any]) -> A:
    return fx.run_blocking(effect)


def span_tracer() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


EPHEMERAL = {"message_id": 0, "ephemeral_message_id": 7}
"""What makes a message private: id 0, with its own private id."""


def click(data: str, date: int = 1_800_000_000) -> dict[str, Any]:
    """A click on ``data``, on a message whose keyboard has one ``approve``
    button."""
    return callback_update(
        {
            "message_id": 5,
            "date": date,
            "chat": {"id": CHAT_ID, "type": "supergroup"},
            "text": "x",
            "reply_markup": {"inline_keyboard": [[{"text": "Yes", "callback_data": "approve"}]]},
        },
        data,
    )


def until(done: Callable[[], bool]) -> Effect[None]:
    """Yields until ``done`` holds."""

    @fx.gen
    def loop() -> Gen[None]:
        while not done():
            yield from fx.yield_now()

    return loop


def post(markdown: str) -> Effect[Any, ChatError, Chat]:
    return Chat().flat_map(lambda chat: chat.post(THREAD, markdown=markdown))


def test_keeps_the_token_out_of_errors_spans_and_logs():
    api = FakeApi()
    tracer, spans = span_tracer()
    logs: list[str] = []
    sink = logger.format_json.map(logs.append)
    api.next["sendRichMessage"] = api_error(401, "Unauthorized")
    exit = run(
        post("hi")
        .tap_cause(lambda cause: fx.log_error("post failed", cause))
        .exit()
        .pipe(fx.provide(telegram_layer(api)))
        .pipe(fx.provide(logger.layer([sink])))
        .with_tracer(tracer)
    )
    assert is_failure(exit)
    assert any(span.name == "TelegramBotApi.sendRichMessage" for span in spans)
    seen = "\n".join(
        [
            repr(exit),
            str(exit),
            *logs,
            *(json.dumps([span.name, dict(span.attributes)], default=str) for span in spans),
            *(repr(span.events) for span in spans),
        ]
    )
    assert TOKEN.split(":")[1] not in seen


def test_maps_the_rich_message_errors_captured_in_live_check_10():
    captured = [
        ("RICH_MESSAGE_TOO_LARGE", "TooLarge", "message_too_large"),
        ("RICH_MESSAGE_DEPTH_INVALID", "InvalidRequest", "too_deep"),
    ]
    for description, tag, detail in captured:
        api = FakeApi()
        api.next["sendRichMessage"] = api_error(400, f"Bad Request: {description}")
        error = run(post("hi").flip().pipe(fx.provide(telegram_layer(api))))
        reason = error.reason
        assert (type(reason).__name__, getattr(reason, "detail", None)) == (tag, detail)


# --- layer_webhook ------------------------------------------------------------------------


def _webhook_app(recorder: Recorder, **options: Any) -> layer.Layer[Any, Any]:
    return telegram_chat.layer_webhook(
        path="/telegram", secret_token=redacted(SECRET), max_body_bytes=4096, **options
    ).pipe(
        layer.provide(layer.merge(telegram_layer(FakeApi()), chat_handler.layer(recorder.on_event)))
    )


def webhook(recorder: Recorder) -> Effect[Callable[[str, str | None], Effect[int]], Any, Any]:
    @fx.gen
    def make() -> Gen[Callable[[str, str | None], Effect[int]]]:
        http = yield from router.in_memory_client(_webhook_app(recorder))

        def send(body: str, header: str | None = None) -> Effect[int]:
            headers = {} if header is None else {telegram_chat.SECRET_HEADER: header}
            sent = http_request.post("http://x").body_text(body, "application/json").body
            return (
                http.post("http://localhost/telegram", body=sent, headers=headers)
                .map(lambda response: response.status)
                .or_die()
            )

        return send

    return make


UPDATE = json.dumps(message_update({"text": "hi"}))


@testing.effect
def test_needs_the_secret_then_answers_for_the_body():
    """layerWebhook / needs the secret, then answers for the body"""

    @fx.gen
    def program() -> Gen[None]:
        recorder = Recorder()
        send = yield from webhook(recorder)
        assert (yield from send(UPDATE, None)) == 401
        assert (yield from send(UPDATE, "t" * 32)) == 401
        assert recorder.events == []
        assert (yield from send("x" * 5000, SECRET)) == 413
        assert (yield from send("{", SECRET)) == 400
        assert (yield from send(json.dumps({"message": {}}), SECRET)) == 400
        assert (yield from send(UPDATE, SECRET)) == 200
        assert len(recorder.events) == 1

    return fx.scoped(program)


@testing.effect
def test_answers_503_when_the_handler_does_not_accept():
    """layerWebhook / answers 503 when the handler does not accept"""

    @fx.gen
    def program() -> Gen[None]:
        send = yield from webhook(Recorder(handle=fx.fail(NotAccepted())))
        assert (yield from send(UPDATE, SECRET)) == 503

    return fx.scoped(program)


@testing.effect
def test_refuses_a_short_secret():
    """layerWebhook / refuses a short secret"""
    app: layer.Layer[Any, Any, Any] = telegram_chat.layer_webhook(
        path="/telegram", secret_token=redacted("short")
    ).pipe(
        layer.provide(
            layer.merge(telegram_layer(FakeApi()), chat_handler.layer(Recorder().on_event))
        )
    )
    built: Effect[Any, Any, Any] = fx.scoped(router.in_memory_client(app))
    return built.exit().map(is_failure).map(_assert_true)


def _assert_true(value: bool) -> None:
    assert value


# --- private messages ---------------------------------------------------------------------

EPHEMERAL_COMMAND = command_update("deploy", "", EPHEMERAL)


def test_refuses_an_ephemeral_answer_and_never_posts_it():
    """private messages / refuses an ephemeral answer and never posts it"""
    api = FakeApi()
    recorder = Recorder(command=lambda: fx.succeed(ci.respond(markdown="secret")))
    assert run(receive(api, recorder, EPHEMERAL_COMMAND)) == ["accepted"]
    assert [type(error.reason).__name__ for error in recorder.refused] == ["Unsupported"]
    assert api.sent("sendRichMessage") == []
    assert len(recorder.events) + len(recorder.unhandled) == 0


def test_answers_an_ephemeral_command_in_public_without_quoting_it():
    """private messages / answers an ephemeral command in public without quoting it"""
    api = FakeApi()
    recorder = Recorder(
        command=lambda: fx.succeed(ci.respond(markdown="done", visibility="public"))
    )
    run(receive(api, recorder, EPHEMERAL_COMMAND))
    [sent] = api.sent("sendRichMessage")
    assert sent["chat_id"] == CHAT_ID
    assert "reply_parameters" not in sent


def test_keeps_an_ephemeral_message_that_is_not_a_command_from_every_handler():
    """private messages / keeps an ephemeral message that is not a command from every handler"""
    recorder = Recorder()
    run(receive(FakeApi(), recorder, message_update({"text": "psst", **EPHEMERAL})))
    assert len(recorder.events) + len(recorder.unhandled) + len(recorder.commands) == 0


def test_dispatches_only_data_from_telegrams_copy_of_the_keyboard_and_answers_every_click():
    api = FakeApi()
    recorder = Recorder()
    # A message Telegram can no longer show the bot comes with date 0.
    run(receive(api, recorder, click("approve"), click("forged"), click("approve", 0)))
    assert [(c.id, c.message_id) for c in recorder.clicks] == [("approve", "5")]
    assert len(api.sent("answerCallbackQuery")) == 3


def test_sends_business_and_channel_direct_messages_to_on_unhandled_and_answers_their_clicks():
    """sends business and channel direct-message updates to onUnhandled, and answers their clicks"""
    api = FakeApi()
    recorder = Recorder()
    business = {
        "message_id": 3,
        "date": 1,
        "chat": {"id": 1, "type": "private"},
        "business_connection_id": "b",
    }
    excluded = [
        message_update({"text": "hi", "business_connection_id": "b"}),
        message_update(
            {
                "text": "hi",
                "chat": {"id": CHAT_ID, "type": "supergroup", "is_direct_messages": True},
            }
        ),
    ]
    # The pure normalizer leaves them out too, not only receive.
    assert [telegram_chat.normalize(update, CONTEXT) for update in excluded] == [[], []]
    run(
        receive(
            api,
            recorder,
            *excluded,
            callback_update(
                {
                    **business,
                    "reply_markup": {"inline_keyboard": [[{"text": "a", "callback_data": "a"}]]},
                },
                "a",
            ),
        )
    )
    assert len(recorder.unhandled) == 3
    assert len(recorder.events) + len(recorder.clicks) == 0
    assert len(api.sent("answerCallbackQuery")) == 1


def test_keys_deliveries_by_bot_update_and_date_and_by_environment():
    update = message_update({"text": "hi"})
    key = telegram_chat.delivery_key(update, bot_id=BOT_ID)
    assert key == f"{BOT_ID}.{update['update_id']}.{update['message']['date']}"
    assert telegram_chat.delivery_key(update, bot_id=BOT_ID, environment="test") == f"test.{key}"


@testing.effect
def test_confirms_a_polled_update_only_after_it_ran():
    api = FakeApi()
    recorder = Recorder()
    last = message_update({"text": "two"})
    api.updates.append([message_update({"text": "one"}), last])

    @fx.gen
    def program() -> Gen[None]:
        yield from (
            telegram_chat.layer_polling()
            .pipe(layer.provide_merge(telegram_layer(api)))
            .pipe(layer.provide(chat_handler.layer(recorder.on_event)))
            .build()
        )
        yield from until(lambda: len(api.sent("getUpdates")) >= 2)
        start, next_ = api.sent("getUpdates")[:2]
        assert "offset" not in start
        assert next_["offset"] == last["update_id"] + 1
        assert len(recorder.events) == 2

    return fx.scoped(program)


# --- deadlines ----------------------------------------------------------------------------


@testing.effect
def test_answers_a_click_at_its_deadline_and_lets_its_handler_run_on():
    """deadlines / answers a click at its deadline and lets its handler run on, so a late
    commit is never repeated"""

    @fx.gen
    def program() -> Gen[None]:
        api = FakeApi()
        release: Deferred[None] = yield from Deferred[None].make()
        steps: list[str] = []
        recorder = Recorder(
            click=fx.sync(lambda: steps.append("started"))
            .and_then(release.wait())
            .and_then(fx.sync(lambda: steps.append("committed")))
        )
        fiber = yield from receive(api, recorder, click("approve")).fork()
        yield from until(lambda: len(steps) > 0)
        yield from testing.adjust("2499 millis")
        assert len(api.sent("answerCallbackQuery")) == 0
        yield from testing.adjust("1 millis")
        assert (yield from fiber.join()) == ["accepted"]
        assert len(api.sent("answerCallbackQuery")) == 1
        yield from release.succeed(None)
        yield from until(lambda: len(steps) > 1)
        assert steps == ["started", "committed"]

    return program


@testing.effect
def test_refuses_a_message_whose_handler_outlives_its_deadline_so_telegram_redelivers_it():
    """deadlines / refuses a message whose handler outlives its deadline, so Telegram
    redelivers it"""

    @fx.gen
    def program() -> Gen[None]:
        started: list[bool] = []
        recorder = Recorder(handle=fx.sync(lambda: started.append(True)).and_then(fx.never))
        fiber = yield from receive(FakeApi(), recorder, message_update({"text": "hi"})).fork()
        yield from until(lambda: bool(started))
        yield from testing.adjust("9999 millis")
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("1 millis")
        assert (yield from fiber.join()) == ["notAccepted"]

    return program


@testing.effect
def test_interrupts_a_command_at_its_deadline_and_still_counts_it_answered_never_as_a_message():
    """deadlines / interrupts a command at its deadline and still counts it answered, never
    as a message"""

    @fx.gen
    def program() -> Gen[None]:
        steps: list[str] = []
        recorder = Recorder(
            command=lambda: fx.never.on_interrupt(fx.sync(lambda: steps.append("interrupted")))
        )
        fiber = yield from receive(FakeApi(), recorder, command_update("deploy", "prod")).fork()
        yield from until(lambda: len(recorder.commands) > 0)
        yield from testing.adjust("9999 millis")
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("1 millis")
        assert (yield from fiber.join()) == ["accepted"]
        yield from until(lambda: len(steps) > 0)
        assert len(recorder.events) + len(recorder.unhandled) == 0

    return program


def test_gives_an_anonymous_admins_command_the_group_as_its_user():
    recorder = Recorder()
    # Telegram's stand-in ``from`` for anonymous group admins.
    anonymous = {
        "id": 1087968824,
        "is_bot": True,
        "first_name": "Group",
        "username": "GroupAnonymousBot",
    }
    run(
        receive(
            FakeApi(),
            recorder,
            command_update(
                "deploy",
                "",
                {
                    "from": anonymous,
                    "sender_chat": {"id": -1001, "type": "supergroup", "title": "G"},
                },
            ),
        )
    )
    assert [command.user_id for command in recorder.commands] == ["-1001"]


def test_gives_an_animation_one_attachment_not_its_document_copy_too():
    file = {"file_id": "anim", "file_unique_id": "u", "mime_type": "video/mp4"}
    [event] = telegram_chat.normalize(
        message_update(
            {"animation": {**file, "width": 1, "height": 1, "duration": 1}, "document": file}
        ),
        CONTEXT,
    )
    assert isinstance(event, MessageCreated)
    assert [a.id for a in event.message.attachments] == ["anim"]


def test_command_requests_refuses_ids_telegram_cant_register():
    good = ci.group(ci.command("deploy", description="Deploy"))
    bad = ci.group(ci.command("ship-it", description="Ship"))
    assert run(telegram_chat.command_requests(good)) == {
        "commands": [{"command": "deploy", "description": "Deploy"}]
    }
    assert is_failure(run(telegram_chat.command_requests(bad).exit()))


# --- interactions over both transports ----------------------------------------------------


def _with_interactions(recorder: Recorder, api: FakeApi) -> layer.Layer[Any, Any]:
    """What a transport layer is given: the adapter, a ``ChatHandler`` and a
    ``chat_interaction.Handler``."""
    return layer.merge(
        telegram_layer(api),
        chat_handler.layer(recorder.on_event),
        layer.succeed(ci.Handler, recorder.interactions()),
    )


@testing.effect
def test_hands_a_webhook_command_and_click_to_the_interaction_handler_the_layer_was_given():
    """The webhook runs each update in the request's context, where the
    ``chat_interaction.Handler`` given to the layer is not: it has to come
    from the layer, as polling's does."""
    recorder = Recorder(
        command=lambda: fx.succeed(ci.respond(markdown="pong", visibility="public"))
    )
    api = FakeApi()
    app = telegram_chat.layer_webhook(path="/telegram", secret_token=redacted(SECRET)).pipe(
        layer.provide(_with_interactions(recorder, api))
    )

    @fx.gen
    def program() -> Gen[None]:
        http = yield from router.in_memory_client(app)
        for update in (command_update("deploy", "prod"), click("approve")):
            sent = http_request.post("http://x").body_text(json.dumps(update), "application/json")
            answered = yield from http.post(
                "http://localhost/telegram",
                body=sent.body,
                headers={telegram_chat.SECRET_HEADER: SECRET},
            )
            assert answered.status == 200
        assert [command.text for command in recorder.commands] == ["prod"]
        assert [clicked.id for clicked in recorder.clicks] == ["approve"]
        assert recorder.events == []
        [answer] = api.sent("sendRichMessage")
        assert answer["chat_id"] == CHAT_ID

    return fx.scoped(program)


@testing.effect
def test_hands_a_polled_command_to_the_interaction_handler_the_layer_was_given():
    recorder = Recorder()
    api = FakeApi()
    api.updates.append([command_update("deploy", "prod")])

    @fx.gen
    def program() -> Gen[None]:
        yield from (
            telegram_chat.layer_polling().pipe(layer.provide(_with_interactions(recorder, api)))
        ).build()
        yield from until(lambda: len(api.sent("getUpdates")) >= 2)
        assert [command.text for command in recorder.commands] == ["prod"]

    return fx.scoped(program)


# --- polling deadlines --------------------------------------------------------------------


def _advance_until(done: Callable[[], bool], step: str = "100 millis") -> Effect[None]:
    """Moves the test clock a step at a time until ``done`` holds, at most 100 steps."""

    @fx.gen
    def loop() -> Gen[None]:
        for _ in range(100):
            if done():
                return
            yield from testing.adjust(step)
        assert done()

    return loop


@testing.effect
def test_gives_up_on_a_get_updates_that_never_answers_and_polls_again():
    """A connection that dies without a reset leaves ``getUpdates``
    unanswered: each call has the long poll plus a margin, then is retried."""
    api = FakeApi()
    api.updates.append([])  # the layer's own first call; then the fake never answers

    @fx.gen
    def program() -> Gen[None]:
        yield from (
            telegram_chat.layer_polling(timeout="1 second")
            .pipe(layer.provide_merge(telegram_layer(api)))
            .pipe(layer.provide(chat_handler.layer(Recorder().on_event)))
            .build()
        )
        yield from until(lambda: len(api.sent("getUpdates")) >= 2)
        # One second of long poll, plus three of margin.
        yield from testing.adjust("3999 millis")
        assert len(api.sent("getUpdates")) == 2
        yield from testing.adjust("1 millis")
        yield from _advance_until(lambda: len(api.sent("getUpdates")) >= 3)
        [*_, last] = api.sent("getUpdates")
        assert last["timeout"] == 1

    return fx.scoped(program)


# --- private answers ----------------------------------------------------------------------


def test_names_what_is_missing_when_it_refuses_a_private_answer():
    """``ci.respond`` answers privately by default, which Telegram has no
    way to send: the refusal says so, so the log line explains the silence."""
    recorder = Recorder(command=lambda: fx.succeed(ci.respond(markdown="secret")))
    run(receive(FakeApi(), recorder, command_update("deploy")))
    [error] = recorder.refused
    assert "ephemeral" in error.message
    assert error.reason.retry == "denied"


# --- escape_markdown ----------------------------------------------------------------------

UNTRUSTED = [
    "[x](http://evil)",
    "![x](http://evil/i.png)",
    "<http://evil>",
    "*bold* __strong__ _it_ ~~gone~~ `code`",
    "<b>&amp;</b>",
    "back\\slash \\[x\\](http://evil)",
    "$x$ ||spoiler|| ==mark==",
    "@everyone",
]
"""Display names a user picks, each of which forms syntax unescaped."""


def test_escape_markdown_keeps_user_text_literal_in_what_telegram_is_sent():
    """A dogfood app put display names into posts, and one name was a live
    link: ``escape_markdown`` makes each show as typed."""
    for name in UNTRUSTED:
        api = FakeApi()
        run(
            post(f"Deploy by {telegram_chat.escape_markdown(name)}.").pipe(
                fx.provide(telegram_layer(api))
            )
        )
        [sent] = api.sent("sendRichMessage")
        assert literal(sent["rich_message"]["markdown"]) == f"Deploy by {name}.", name


def test_unescaped_user_text_forms_a_link():
    api = FakeApi()
    run(post("Deploy by [x](http://evil).").pipe(fx.provide(telegram_layer(api))))
    [sent] = api.sent("sendRichMessage")
    assert literal(sent["rich_message"]["markdown"]) is None


# --- max_retry_after ----------------------------------------------------------------------


def test_fails_at_once_with_the_wait_when_retry_after_passes_max_retry_after():
    api = FakeApi()
    api.next["sendRichMessage"] = api_error(
        429, "Too Many Requests: retry after 3600", {"retry_after": 3600}
    )
    error = run(
        post("alert").flip().pipe(fx.provide(telegram_layer(api, max_retry_after="1 minute")))
    )
    assert type(error.reason).__name__ == "RateLimited"
    assert error.retry_after == seconds(3600)
    assert len(api.sent("sendRichMessage")) == 1


@testing.effect
def test_waits_out_a_retry_after_within_max_retry_after():
    api = FakeApi()
    api.next["sendRichMessage"] = api_error(
        429, "Too Many Requests: retry after 30", {"retry_after": 30}
    )

    @fx.gen
    def program() -> Gen[None]:
        fiber = yield from post("alert").fork()
        yield from testing.adjust("29 seconds")
        assert len(api.sent("sendRichMessage")) == 1
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert len(api.sent("sendRichMessage")) == 2

    return program.pipe(fx.provide(telegram_layer(api, max_retry_after="1 minute")))
