"""Port of Effect's ``packages/chat/discord/test/DiscordChat.test.ts``: the
Discord adapter's ops over a scripted REST API, from the bodies it posts to
history, openers, downloads and dispatches without a channel type."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from _discord_fake import (
    BOT_USER_ID,
    GUILD,
    SCRATCH,
    Fake,
    adapter,
    answer,
    discord_layer,
    dispatch,
    error_response,
    events,
    status_code_error,
    step,
)

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat.chat_adapter import ChatAdapter, File
from pyfect.chat.chat_error import RateLimited
from pyfect.chat.chat_event import ChatEvent, MessageCreated
from pyfect.chat.chat_handler import ChatHandler, NotAccepted
from pyfect.chat.chat_handler import Service as HandlerService
from pyfect.chat.chat_message import Attachment, ReplyTo
from pyfect.chat.chat_ui import Button, LinkButton, Select, SelectOption
from pyfect.chat.discord import discord_chat
from pyfect.chat.discord.discord_chat import DiscordPostOptions
from pyfect.duration import millis

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def with_adapter(
    handlers: dict[str, Callable[..., object]],
    body: Callable[[ChatAdapter, Fake], Effect[Any, Any, Any]],
) -> Effect[Any, Any]:
    """Runs ``body`` with the adapter over a fake answering from ``handlers``."""
    fake = Fake(handlers)
    return adapter.flat_map(lambda discord: body(discord, fake)).pipe(
        fx.provide(discord_layer(fake))
    )


def one(f: Callable[[str], object]) -> Callable[..., object]:
    """A handler of the call's first argument."""
    return lambda *args: f(args[0])


def two(f: Callable[[str, str], object]) -> Callable[..., object]:
    """A handler of the call's first two arguments."""
    return lambda *args: f(args[0], args[1])


def reason(effect: Effect[Any, Any, Any]) -> Effect[dict[str, Any], Any, Any]:
    return effect.flip().map(
        lambda error: {
            "op": error.op,
            "tag": type(error.reason).__name__,
            "detail": error.reason.detail,
            "retry": error.retry,
        }
    )


CHANNEL = discord_chat.thread(SCRATCH)
POSTED = step("posts", "channel-plain")["response"]
ANSWERS: dict[str, Callable[..., object]] = {"createMessage": lambda *_: POSTED}

HISTORY = step("history", "thread-history")
THREAD_ID: str = step("history", "thread-start")["response"]["id"]
THREAD = discord_chat.thread(THREAD_ID)
THREAD_CHANNEL = step("history", "thread-get-channel")["response"]


def forbidden(*_: object) -> object:
    return error_response(403, {"code": 50001, "message": "Missing Access"})


NO_MENTIONS: dict[str, object] = {"parse": [], "users": [], "roles": [], "replied_user": False}


def calls(fake: Fake) -> list[Any]:
    """Every call but the bot user's lookup, which the layer makes on its own."""
    return [call for call in fake.calls if call.method != "getMyUser"]


# --- post ------------------------------------------------------------------------------


@testing.effect
def test_sends_the_markdown_as_is_notifying_nobody_and_suppressing_embeds_with_its_files():
    """post / sends the Markdown as is, notifying nobody and suppressing embeds, with its files"""
    content = b"hello from effect/chat\n"

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            yield from discord.post(
                CHANNEL,
                markdown="hi <@1> @everyone **bold**",
                files=[File("fixture.txt", "application/x-effect-fixture", content)],
            )
            assert fake.called("createMessage") == [
                (
                    SCRATCH,
                    {
                        "content": "hi <@1> @everyone **bold**",
                        "allowed_mentions": NO_MENTIONS,
                        "flags": 4,
                        "attachments": [{"id": "0", "filename": "fixture.txt"}],
                    },
                )
            ]
            # The multipart part for attachment 0, sent with the message.
            [[file]] = [files for (files,) in fake.called("withFiles")]
            assert (file.name, file.content_type, file.content) == (
                "fixture.txt",
                "application/x-effect-fixture",
                content,
            )

        return run

    return with_adapter(ANSWERS, body)


