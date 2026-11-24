"""Port of Effect's ``packages/chat/slack/test/SlackChat.test.ts``: the Slack
adapter's ops over a scripted Web API, from the bodies it posts to its pacing,
rollbacks and stream cleanup."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from _slack_fake import (
    AUTH_TEST,
    BOT_USER_ID,
    CHANNEL,
    HANG,
    TEAM,
    Fake,
    Status,
    adapter,
    fixture,
    slack_layer,
)

import pyfect as fx
from pyfect import layer, testing
from pyfect._core import Effect
from pyfect.chat import chat, chat_ui
from pyfect.chat.chat_adapter import AppendResult, ChatAdapter, File, NativeStream
from pyfect.chat.chat_error import PlatformUnavailable
from pyfect.chat.chat_event import ChatEvent
from pyfect.chat.chat_message import ChatMessage
from pyfect.chat.chat_test import check_event, check_message
from pyfect.chat.slack import slack_chat
from pyfect.chat.slack._options import SlackPostOptions
from pyfect.chat.slack.slack_web_api import SlackWebApi
from pyfect.duration import seconds
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import make as redacted

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

ROOT = "1794509110.999799"
CHANNEL_THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL)
REPLY_THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL, thread_ts=ROOT)


def check_event_(event: ChatEvent) -> Effect[None, Any]:
    return check_event(event, platform="slack", parse_mention=slack_chat.parse_mention)


def check_message_(message: ChatMessage) -> Effect[None, Any]:
    return check_message(message, platform="slack", parse_mention=slack_chat.parse_mention)


def run(fake: Fake, program: Effect[Any, Any, Any]) -> Effect[Any, Any]:
    return program.pipe(fx.provide(slack_layer(fake)))


def posted(ts: str) -> dict[str, Any]:
    return {"ok": True, "channel": CHANNEL, "ts": ts}


def reason(effect: Effect[Any, Any, Any]) -> Effect[dict[str, Any], Any, Any]:
    return effect.flip().map(
        lambda error: {
            "op": error.op,
            "tag": type(error.reason).__name__,
            "detail": error.reason.detail,
            "retry": error.retry,
        }
    )


@testing.effect
def test_sends_a_markdown_block_and_an_escaped_text_with_unfurls_off():
    """post / sends a markdown block and an escaped text, with unfurls off"""
    fake = Fake({"chat.postMessage": posted("1794509200.000100")})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.post(REPLY_THREAD, markdown="hi <@U1> `<@U1>` & >")
        assert fake.called("chat.postMessage")[0].params == {
            "channel": CHANNEL,
            "thread_ts": ROOT,
            "blocks": json.dumps(
                [{"type": "markdown", "text": "hi &lt;@U1> `<@U1>` & >"}], separators=(",", ":")
            ),
            "text": "hi &lt;@U1&gt; `&lt;@U1&gt;` &amp; &gt;",
            "unfurl_links": "false",
            "unfurl_media": "false",
        }

    return run(fake, program)


@testing.effect
def test_with_post_options_allows_a_token_and_turns_unfurls_on():
    """post / withPostOptions allows a token and turns unfurls on"""
    fake = Fake({"chat.postMessage": posted("1794509200.000101")})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from (
            slack.post(CHANNEL_THREAD, markdown="hi <@U1> <@U2>")
            .pipe(slack_chat.with_post_options(SlackPostOptions(notify_users=("U1",))))
            .pipe(slack_chat.with_post_options(SlackPostOptions(unfurl=True)))
        )
        params = fake.called("chat.postMessage")[0].params
        assert json.loads(params["blocks"]) == [{"type": "markdown", "text": "hi <@U1> &lt;@U2>"}]
        assert params["text"] == "hi <@U1> &lt;@U2&gt;"
        assert params["unfurl_links"] == "true"

    return run(fake, program)


@testing.effect
def test_never_sends_an_empty_text_a_post_or_edit_with_no_markdown_fails_before_the_call():
    """post / never sends an empty text: a post or edit with no Markdown fails before the call"""
    fake = Fake({})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        assert (yield from reason(slack.post(CHANNEL_THREAD, markdown=""))) == {
            "op": "post",
            "tag": "InvalidRequest",
            "detail": "no_text",
            "retry": "denied",
        }
        assert (yield from reason(slack.edit(CHANNEL_THREAD, "1.2", markdown="")))[
            "detail"
        ] == "no_text"
        assert fake.calls == []

    return run(fake, program)


@testing.effect
def test_leaves_the_emoji_count_to_slack():
    """post / leaves the emoji count to Slack"""
    fake = Fake(
        {
            "chat.postMessage": [
                posted("1794509200.000100"),
                {"ok": False, "error": "msg_blocks_too_long"},
            ]
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        # 14,000 if `&lt;` cost 4, 11,000 as Slack counts it.
        yield from slack.post(CHANNEL_THREAD, markdown="😀" * 1_000 + "<" * 1_000)
        # 1,400 😀 are 14,000 with shortcodes: Slack refuses, nothing is posted.
        failure = yield from reason(slack.post(CHANNEL_THREAD, markdown="😀" * 1_400))
        assert failure == {
            "op": "post",
            "tag": "TooLarge",
            "detail": "msg_blocks_too_long",
            "retry": "denied",
        }

    return run(fake, program)


BUTTON = chat_ui.Button(id="go", label="Go <!channel>", value="v")


@testing.effect
def test_with_no_markdown_the_text_is_the_escaped_labels():
    """buttons and selects / with no Markdown, the text is the escaped labels"""
    fake = Fake({"chat.postMessage": posted("1794509200.000100")})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.post(CHANNEL_THREAD, markdown="", actions=[BUTTON])
        assert fake.called("chat.postMessage")[0].params["text"] == "Go &lt;!channel&gt;"

    return run(fake, program)


@testing.effect
def test_an_id_holding_the_adapters_separator_is_refused_before_any_call():
    """buttons and selects / an id holding the adapter's separator is refused before any call"""
    fake = Fake({})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        refused = chat_ui.Button(id="a␟b", label=BUTTON.label, value=BUTTON.value)
        failure = yield from reason(slack.post(CHANNEL_THREAD, markdown="x", actions=[refused]))
        assert (failure["tag"], failure["detail"]) == ("InvalidRequest", "invalid_action_id")
        assert fake.calls == []

    return run(fake, program)