@testing.effect
def test_with_post_options_sets_mentions_embeds_and_the_reference_merging_nested_calls():
    """post / withPostOptions sets mentions, embeds and the reference, merging nested calls"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            yield from (
                discord.post(CHANNEL, markdown="hi", reply_to=ReplyTo(message_id="42"))
                .pipe(
                    discord_chat.with_post_options(
                        DiscordPostOptions(
                            notify_users=("1",),
                            notify_roles=("2",),
                            notify_everyone=True,
                            notify_replied_user=True,
                        )
                    )
                )
                .pipe(
                    discord_chat.with_post_options(
                        DiscordPostOptions(suppress_embeds=False, fail_if_not_exists=False)
                    )
                )
            )
            assert fake.called("createMessage")[0][1] == {
                "content": "hi",
                "allowed_mentions": {
                    "parse": ["everyone"],
                    "users": ["1"],
                    "roles": ["2"],
                    "replied_user": True,
                },
                "flags": 0,
                "message_reference": {"message_id": "42", "fail_if_not_exists": False},
            }

        return run

    return with_adapter(ANSWERS, body)


@testing.effect
def test_counts_the_2000_limit_in_code_points_failing_past_it_without_a_call():
    """post / counts the 2,000 limit in code points, failing past it without a call"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from reason(discord.post(CHANNEL, markdown="a" * 2001))) == {
                "op": "post",
                "tag": "TooLarge",
                "detail": "message_too_long",
                "retry": "denied",
            }
            assert calls(fake) == []
            # 2,000 astral emoji are 4,000 UTF-16 units, and Discord took them.
            yield from discord.post(CHANNEL, markdown="\U0001f600" * 2000)
            assert len(fake.called("createMessage")) == 1

        return run

    return with_adapter(ANSWERS, body)


@testing.effect
def test_maps_discords_failures_sending_a_write_once_and_a_5xx_on_it_as_uncertain():
    """post / maps Discord's failures, sending a write once and a 5xx on it as uncertain"""
    cases = [
        (
            answer(step("errors", "post-unknown-channel")),
            {"tag": "NotFound", "detail": "10003", "retry": "denied"},
        ),
        (
            answer(step("errors", "length-2001-ascii")),
            {"tag": "TooLarge", "detail": "50035", "retry": "denied"},
        ),
        (
            status_code_error(502),
            {"tag": "PlatformUnavailable", "detail": "http_502", "retry": "uncertain"},
        ),
    ]

    def one(failure: object, expected: dict[str, str]) -> Effect[None, Any]:
        def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
            @fx.gen
            def run() -> Gen[None]:
                assert (yield from reason(discord.post(CHANNEL, markdown="x"))) == {
                    "op": "post",
                    **expected,
                }
                assert len(calls(fake)) == 1

            return run

        return with_adapter({"createMessage": lambda *_: failure}, body)

    return fx.for_each(cases, lambda case: one(*case), discard=True)


@testing.effect
def test_a_5xx_on_a_read_is_retried():
    """post / a 5xx on a read is retried"""
    attempts = [0]

    def get_message(*_: object) -> object:
        attempts[0] += 1
        return status_code_error(503) if attempts[0] <= 1 else POSTED

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            fiber = yield from discord.fetch_message(CHANNEL, POSTED["id"]).fork()
            yield from testing.adjust("1 second")
            assert (yield from fiber.join()).id == POSTED["id"]

        return run

    return with_adapter({"getMessage": get_message}, body)


@testing.effect
def test_rejects_an_address_that_is_not_a_discord_channel_id():
    """post / rejects an address that is not a Discord channel id"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            result = yield from reason(discord.post(discord_chat.thread("../C123"), markdown="x"))
            assert result["tag"] == "InvalidRequest"
            assert calls(fake) == []

        return run

    return with_adapter({}, body)


@testing.effect
def test_a_post_answer_with_an_invalid_timestamp_fails_instead_of_throwing():
    """post / a post answer with an invalid timestamp fails instead of throwing"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            result = yield from reason(discord.post(CHANNEL, markdown="x"))
            assert [result["tag"], result["detail"]] == ["Unknown", "invalid_timestamp"]

        return run

    return with_adapter({"createMessage": lambda *_: {**POSTED, "timestamp": "not a date"}}, body)