def upload(ids: list[str]) -> dict[str, Any]:
    pending = iter(ids)

    def url(_: dict[str, Any]) -> dict[str, Any]:
        id = next(pending)
        return {"ok": True, "upload_url": f"https://files.slack.test/upload/{id}", "file_id": id}

    return {
        "files.getUploadURLExternal": url,
        "files.completeUploadExternal": {"ok": True, "files": [{"id": id} for id in ids]},
    }


def file(name: str) -> File:
    return File(name=name, content_type="text/plain", content=b"hello")


FILE_TS = "1794509300.000100"


@testing.effect
def test_uploads_completes_with_no_channel_posts_then_attaches_with_the_same_body():
    """files / uploads, completes with no channel, posts, then attaches with the same body"""
    fake = Fake({**upload(["F1", "F2"]), "chat.postMessage": posted(FILE_TS)})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.post(
            REPLY_THREAD, markdown="a" * 5_000, files=[file("a.txt"), file("b.txt")]
        )
        assert [call.method for call in fake.calls if not call.method.startswith("/upload/")] == [
            "files.getUploadURLExternal",
            "files.getUploadURLExternal",
            "files.completeUploadExternal",
            "chat.postMessage",
            "chat.update",
        ]
        complete = fake.called("files.completeUploadExternal")[0].params
        assert json.loads(complete["files"]) == [
            {"id": "F1", "title": "a.txt"},
            {"id": "F2", "title": "b.txt"},
        ]
        assert list(complete) == ["files"]
        post = fake.called("chat.postMessage")[0].params
        update = fake.called("chat.update")[0].params
        assert {**update, "file_ids": json.loads(update["file_ids"])} == {
            "channel": CHANNEL,
            "ts": FILE_TS,
            "blocks": post["blocks"],
            "text": post["text"],
            "file_ids": ["F1", "F2"],
        }
        # The text is cut to the update budget from the post on.
        assert len(post["text"].encode("utf-8")) <= 3_800

    return run(fake, program)


@testing.effect
def test_a_post_with_files_and_no_markdown_carries_the_escaped_file_names():
    """files / a post with files and no Markdown carries the escaped file names"""
    fake = Fake({**upload(["F1", "F2"]), "chat.postMessage": posted(FILE_TS)})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.post(
            CHANNEL_THREAD, markdown="", files=[file("*a*.txt"), file("<@U1>.csv")]
        )
        post = fake.called("chat.postMessage")[0].params
        assert json.loads(post["blocks"]) == [
            {"type": "markdown", "text": "\\*a\\*.txt, &lt;@U1>.csv"}
        ]
        assert post["text"] == "*a*.txt, &lt;@U1&gt;.csv"

    return run(fake, program)


@testing.effect
def test_a_long_retry_after_on_the_attach_is_cut_off_and_rolled_back_even_when_interrupted():
    """files / a long Retry-After on the attach is cut off by its deadline and rolled back, even
    when interrupted"""
    fake = Fake(
        {
            **upload(["F1"]),
            "chat.postMessage": posted(FILE_TS),
            "chat.update": Status(429, headers={"retry-after": "3600"}),
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        fiber = yield from slack.post(CHANNEL_THREAD, markdown="x", files=[file("a")]).fork()
        yield from testing.adjust("1 second")
        interrupting = yield from fiber.interrupt().fork()
        yield from testing.adjust("61 seconds")
        yield from interrupting.join()
        assert len(fake.called("chat.update")) == 1
        assert fake.called("chat.delete")[0].params == {"channel": CHANNEL, "ts": FILE_TS}
        assert [call.params["file"] for call in fake.called("files.delete")] == ["F1"]

    return run(fake, program)


@testing.effect
def test_a_rollback_that_cant_delete_the_message_fails_uncertain_with_slack_attach_failed():
    """files / a rollback that can't delete the message fails uncertain with SlackAttachFailed"""
    fake = Fake(
        {
            **upload(["F1", "F2"]),
            "chat.postMessage": posted(FILE_TS),
            "chat.update": {"ok": False, "error": "file_not_found"},
            "chat.delete": {"ok": False, "error": "cant_delete_message"},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        error = yield from slack.post(
            REPLY_THREAD, markdown="x", files=[file("a"), file("b")]
        ).flip()
        assert (type(error.reason).__name__, error.reason.detail, error.retry) == (
            "Unknown",
            "attach_failed_message_left",
            "uncertain",
        )
        cause = error.reason.cause
        assert isinstance(cause, slack_chat.SlackAttachFailed)
        assert cause.thread == REPLY_THREAD
        assert cause.message_id == FILE_TS
        assert cause.file_ids == ("F1", "F2")
        # The files are kept, so the ids it carries still mean something.
        assert fake.called("files.delete") == []

    return run(fake, program)


@testing.effect
def test_maps_slacks_answers_and_never_repeats_a_write_that_may_have_landed():
    """errors / maps Slack's answers, and never repeats a write that may have landed"""
    fake = Fake(
        {
            "chat.update": {"ok": False, "error": "invalid_auth"},
            "chat.postMessage": Status(500),
            "conversations.info": Status(429, headers={"retry-after": "7"}),
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        assert (yield from reason(slack.edit(CHANNEL_THREAD, "1.2", markdown="x"))) == {
            "op": "edit",
            "tag": "Unauthenticated",
            "detail": "invalid_auth",
            "retry": "denied",
        }
        assert (yield from reason(slack.post(CHANNEL_THREAD, markdown="x"))) == {
            "op": "post",
            "tag": "PlatformUnavailable",
            "detail": "http_500",
            "retry": "uncertain",
        }
        assert len(fake.called("chat.postMessage")) == 1
        api = yield from SlackWebApi()
        limited = yield from api.call(
            "conversations.info", {"channel": CHANNEL}, retry=False
        ).flip()
        assert type(limited.reason).__name__ == "RateLimited"
        assert limited.retry_after == seconds(7)

    return run(fake, program)


@testing.effect
def test_fetch_message_normalises_what_slack_stored():
    """reads / fetchMessage normalises what Slack stored"""
    replies = next(
        call
        for call in fixture("recorded", "markdown-mentions")["calls"]
        if call["method"] == "conversations.replies"
    )["response"]
    fake = Fake({"auth.test": AUTH_TEST, "conversations.replies": replies})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        message = yield from slack.fetch_message(CHANNEL_THREAD, "1794509003.143939")
        yield from check_message_(message)
        assert len(message.mentions) == 2
        # The thread's channel, with both bounds at the message, inclusive, or Slack
        # leaves the message out.
        params = fake.called("conversations.replies")[0].params
        assert {k: params[k] for k in ("channel", "latest", "oldest", "inclusive")} == {
            "channel": CHANNEL,
            "latest": "1794509003.143939",
            "oldest": "1794509003.143939",
            "inclusive": "true",
        }

    return run(fake, program)


@testing.effect
def test_thread_history_pages_in_both_directions_from_exclusive():
    """reads / thread history pages in both directions, from exclusive"""

    def message(ts: str) -> dict[str, Any]:
        return {"ts": ts, "thread_ts": ROOT, "user": "U080YLYB277", "text": ts}

    fake = Fake(
        {
            "auth.test": AUTH_TEST,
            "conversations.replies": [
                {
                    "ok": True,
                    "messages": [message(ROOT), message("1794509111.000001")],
                    "response_metadata": {"next_cursor": "page2"},
                },
                {
                    "ok": True,
                    "messages": [
                        message(ROOT),
                        message("1794509112.000001"),
                        message("1794509113.000001"),
                    ],
                },
            ],
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        forward = yield from slack.history(REPLY_THREAD, direction="forward").run_collect()
        assert [m.id for m in forward] == [
            ROOT,
            "1794509111.000001",
            "1794509112.000001",
            "1794509113.000001",
        ]
        backward = yield from slack.history(
            REPLY_THREAD, direction="backward", from_="1794509113.000001"
        ).run_collect()
        assert [m.id for m in backward] == ["1794509112.000001", ROOT]

    return run(fake, program)


@testing.effect
def test_get_thread():
    """reads / getThread"""
    fake = Fake(
        {
            "conversations.info": {
                "ok": True,
                "channel": {
                    "id": CHANNEL,
                    "name": "chat-testing-123",
                    "created": 1794400000,
                    "topic": {"value": "tests"},
                },
            }
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        info = yield from slack.get_thread(CHANNEL_THREAD)
        assert (info.kind, info.name, info.topic) == ("channel", "chat-testing-123", "tests")
        thread = yield from slack.get_thread(REPLY_THREAD)
        assert thread.kind == "thread"
        assert thread.parent == CHANNEL_THREAD

    return run(fake, program)


@testing.effect
def test_stops_an_open_stream_first():
    """delete / stops an open stream first"""
    fake = Fake(
        {
            "chat.delete": [{"ok": False, "error": "cant_delete_message"}, {"ok": True}],
            "chat.stopStream": {"ok": True},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.delete(REPLY_THREAD, "1794509111.134189")
        assert [call.method for call in fake.calls] == [
            "chat.delete",
            "chat.stopStream",
            "chat.delete",
        ]

    return run(fake, program)


TS = "1794509111.134189"
RECIPIENT = "U080YLYB277"


def native() -> Effect[NativeStream, Any, Any]:
    def stream_of(found: ChatAdapter) -> NativeStream:
        stream = found.native_stream
        assert stream is not None
        return stream

    return adapter.map(stream_of)


@testing.effect
def test_is_unsupported_off_a_thread_without_a_recipient_or_when_turned_off():
    """nativeStream / is unsupported off a thread, without a recipient, or when turned off"""

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        cases = [
            stream.start(CHANNEL_THREAD, markdown="x", recipient="U1"),
            stream.start(REPLY_THREAD, markdown="x"),
            stream.start(REPLY_THREAD, markdown="x", recipient="U1").pipe(
                slack_chat.with_post_options(SlackPostOptions(native_stream=False))
            ),
        ]
        for start in cases:
            assert (yield from reason(start))["tag"] == "Unsupported"

    return run(Fake({}), program)


@testing.effect
def test_closed_too_large_and_stopped():
    """nativeStream / closed, too large and stopped"""
    fake = Fake(
        {
            "chat.startStream": posted(TS),
            "chat.appendStream": [
                {"ok": False, "error": "message_not_in_streaming_state"},
                {"ok": False, "error": "stopped_by_user"},
            ],
            "agents.sessions.setStatus": {"ok": True},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="a" * 11_990, recipient="U1")
        too_large = yield from reason(stream.append(REPLY_THREAD, TS, "b" * 11, flush=True))
        assert too_large["tag"] == "TooLarge"
        assert fake.called("chat.appendStream") == []
        assert (yield from stream.append(REPLY_THREAD, TS, "c", flush=True)) == AppendResult(
            "closed", 0
        )
        suspended = slack_chat.with_post_options(
            SlackPostOptions(session_status_at_end="suspended")
        )
        appended = yield from stream.append(REPLY_THREAD, TS, "d", flush=True).pipe(suspended)
        assert appended == AppendResult("stopped", 0)
        # The layer sends no stop after a stopped append, so the append moves the
        # session off processing.
        assert [call.params for call in fake.called("agents.sessions.setStatus")] == [
            {"channel_id": CHANNEL, "thread_ts": ROOT, "status": "suspended"}
        ]

    return run(fake, program)


@testing.effect
def test_rotates_with_processing_and_stops_asking_once_slack_says_not_authorized():
    """nativeStream / rotates with processing, and stops asking once Slack says not_authorized"""
    fake = Fake(
        {
            "chat.stopStream": lambda params: (
                {"ok": False, "error": "not_authorized"}
                if "session_status" in params
                else {
                    "ok": True,
                    "message": {"ts": TS, "ai_context": {"result_status": "stopped_by_user"}},
                }
            ),
            "agents.sessions.setStatus": {"ok": False, "error": "not_authorized"},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        assert (yield from stream.stop(REPLY_THREAD, TS, end="rotating")) is True
        assert [call.params.get("session_status") for call in fake.called("chat.stopStream")] == [
            "processing",
            None,
        ]
        # Not a declared agent: no more session status, and a reply never fails over it.
        assert (yield from stream.stop(REPLY_THREAD, TS, end="done")) is True
        assert len(fake.called("chat.stopStream")) == 3
        assert "session_status" not in fake.called("chat.stopStream")[2].params
        assert fake.called("agents.sessions.setStatus") == []

    return run(fake, program)


@testing.effect
def test_after_a_429_the_replys_next_part_waits_then_doubles_and_another_reply_does_not():
    """nativeStream / after a 429 the reply's next part waits, then doubles its interval, and
    another reply does not"""
    next_ = "1794509201.000100"
    other = "1794509202.000100"
    fake = Fake(
        {
            "chat.appendStream": [
                Status(429, headers={"retry-after": "3"}),
                posted(other),
                posted(next_),
            ],
            "chat.stopStream": {"ok": True, "message": {"ts": TS}},
            "chat.startStream": [posted(other), posted(next_)],
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        assert (yield from reason(stream.append(REPLY_THREAD, TS, "a", flush=True)))[
            "tag"
        ] == "RateLimited"
        yield from stream.stop(REPLY_THREAD, TS, end="rotating")
        # Another reply in the thread starts and appends at once.
        yield from stream.start(REPLY_THREAD, markdown="x", recipient=RECIPIENT)
        assert fake.called("chat.startStream")[0].params == {
            "channel": CHANNEL,
            "thread_ts": ROOT,
            "recipient_user_id": RECIPIENT,
            "recipient_team_id": TEAM,
            "markdown_text": "x",
        }
        yield from stream.append(REPLY_THREAD, other, "y", flush=True)
        assert len(fake.called("chat.appendStream")) == 2
        # The reply's next part waits for the retry-after.
        start = yield from stream.start(
            REPLY_THREAD, markdown="b", recipient=RECIPIENT, continues=TS
        ).fork()
        yield from testing.adjust("2999 millis")
        assert len(fake.called("chat.startStream")) == 1
        yield from testing.adjust("1 millis")
        assert (yield from start.join()).id == next_
        # Its appends keep the doubled interval, two seconds.
        append = yield from stream.append(REPLY_THREAD, next_, "c", flush=True).fork()
        yield from testing.adjust("1999 millis")
        assert len(fake.called("chat.appendStream")) == 2
        yield from testing.adjust("1 millis")
        yield from append.join()
        assert len(fake.called("chat.appendStream")) == 3

    return run(fake, program)


@testing.effect
def test_an_edit_retried_after_a_429_keeps_the_doubled_interval():
    """nativeStream / an edit retried after a 429 keeps the doubled interval"""
    fake = Fake(
        {"chat.update": [Status(429, headers={"retry-after": "1"}), {"ok": True}, {"ok": True}]}
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        first = yield from slack.edit(REPLY_THREAD, TS, markdown="a").fork()
        yield from testing.adjust("1 second")
        yield from first.join()
        assert len(fake.called("chat.update")) == 2
        # Six seconds, twice the three second floor.
        second = yield from slack.edit(REPLY_THREAD, TS, markdown="ab").fork()
        yield from testing.adjust("5999 millis")
        assert len(fake.called("chat.update")) == 2
        yield from testing.adjust("1 millis")
        yield from second.join()
        assert len(fake.called("chat.update")) == 3

    return run(fake, program)


@testing.effect
def test_edits_to_one_message_are_three_seconds_apart():
    """nativeStream / edits to one message are three seconds apart"""
    other = "1794509200.000200"
    fake = Fake({"chat.update": {"ok": True}})

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        yield from slack.edit(REPLY_THREAD, TS, markdown="a")
        second = yield from slack.edit(REPLY_THREAD, TS, markdown="ab").fork()
        # Another message is not held back.
        yield from slack.edit(REPLY_THREAD, other, markdown="x")
        yield from testing.adjust("2999 millis")
        assert len(fake.called("chat.update")) == 2
        yield from testing.adjust("1 millis")
        yield from second.join()
        assert len(fake.called("chat.update")) == 3

    return run(fake, program)


Z = "\u200b"


@testing.effect
def test_rewrites_a_stream_whose_appends_differ_from_the_block_once_after_the_stop():
    """nativeStream / the cleanup edit / rewrites a stream whose appends differ from the block,
    once, after the stop, with no actions"""
    fake = Fake({"chat.startStream": posted(TS), "chat.appendStream": posted(TS)})

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="Hi <@U2> ", recipient=RECIPIENT)
        yield from stream.append(REPLY_THREAD, TS, "and `<@U3>` a < b", flush=True)
        assert fake.called("chat.startStream")[0].params["markdown_text"] == f"Hi <{Z}@U2> "
        assert (
            fake.called("chat.appendStream")[0].params["markdown_text"]
            == f"and `<{Z}@U3>` a &lt; b"
        )
        yield from stream.stop(REPLY_THREAD, TS, end="done")
        assert [call.method for call in fake.calls][-2:] == ["chat.stopStream", "chat.update"]
        assert [
            {**call.params, "blocks": json.loads(call.params["blocks"])}
            for call in fake.called("chat.update")
        ] == [
            {
                "channel": CHANNEL,
                "ts": TS,
                "blocks": [{"type": "markdown", "text": "Hi &lt;@U2> and `<@U3>` a &lt; b"}],
                "text": "Hi &lt;@U2&gt; and `&lt;@U3&gt;` a &lt; b",
            }
        ]

    return run(fake, program)


@testing.effect
def test_runs_again_on_a_stop_sent_after_one_interrupted_during_it():
    """nativeStream / the cleanup edit / runs again on a stop sent after one interrupted
    during it"""
    fake = Fake(
        {
            "chat.startStream": posted(TS),
            "chat.stopStream": [
                {"ok": True, "result_status": "stopped_by_user"},
                {"ok": False, "error": "message_not_in_streaming_state"},
            ],
            "chat.update": [HANG, posted(TS)],
            "agents.sessions.setStatus": {"ok": True},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="<@U2>", recipient=RECIPIENT)
        first = yield from stream.stop(REPLY_THREAD, TS, end="done").fork()
        yield from testing.adjust("1 millis")
        assert len(fake.called("chat.update")) == 1
        yield from first.interrupt()
        # Slack answers this one as not streaming, so the user's stop is known from the first.
        assert (yield from stream.stop(REPLY_THREAD, TS, end="done")) is True
        assert len(fake.called("chat.update")) == 2
        assert len(fake.called("agents.sessions.setStatus")) == 1

    return run(fake, program)


@testing.effect
def test_runs_when_an_append_finds_the_stream_stopped_by_the_user_and_only_once():
    """nativeStream / the cleanup edit / runs when an append finds the stream stopped by the user,
    and only once"""
    fake = Fake(
        {
            "chat.startStream": posted(TS),
            "chat.appendStream": {"ok": False, "error": "stopped_by_user"},
            "chat.stopStream": {"ok": False, "error": "message_not_in_streaming_state"},
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="a <@U2>", recipient=RECIPIENT)
        yield from stream.append(REPLY_THREAD, TS, " b", flush=True)
        assert [json.loads(call.params["blocks"]) for call in fake.called("chat.update")] == [
            [{"type": "markdown", "text": "a &lt;@U2>"}]
        ]
        assert (yield from stream.stop(REPLY_THREAD, TS, end="done")) is True
        assert len(fake.called("chat.update")) == 1

    return run(fake, program)


@testing.effect
def test_runs_with_the_session_status_on_the_stops_after_that_append_is_cut_off():
    """nativeStream / the cleanup edit / runs, with the session status, on the stops after that
    append is cut off"""
    fake = Fake(
        {
            "chat.startStream": posted(TS),
            "chat.appendStream": {"ok": False, "error": "stopped_by_user"},
            "chat.stopStream": {"ok": False, "error": "message_not_in_streaming_state"},
            "chat.update": [HANG, posted(TS)],
            "agents.sessions.setStatus": [HANG, {"ok": True}],
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="a <@U2>", recipient=RECIPIENT)
        # Cut off during the cleanup.
        appended = yield from stream.append(REPLY_THREAD, TS, " b", flush=True).fork()
        yield from testing.adjust("1 millis")
        yield from appended.interrupt()
        assert len(fake.called("chat.update")) == 1
        assert fake.called("agents.sessions.setStatus") == []
        # The finaliser's stop, cut off during the session status.
        stopping = yield from stream.stop(REPLY_THREAD, TS, end="done").fork()
        yield from testing.adjust("1 millis")
        yield from stopping.interrupt()
        assert len(fake.called("chat.update")) == 2
        assert len(fake.called("agents.sessions.setStatus")) == 1
        assert (yield from stream.stop(REPLY_THREAD, TS, end="done")) is True
        assert [call.params for call in fake.called("agents.sessions.setStatus")] == [
            {"channel_id": CHANNEL, "thread_ts": ROOT, "status": "active"},
            {"channel_id": CHANNEL, "thread_ts": ROOT, "status": "active"},
        ]
        # A stop sent again sets it no third time.
        yield from stream.stop(REPLY_THREAD, TS, end="done")
        assert len(fake.called("agents.sessions.setStatus")) == 2
        assert len(fake.called("chat.update")) == 2

    return run(fake, program)


@testing.effect
def test_holds_a_trailing_high_surrogate_and_sends_any_other_lone_surrogate_as_ufffd():
    """nativeStream / holds a trailing high surrogate and sends any other lone surrogate
    as U+FFFD"""
    fake = Fake({"chat.startStream": posted(TS), "chat.appendStream": posted(TS)})

    @fx.gen
    def program() -> Gen[None]:
        stream = yield from native()
        yield from stream.start(REPLY_THREAD, markdown="x\udc00", recipient="U1")
        assert (yield from stream.append(REPLY_THREAD, TS, "a\ud83d")) == AppendResult("open", 1)
        assert (yield from stream.append(REPLY_THREAD, TS, "\ud83d")) == AppendResult("open", 1)
        # With an unclosed < as well, the longer tail. A Python string holds
        # Effect's "😀" as one code point.
        assert (yield from stream.append(REPLY_THREAD, TS, "😀 <\ud83d")) == AppendResult("open", 2)
        assert (yield from stream.append(REPLY_THREAD, TS, "<\ud83d", flush=True)) == AppendResult(
            "open", 0
        )
        assert fake.called("chat.startStream")[0].params["markdown_text"] == "x�"
        assert [call.params["markdown_text"] for call in fake.called("chat.appendStream")] == [
            "a",
            "😀 ",
            "&lt;�",
        ]

    return run(fake, program)


@testing.effect
def test_bot_user_id_and_user():
    """SlackChat / botUserId and user"""
    fake = Fake(
        {
            "auth.test": AUTH_TEST,
            "users.info": {
                "ok": True,
                "user": {
                    "id": "U0EXT",
                    "team_id": "T0OTHER",
                    "name": "ext",
                    "is_restricted": True,
                    "is_stranger": True,
                    "profile": {"display_name": "Ext"},
                },
            },
        }
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from slack_chat.SlackChat()
        assert (yield from slack.bot_user_id) == BOT_USER_ID
        user = yield from slack.user("U0EXT")
        assert (user.id, user.team_id, user.name, user.is_restricted, user.is_stranger) == (
            "U0EXT",
            "T0OTHER",
            "Ext",
            True,
            True,
        )

    return run(fake, program)


@testing.effect
def test_base_url_sends_every_web_api_call_to_the_given_host():
    # GovSlack serves the Web API from slack-gov.com.
    urls: list[str] = []

    def answer(request: HttpClientRequest) -> Effect[HttpClientResponse, HttpClientError]:
        urls.append(request.url)
        return fx.succeed(
            http_response.make(
                request, json.dumps(AUTH_TEST), headers={"content-type": "application/json"}
            )
        )

    gov = (
        slack_chat.layer(
            bot_token=redacted("xoxb-test"), team_id=TEAM, base_url="https://slack-gov.com/api"
        )
        .pipe(layer.provide_merge(chat.layer))
        .pipe(layer.provide(client.layer_test(answer)))
    )

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from slack_chat.SlackChat()
        assert (yield from slack.bot_user_id) == BOT_USER_ID
        api = yield from SlackWebApi()
        yield from api.call("conversations.info", {"channel": CHANNEL})
        assert urls == [
            "https://slack-gov.com/api/auth.test",
            "https://slack-gov.com/api/conversations.info",
        ]

    return program.pipe(fx.provide(gov))


def test_emoji_in_both_directions() -> None:
    """SlackChat / emoji in both directions"""
    assert slack_chat.emoji_from_name(":+1::skin-tone-3:") == "👍🏼"
    assert slack_chat.emoji_to_name("👍") == "+1"
    assert slack_chat.emoji_to_name("❤") == "heart"
    assert slack_chat.emoji_from_name("party-parrot") is None


def test_slack_attach_failed_keeps_the_ids_out_of_its_message() -> None:
    # The ids are for code that cleans up, not for logs.
    error = slack_chat.SlackAttachFailed(
        thread=REPLY_THREAD,
        message_id="1794509300.000100",
        file_ids=("F0SECRETFILE",),
        reason=PlatformUnavailable(retry="retry", detail="http_503"),
    )
    for shown in (str(error), error.message):
        assert "1794509300.000100" not in shown
        assert "F0SECRETFILE" not in shown
        assert ROOT not in shown
        assert "http_503" in shown