@testing.effect
def test_the_adapters_own_file_count_and_size_check_is_file_refused_without_a_call():
    """post / the adapter's own file count and size check is file_refused, without a call"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        limits = discord.descriptor.limits
        file = File("fixture.txt", "text/plain", b"\0")
        too_many = [file] * (limits.files_per_message + 1)
        too_big = [File("fixture.txt", "text/plain", bytes(limits.upload_bytes + 1))]

        @fx.gen
        def run() -> Gen[None]:
            for files in (too_many, too_big):
                assert (yield from reason(discord.post(CHANNEL, markdown="x", files=files))) == {
                    "op": "post",
                    "tag": "TooLarge",
                    "detail": "file_refused",
                    "retry": "denied",
                }
            assert calls(fake) == []

        return run

    return with_adapter({}, body)


# --- actions ---------------------------------------------------------------------------


@testing.effect
def test_go_out_as_action_rows_five_buttons_to_a_row_and_a_select_alone_in_its_row():
    """actions / go out as action rows: five buttons to a row and a select alone in its row"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            yield from discord.post(
                CHANNEL,
                markdown="x",
                actions=[
                    Button(id="go", label="Go", style="primary", value="v"),
                    Button(id="stop", label="Stop", style="danger"),
                    LinkButton(label="Docs", url="https://effect.website"),
                    Select(
                        id="pick",
                        options=(
                            SelectOption(label="A", value="a"),
                            SelectOption(label="B", value="b"),
                        ),
                        selected="b",
                    ),
                    *(Button(id=f"b{i}", label=f"B{i}") for i in range(6)),
                ],
            )
            assert fake.called("createMessage")[0][1]["components"] == [
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 1, "label": "Go", "custom_id": "go␟v"},
                        {"type": 2, "style": 4, "label": "Stop", "custom_id": "stop"},
                        {"type": 2, "style": 5, "label": "Docs", "url": "https://effect.website"},
                    ],
                },
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 3,
                            "custom_id": "pick",
                            "options": [
                                {"label": "A", "value": "a"},
                                {"label": "B", "value": "b", "default": True},
                            ],
                            "min_values": 1,
                            "max_values": 1,
                        }
                    ],
                },
                *(
                    {
                        "type": 1,
                        "components": [
                            {"type": 2, "style": 2, "label": f"B{i}", "custom_id": f"b{i}"}
                            for i in row
                        ],
                    }
                    for row in ([0, 1, 2, 3, 4], [5])
                ),
            ]

        return run

    return with_adapter(ANSWERS, body)


@testing.effect
def test_an_id_holding_the_join_which_would_forge_a_value_or_a_sixth_row_fails_before_the_call():
    """actions / an id holding the join, which would forge a value, or a sixth row fails before the
    call"""

    def select(id: str) -> Select:
        return Select(id=id, options=(SelectOption(label="A", value="a"),))

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            cases: list[tuple[list[Any], list[str]]] = [
                ([Button(id="a␟b", label="x")], ["InvalidRequest", "invalid_action_id"]),
                # Six selects are six rows, one past Discord's five, though far under 25 actions.
                ([select(str(i)) for i in range(1, 7)], ["TooLarge", "too_many_actions"]),
            ]
            for actions, expected in cases:
                result = yield from reason(discord.post(CHANNEL, markdown="x", actions=actions))
                assert [result["tag"], result["detail"]] == expected
            assert calls(fake) == []

        return run

    return with_adapter({}, body)


@testing.effect
def test_edit_sends_allowed_mentions_and_the_suppress_embeds_flag():
    """edit sends allowed_mentions and the SUPPRESS_EMBEDS flag"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            yield from discord.edit(CHANNEL, "1", markdown="now with https://effect.website")
            assert fake.called("updateMessage") == [
                (
                    SCRATCH,
                    "1",
                    {
                        "content": "now with https://effect.website",
                        "allowed_mentions": NO_MENTIONS,
                        "flags": 4,
                        "components": [],
                    },
                )
            ]

        return run

    return with_adapter({"updateMessage": lambda *_: POSTED}, body)


@testing.effect
def test_edit_fails_too_large_past_2000_code_points_without_a_call():
    """edit fails TooLarge past 2,000 code points without a call"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from reason(discord.edit(CHANNEL, "1", markdown="a" * 2001))) == {
                "op": "edit",
                "tag": "TooLarge",
                "detail": "message_too_long",
                "retry": "denied",
            }
            assert calls(fake) == []

        return run

    return with_adapter({}, body)


@testing.effect
def test_edit_and_delete_refuse_a_message_id_that_is_not_a_snowflake_without_a_call():
    """edit and delete refuse a message id that is not a snowflake, without a call"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            for id in ("..", "1/../../users/@me", "", "1" * 21):
                edited = yield from reason(discord.edit(CHANNEL, id, markdown="x"))
                deleted = yield from reason(discord.delete(CHANNEL, id))
                assert [edited["tag"], deleted["tag"]] == ["InvalidRequest", "InvalidRequest"]
            assert calls(fake) == []

        return run

    return with_adapter({}, body)


# --- startThread -----------------------------------------------------------------------


@testing.effect
def test_names_the_thread_after_the_message_cut_to_100_characters():
    """startThread / names the thread after the message, cut to 100 characters"""

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from discord.start_thread(CHANNEL, THREAD_ID)) == THREAD
            assert (
                fake.called("createThreadFromMessage")[0][2]["name"]
                == ("first line second " + "x" * 200)[:100]
            )

        return run

    return with_adapter(
        {
            "getMessage": lambda *_: {**POSTED, "content": "  first line\nsecond " + "x" * 200},
            "createThreadFromMessage": lambda *_: step("history", "thread-start")["response"],
        },
        body,
    )


@testing.effect
def test_160004_gives_the_existing_thread_whose_id_is_the_messages():
    """startThread / 160004 gives the existing thread, whose id is the message's"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from discord.start_thread(CHANNEL, THREAD_ID, name="x")) == THREAD

        return run

    return with_adapter(
        {"createThreadFromMessage": lambda *_: answer(step("errors", "thread-start-again"))}, body
    )


@testing.effect
def test_50024_on_a_message_in_a_thread_gives_the_thread_and_elsewhere_fails():
    """startThread / 50024 on a message in a thread gives the thread, and elsewhere fails"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from discord.start_thread(THREAD, "1", name="x")) == THREAD
            failed = yield from reason(discord.start_thread(CHANNEL, "1", name="x"))
            assert failed["detail"] == "50024"

        return run

    return with_adapter(
        {
            "createThreadFromMessage": lambda *_: answer(
                step("errors", "forum-start-thread-again")
            ),
            "getChannel": one(
                lambda id: (
                    THREAD_CHANNEL
                    if id == THREAD_ID
                    else step("channels", "get-channel-dm")["response"]
                )
            ),
        },
        body,
    )


# --- history and opener ----------------------------------------------------------------


def list_from(all: list[dict[str, Any]]) -> Callable[..., object]:
    """``listMessages`` over ``all``, newest first, as Discord answers with either bound."""

    def answer_(_channel: str, params: dict[str, Any]) -> object:
        after, before = params.get("after"), params.get("before")
        found = [
            raw
            for raw in all
            if (after is None or int(raw["id"]) > int(after))
            and (before is None or int(raw["id"]) < int(before))
        ]
        found.sort(key=lambda raw: int(raw["id"]), reverse=True)
        return found[: params["limit"]]

    return answer_


@testing.effect
def test_history_pages_until_a_short_page():
    """history and opener / history pages until a short page"""
    many = [{**POSTED, "id": str(1570607253965246584 + i + 1)} for i in range(250)]

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            found = yield from discord.history(CHANNEL, direction="backward").run_collect()
            assert [message.id for message in found] == [raw["id"] for raw in reversed(many)]

        return run

    return with_adapter({"listMessages": list_from(many)}, body)


@testing.effect
def test_history_of_a_thread_started_from_a_message_has_its_opener_first_addressed_to_the_parent():
    """history and opener / history of a thread started from a message has its opener first,
    addressed to the parent"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            opener, *replies = yield from discord.history(THREAD, direction="forward").run_collect()
            assert [opener.id, opener.thread] == [THREAD_ID, CHANNEL]
            assert [message.id for message in replies] == [
                raw["id"] for raw in reversed(HISTORY["response"]) if raw["type"] != 21
            ]
            for message in replies:
                assert message.thread == THREAD

        return run

    return with_adapter({"listMessages": list_from(HISTORY["response"])}, body)


@testing.effect
def test_history_of_a_thread_whose_opener_was_deleted_starts_at_the_first_reply():
    """history and opener / history of a thread whose opener was deleted starts at the first
    reply"""
    deleted = step("history", "thread-deleted-history")["response"]
    deleted_thread = discord_chat.thread(step("history", "thread-deleted-start")["response"]["id"])

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            found = yield from discord.history(deleted_thread, direction="forward").run_collect()
            assert [message.id for message in found] == [
                next(raw for raw in deleted if raw["type"] == 0)["id"]
            ]

        return run

    return with_adapter({"listMessages": list_from(deleted)}, body)


@testing.effect
def test_opener_reads_the_message_in_the_parent_for_a_thread_started_from_a_message():
    """history and opener / opener reads the message in the parent for a thread started from a
    message"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            opener = yield from discord.opener(THREAD)
            assert opener is not None
            assert opener.id == THREAD_ID
            assert opener.thread == CHANNEL

        return run

    return with_adapter(
        {
            "getChannel": lambda *_: THREAD_CHANNEL,
            "getMessage": two(
                lambda channel_id, _id: answer(
                    step(
                        "history",
                        "thread-get-opener-by-thread-id"
                        if channel_id == THREAD_ID
                        else "thread-get-opener",
                    )
                )
            ),
        },
        body,
    )


@testing.effect
def test_opener_reads_a_forum_posts_starter_in_the_post():
    """history and opener / opener reads a forum post's starter in the post"""
    starter = step("history", "forum-get-starter")["response"]

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            opener = yield from discord.opener(discord_chat.thread(starter["id"]))
            assert opener is not None
            assert [opener.id, opener.thread.id] == [starter["id"], starter["id"]]

        return run

    return with_adapter(
        {
            "getChannel": lambda *_: step("history", "forum-post")["response"],
            "getMessage": lambda *_: starter,
        },
        body,
    )


@testing.effect
def test_opener_is_none_for_a_deleted_opener_and_for_a_channel():
    """history and opener / opener is None for a deleted opener and for a channel"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from discord.opener(THREAD)) is None
            assert (yield from discord.opener(CHANNEL)) is None

        return run

    return with_adapter(
        {
            "getChannel": one(
                lambda id: (
                    step("channels", "get-channel-text")["response"]
                    if id == SCRATCH
                    else THREAD_CHANNEL
                )
            ),
            "getMessage": lambda *_: answer(step("history", "thread-deleted-get-opener")),
        },
        body,
    )


@testing.effect
def test_history_skips_an_opener_the_bot_cant_read_and_starts_at_the_first_reply():
    """history and opener / history skips an opener the bot can't read and starts at the first
    reply"""
    starter = next(raw for raw in HISTORY["response"] if raw["type"] == 21)
    bare = {key: value for key, value in starter.items() if key != "referenced_message"}
    reply = next(raw for raw in HISTORY["response"] if raw["type"] == 0)

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            found = yield from discord.history(THREAD, direction="forward").run_collect()
            assert [message.id for message in found] == [reply["id"]]

        return run

    return with_adapter({"listMessages": lambda *_: [reply, bare], "getMessage": forbidden}, body)


@testing.effect
def test_opener_is_none_when_the_bot_cant_read_it():
    """history and opener / opener is None when the bot can't read it"""

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            assert (yield from discord.opener(THREAD)) is None

        return run

    return with_adapter({"getChannel": lambda *_: THREAD_CHANNEL, "getMessage": forbidden}, body)


# --- download --------------------------------------------------------------------------


@testing.effect
def test_download_reads_the_message_again_for_the_url_and_fails_too_large_past_max_bytes():
    """download reads the message again for the URL and fails TooLarge past maxBytes"""
    raw = step("posts", "attachment-fixed")["response"]
    attachment = Attachment(id=f"{raw['id']}/{raw['attachments'][0]['id']}")
    content = b"hello from effect/chat\n"

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            chunks = yield from discord.download(
                CHANNEL, attachment, max_bytes=len(content)
            ).run_collect()
            assert b"".join(chunks) == content
            assert fake.called("download")[0] == (raw["attachments"][0]["url"],)
            too_large = yield from reason(
                discord.download(CHANNEL, attachment, max_bytes=5).run_collect()
            )
            assert [too_large["tag"], too_large["detail"]] == ["TooLarge", "max_bytes"]

        return run

    return with_adapter({"getMessage": lambda *_: raw, "download": lambda *_: content}, body)


# --- getThread and getUser -------------------------------------------------------------


@testing.effect
def test_get_thread_gives_the_kind_name_and_parent():
    """getThread and getUser / getThread gives the kind, name and parent"""
    dm = step("channels", "get-channel-dm")["response"]

    def body(discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            info = yield from discord.get_thread(THREAD)
            assert [info.kind, info.name, info.parent] == [
                "thread",
                "Fixture thread from a message",
                CHANNEL,
            ]
            direct = yield from discord.get_thread(discord_chat.thread(dm["id"]))
            assert [direct.kind, direct.name] == ["direct", None]

        return run

    return with_adapter(
        {"getChannel": one(lambda id: THREAD_CHANNEL if id == THREAD_ID else dm)}, body
    )


@testing.effect
def test_get_user_with_in_gives_the_guild_nick_with_the_member_as_raw():
    """getThread and getUser / getUser with in gives the guild nick, with the member as raw"""
    member = {**step("users", "get-member-bot")["response"], "nick": "Janny"}

    def body(discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            user = yield from discord.get_user(BOT_USER_ID, in_=CHANNEL)
            assert user.name == "Janny"
            assert user.raw == member
            assert fake.called("getGuildMember") == [(GUILD, BOT_USER_ID)]
            assert (yield from discord.get_user(BOT_USER_ID)).name == "Janitor"

        return run

    return with_adapter(
        {
            "getChannel": lambda *_: step("channels", "get-channel-text")["response"],
            "getGuildMember": lambda *_: member,
            "getUser": lambda *_: answer(step("users", "get-user-bot")),
        },
        body,
    )


# --- dispatch without channel_type -----------------------------------------------------

MISSING = dispatch(events("channel-message-without-channel-type")[0])


def dispatcher(seen: list[ChatEvent]) -> Effect[Effect[None, NotAccepted], Any, Any]:
    """Dispatches ``MISSING`` through ``DiscordChat.dispatch``, keeping what the handler saw."""
    handler = HandlerService(lambda event: fx.sync(lambda: seen.append(event)))
    return discord_chat.DiscordChat().map(
        lambda discord: discord.dispatch(MISSING).pipe(fx.provide_service(ChatHandler, handler))
    )


@testing.effect
def test_looks_the_channel_up_once():
    """dispatch without channel_type / looks the channel up once"""

    def body(_discord: ChatAdapter, fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            seen: list[ChatEvent] = []
            send = yield from dispatcher(seen)
            yield from send
            yield from send
            assert [isinstance(e, MessageCreated) and e.kind for e in seen] == ["thread", "thread"]
            assert fake.called("getChannel") == [(SCRATCH,)]

        return run

    return with_adapter({"getChannel": lambda *_: THREAD_CHANNEL}, body)


@testing.effect
def test_fails_not_accepted_when_the_lookup_fails_and_tries_again_next_time():
    """dispatch without channel_type / fails NotAccepted when the lookup fails, and tries again
    next time"""
    attempts = [0]

    def get_channel(*_: object) -> object:
        attempts[0] += 1
        return (
            status_code_error(500)
            if attempts[0] <= 4
            else step("channels", "get-channel-text")["response"]
        )

    def body(_discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            seen: list[ChatEvent] = []
            send = yield from dispatcher(seen)
            fiber = yield from send.flip().fork()
            yield from testing.adjust("10 seconds")
            assert isinstance((yield from fiber.join()), NotAccepted)
            assert seen == []
            yield from send
            assert len(seen) == 1

        return run

    return with_adapter({"getChannel": get_channel}, body)


@testing.effect
def test_drops_the_event_when_the_lookup_is_denied():
    """dispatch without channel_type / drops the event when the lookup is denied"""

    def body(_discord: ChatAdapter, _fake: Fake) -> Effect[None, Any]:
        @fx.gen
        def run() -> Gen[None]:
            seen: list[ChatEvent] = []
            yield from (yield from dispatcher(seen))
            assert seen == []

        return run

    return with_adapter(
        {"getChannel": lambda *_: answer(step("errors", "get-channel-unknown"))}, body
    )


# --- max_retry_after -------------------------------------------------------------------


def _rate_limited(*_: object) -> object:
    return error_response(429, {"message": "You are being rate limited.", "retry_after": 1336.57})


@testing.effect
def test_a_429_past_max_retry_after_fails_at_once_with_its_wait():
    fake = Fake({"createMessage": _rate_limited})
    app = discord_layer(fake, max_retry_after="1 minute")

    @fx.gen
    def program() -> Gen[None]:
        discord: ChatAdapter = yield from adapter
        error = yield from discord.post(CHANNEL, markdown="alert").flip()
        assert isinstance(error.reason, RateLimited)
        assert error.retry_after == millis(1_336_570)
        assert len(fake.called("createMessage")) == 1

    return program.pipe(fx.provide(app))


@testing.effect
def test_a_429_within_max_retry_after_is_waited_out():
    answers = iter([_rate_limited(), POSTED])
    fake = Fake({"createMessage": lambda *_: next(answers)})
    app = discord_layer(fake, max_retry_after="1 hour")

    @fx.gen
    def program() -> Gen[None]:
        discord: ChatAdapter = yield from adapter
        fiber = yield from discord.post(CHANNEL, markdown="alert").fork()
        yield from testing.adjust("1337 seconds")
        yield from fiber.join()
        assert len(fake.called("createMessage")) == 2

    return program.pipe(fx.provide(app))
