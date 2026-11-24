"""Port of Effect's ``test/chat/ChatMarkdown.test.ts``: ``post`` splits long
Markdown at block boundaries; ``stream`` writes deltas natively, by
post-then-edit or by posting each part once, and finishes what it received
when the deltas fail or the call is interrupted.

One case differs: Python strings hold code points, so "holds a grapheme
cluster split across deltas inside a fence" splits a flag between its two
regional indicators, not inside a UTF-16 surrogate pair."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import stream, testing
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.chat import chat_interaction as ci
from pyfect.chat import chat_markdown, chat_test
from pyfect.chat.chat import Chat
from pyfect.chat.chat_adapter import ChatAdapter, File, NativeStream, Registry
from pyfect.chat.chat_error import (
    Forbidden,
    RateLimited,
    TooLarge,
    Transport,
    Unknown,
    Unsupported,
)
from pyfect.chat.chat_markdown import ChatCause, ChatMarkdownError, OverflowFile, Part, Result
from pyfect.chat.chat_message import ReplyTo
from pyfect.chat.chat_test import ChatTest, NoSuchElement
from pyfect.chat.chat_thread import ChatThread
from pyfect.chat.chat_ui import Action
from pyfect.deferred import Deferred
from pyfect.duration import millis, seconds
from pyfect.queue import Done, Queue

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def joined(parts: Sequence[Part]) -> str:
    return "".join(part.text for part in parts)


def paragraphs(count: int, size: int) -> str:
    return "\n\n".join(f"Paragraph {i} ".ljust(size, "x") for i in range(count))


settle = fx.for_each(range(50), lambda _: fx.yield_now(), discard=True)


@fx.gen
def setup() -> Gen[tuple[chat_test.Service, ChatThread]]:
    test = yield from ChatTest()
    thread = yield from test.make_thread()
    return test, thread


def texts(test: chat_test.Service, thread: ChatThread) -> Effect[list[str]]:
    return test.messages(thread).map(lambda messages: [m.text for m in messages])


def chat_layer(**options: Any):
    return fx.provide(chat_test.layer(**options))


@dataclass
class Feed:
    fiber: Fiber[Result, ChatMarkdownError[str]]
    queue: Queue[str, str | Done]

    def send(self, chunk: str) -> Effect[None]:
        return self.queue.offer(chunk).and_then(settle)

    def fail(self, error: str) -> Effect[None]:
        return self.queue.fail(error).and_then(settle)

    @property
    def close(self) -> Effect[None]:
        return self.queue.end().and_then(settle)

    @property
    def end(self) -> Effect[Result, ChatMarkdownError[str]]:
        return self.queue.end().and_then(self.fiber.join())


def feed(thread: ChatThread, **options: Any) -> Effect[Feed, Never_, Any]:
    """Runs ``stream`` over a queue the test feeds, ends or fails."""

    @fx.gen
    def run() -> Gen[Feed]:
        queue: Queue[str, str | Done] = yield from Queue[str, str | Done].unbounded()
        fiber = yield from chat_markdown.stream(thread, stream.from_queue(queue), **options).fork()
        return Feed(fiber, queue)

    return run


Never_ = Any


class _Override:
    """An object with some members replaced, as ``{ ...object, ... }``."""

    def __init__(self, base: object, **members: Any) -> None:
        self._base = base
        self._members = members

    def __getattr__(self, name: str) -> Any:
        return self._members[name] if name in self._members else getattr(self._base, name)


def patch_native(f: Callable[[NativeStream], dict[str, Any]]) -> Effect[None, Any, Any]:
    """Registers the test adapter with its native stream changed by ``f``."""

    @fx.gen
    def run() -> Gen[None]:
        test = yield from ChatTest()
        registry = yield from Registry()
        adapter: ChatAdapter = yield from registry.get(test.platform)
        native = adapter.native_stream
        assert native is not None
        yield from registry.register(
            _Override(adapter, native_stream=_Override(native, **f(native)))  # pyright: ignore[reportArgumentType]
        )

    return run


@dataclass
class Hold:
    entered: Deferred[None]
    release: Deferred[None]


def hold_first(op: Literal["append", "stop"]) -> Effect[Hold, Any, Any]:
    """Holds the first native ``append`` or ``stop`` until ``release``."""

    @fx.gen
    def run() -> Gen[Hold]:
        entered = yield from Deferred[None].make()
        release = yield from Deferred[None].make()
        first = [True]

        def hold(effect: Effect[Any, Any]) -> Effect[Any, Any]:
            def go() -> Effect[Any, Any]:
                if not first[0]:
                    return effect
                first[0] = False
                return entered.succeed(None).and_then(release.wait()).and_then(effect)

            return fx.suspend(go)

        def patched(native: NativeStream) -> dict[str, Any]:
            def held(*args: Any, **kwargs: Any) -> Effect[Any, Any]:
                return hold(getattr(native, op)(*args, **kwargs))

            return {op: held}

        yield from patch_native(patched)
        return Hold(entered, release)

    return run


FILES = (File("a.txt", "text/plain", b"a"),)
BUTTON = ci.button("go", label="Go").of()


def costing(cost: int) -> Callable[[str, Sequence[Action]], int]:
    """One element costs ``cost``, so a test can leave as little room
    beside it as it needs."""
    return lambda markdown, actions=(): len(markdown) + cost * len(actions)


def _chat_reason(error: ChatMarkdownError[Any]) -> str | None:
    cause = error.cause
    return cause.error.reason._tag if isinstance(cause, ChatCause) else None  # pyright: ignore[reportPrivateUsage]


# --- post ----------------------------------------------------------------------------


@testing.effect
def test_splits_at_block_boundaries():
    """post / splits at block boundaries"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        text = paragraphs(10, 40)
        result = yield from chat_markdown.post(thread, text, max_parts=10)
        assert len(result.parts) > 1
        assert joined(result.parts) == text
        for part in result.parts:
            assert len(part.markdown) <= 100
        for part in result.parts[:-1]:
            assert part.text.endswith("\n\n"), part.text
        assert (yield from texts(test, thread)) == [p.markdown for p in result.parts]

    return program.pipe(chat_layer(message_length=100))


@testing.effect
def test_keeps_a_fenced_block_that_exactly_fits_in_one_message():
    """post / keeps a fenced block that exactly fits in one message"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        block = "```\nx\n```\n"
        yield from chat_markdown.post(thread, block + "rest", max_parts=2)
        assert (yield from texts(test, thread)) == [block, "rest"]

    return program.pipe(chat_layer(message_length=10))


@testing.effect
def test_closes_a_code_fence_and_reopens_it_in_the_next_part():
    """post / closes a code fence and reopens it in the next part"""

    @fx.gen
    def program() -> Gen[None]:
        _test, thread = yield from setup
        text = "```ts\n" + "const a = 1\n" * 10 + "```\n"
        result = yield from chat_markdown.post(thread, text)
        assert len(result.parts) > 1
        assert joined(result.parts) == text
        assert result.parts[0].markdown.endswith("\n```"), result.parts[0].markdown
        for part in result.parts[1:]:
            assert part.markdown.startswith("```ts\n"), part.markdown
        for part in result.parts:
            assert len(part.markdown) <= 60

    return program.pipe(chat_layer(message_length=60))


@testing.effect
def test_replies_with_the_first_part_only():
    """post / replies with the first part only"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        event = yield from test.user_posts(thread, text="question")
        reply_to = ReplyTo(message_id=event.message.id)
        result = yield from chat_markdown.post(thread, paragraphs(3, 20), reply_to=reply_to)
        messages = {m.id: m for m in (yield from test.messages(thread))}
        replies = [messages[p.message_id].reply_to for p in result.parts]
        assert [r.message_id if r else None for r in replies] == [event.message.id, None, None]

    return program.pipe(chat_layer(message_length=30))


@testing.effect
def test_remaining_fence_is_the_fence_remaining_was_cut_in():
    """post / remainingFence is the fence remaining was cut in, and reopening it gives the
    rest back"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        code = "\n".join(f"const line{i} = {i}" for i in range(6))
        text = "Intro\n\n~~~ts title\n" + code + "\n~~~\n\nOutro"
        error = yield from chat_markdown.post(thread, text, max_parts=2).flip()
        assert error.cause._tag == "Overflow"  # pyright: ignore[reportPrivateUsage]
        assert joined(error.posted) + error.remaining == text
        assert error.remaining.startswith("const line"), error.remaining
        assert error.remaining_fence == "~~~ts title"
        # Sent again with the fence reopened, the thread reads as the input does.
        yield from chat_markdown.post(thread, error.remaining_fence + "\n" + error.remaining)
        sent = yield from texts(test, thread)
        assert all(len(re.findall(r"^~~~", t, re.MULTILINE)) % 2 == 0 for t in sent)
        lines = [line for t in sent for line in t.split("\n") if line.startswith("const line")]
        assert lines == code.split("\n")

    return program.pipe(chat_layer(message_length=60))


@testing.effect
def test_ends_in_the_unattached_note_when_the_files_are_refused():
    """post / ends in the unattached note when the files are refused"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next("post", Forbidden(detail="file_refused"))
        result = yield from chat_markdown.post(
            thread,
            "Report",
            files=FILES,
            unattached_note=lambda files: f"\n\n({len(files)} file not attached)",
        )
        assert [(p.markdown, p.text) for p in result.parts] == [
            ("Report\n\n(1 file not attached)", "Report")
        ]
        messages = yield from test.messages(thread)
        assert [len(m.attachments) for m in messages] == [0]

    return program.pipe(chat_layer())


@testing.effect
def test_fails_on_a_too_large_that_does_not_blame_the_files():
    """post / fails on a TooLarge that does not blame the files"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next("post", TooLarge(detail="msg_blocks_too_long"))
        error = yield from chat_markdown.post(
            thread, "Report", files=FILES, unattached_note=lambda _: " (file not attached)"
        ).flip()
        assert _chat_reason(error) == "TooLarge"
        assert (error.posted, error.uncertain, error.remaining) == ((), None, "Report")
        assert (yield from texts(test, thread)) == []

    return program.pipe(chat_layer())


@testing.effect
def test_does_not_post_a_note_for_an_uncertain_file_write():
    """post / does not post a note for an uncertain file write"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next(
            "post", Transport(retry="uncertain", detail="file_refused"), landed=True
        )
        error = yield from chat_markdown.post(
            thread, "Report", files=FILES, unattached_note=lambda _: " (file not attached)"
        ).flip()
        assert (error.posted, error.uncertain, error.remaining) == ((), "Report", "")
        assert (yield from texts(test, thread)) == ["Report"]

    return program.pipe(chat_layer())


@testing.effect
def test_keeps_the_files_and_blank_text_that_follow_the_last_cut():
    """post / keeps the files and blank text that follow the last cut"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        text = "abcde\n\n"
        result = yield from chat_markdown.post(thread, text, files=FILES)
        assert [(p.markdown, p.text) for p in result.parts] == [("abcde", text)]
        messages = yield from test.messages(thread)
        assert [len(m.attachments) for m in messages] == [1]

    return program.pipe(chat_layer(message_length=5))


@testing.effect
def test_preserves_overflow_as_text_when_files_are_refused():
    """post / preserves overflow as text when files are refused"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.refuse_files(times=2)
        text = paragraphs(5, 20)
        result = yield from chat_markdown.post(
            thread,
            text,
            files=FILES,
            max_parts=1,
            overflow=OverflowFile("rest.md"),
            unattached_note=lambda _: " (not attached)",
        )
        assert joined(result.parts) == text
        messages = yield from test.messages(thread)
        assert "".join(m.text for m in messages) == text + " (not attached)"
        assert all(len(m.attachments) == 0 for m in messages)

    return program.pipe(chat_layer(message_length=30))


@testing.effect
def test_sends_the_files_with_the_overflow_file():
    """post / sends the files with the overflow file"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        text = paragraphs(5, 20)
        result = yield from chat_markdown.post(
            thread, text, files=FILES, max_parts=2, overflow=OverflowFile("rest.md")
        )
        assert [p.kind for p in result.parts] == ["text", "text", "overflowFile"]
        assert joined(result.parts) == text
        last = (yield from test.messages(thread))[-1]
        assert [a.name for a in last.attachments] == ["rest.md", "a.txt"]

    return program.pipe(chat_layer(message_length=30))


@testing.effect
def test_fails_too_large_before_posting_when_the_actions_alone_do_not_fit():
    """post / fails TooLarge before posting when the actions alone do not fit"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        error = yield from chat_markdown.post(thread, "a", actions=(BUTTON,)).flip()
        assert _chat_reason(error) == "TooLarge"
        assert (yield from test.messages(thread)) == ()

    return program.pipe(chat_layer(message_length=9, measure=costing(10)))


@testing.effect
def test_fills_the_parts_before_the_last_one_without_leaving_room_for_the_actions():
    """post / fills the parts before the last one without leaving room for the actions"""

    @fx.gen
    def program() -> Gen[None]:
        test, _thread = yield from setup
        thread = _thread
        result = yield from chat_markdown.post(thread, "a" * 25, actions=(BUTTON,))
        assert [p.text for p in result.parts] == ["a" * 24, "a"]
        yield from test.click(result.parts[1].message_id, "go")

    return program.pipe(chat_layer(message_length=30, measure=costing(29)))


@testing.effect
def test_posts_the_actions_in_a_message_of_their_own_when_no_text_fits_beside_them():
    """post / posts the actions in a message of their own when no text fits beside them"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        result = yield from chat_markdown.post(thread, "Hello", actions=(BUTTON,), files=FILES)
        assert [p.text for p in result.parts] == ["Hello", ""]
        messages = yield from test.messages(thread)
        assert [(m.text, len(m.attachments)) for m in messages] == [("Hello", 0), ("", 1)]
        missing = yield from test.click(result.parts[0].message_id, "go").flip()
        assert isinstance(missing, NoSuchElement)
        yield from test.click(result.parts[1].message_id, "go")

    return program.pipe(chat_layer(message_length=30, measure=costing(30)))


@testing.effect
def test_fails_overflow_when_the_actions_own_message_has_no_part_left():
    """post / fails Overflow when the actions' own message has no part left"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        error = yield from chat_markdown.post(
            thread, "Hello", actions=(BUTTON,), max_parts=1
        ).flip()
        assert error.cause._tag == "Overflow"  # pyright: ignore[reportPrivateUsage]
        assert ([p.text for p in error.posted], error.remaining) == (["Hello"], "")
        assert len((yield from test.messages(thread))) == 1

    return program.pipe(chat_layer(message_length=30, measure=costing(30)))


@testing.effect
def test_moves_the_actions_to_an_unattached_note_posted_on_its_own():
    """post / moves the actions to an unattached note posted on its own"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next("post", Forbidden(detail="file_refused"))
        result = yield from chat_markdown.post(
            thread, "a" * 20, actions=(BUTTON,), files=FILES, unattached_note=lambda _: " note"
        )
        assert [p.markdown for p in result.parts] == ["a" * 20, " note"]
        missing = yield from test.click(result.parts[0].message_id, "go").flip()
        assert isinstance(missing, NoSuchElement)
        yield from test.click(result.parts[1].message_id, "go")

    return program.pipe(chat_layer(message_length=30, measure=costing(10)))


@testing.effect
def test_posts_the_actions_after_an_unattached_note_that_has_no_room_for_them():
    """post / posts the actions after an unattached note that has no room for them"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next("post", Forbidden(detail="file_refused"))
        result = yield from chat_markdown.post(
            thread,
            "a" * 20,
            actions=(BUTTON,),
            files=FILES,
            unattached_note=lambda _: "n" * 25,
        )
        assert [p.markdown for p in result.parts] == ["a" * 20, "n" * 25, ""]
        for part in result.parts[:2]:
            missing = yield from test.click(part.message_id, "go").flip()
            assert isinstance(missing, NoSuchElement)
        yield from test.click(result.parts[2].message_id, "go")

    return program.pipe(chat_layer(message_length=30, measure=costing(10)))


@testing.effect
def test_never_cuts_inside_a_grapheme_cluster_on_a_hard_cut():
    """post / never cuts inside a grapheme cluster on a hard cut"""

    @fx.gen
    def program() -> Gen[None]:
        _test, thread = yield from setup
        # The 10th character is the "e" of "é", and the flag is two code points of one
        # cluster.
        text = "aaaaaaaaaébbbbbbb\U0001f1ef\U0001f1f5cc"
        result = yield from chat_markdown.post(thread, text)
        assert joined(result.parts) == text
        assert [p.text for p in result.parts] == [
            "aaaaaaaaa",
            "ébbbbbbb",
            "\U0001f1ef\U0001f1f5cc",
        ]

    return program.pipe(chat_layer(message_length=10))


@testing.effect
def test_keeps_message_text_out_of_the_errors_message_and_json():
    """post / keeps message text out of the error's message and JSON"""

    @fx.gen
    def program() -> Gen[None]:
        _test, thread = yield from setup
        error = yield from chat_markdown.post(thread, paragraphs(5, 20), max_parts=1).flip()
        assert "Paragraph" not in error.message
        assert "Paragraph" not in str(error)
        assert "Paragraph" not in repr(error.to_json())

    return program.pipe(chat_layer(message_length=30))


# --- stream --------------------------------------------------------------------------


@testing.effect
def test_posts_each_part_once_when_it_is_final_without_edit():
    """stream / posts each part once, when it is final, without edit"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread)
        yield from f.send("one\n\n")
        assert (yield from test.calls) == ()
        yield from f.send("two " * 10 + "\n\nthree")
        result = yield from f.end
        assert [p.transport for p in result.parts] == ["post", "post"]
        assert (yield from texts(test, thread)) == ["one\n\n" + "two " * 10 + "\n\n", "three"]

    return program.pipe(chat_layer(capabilities=["files"], message_length=50))


@testing.effect
def test_writes_natively_with_a_recipient_sending_held_text_again():
    """stream / writes natively with a recipient, sending held text again"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send("hello\n")
        yield from f.send("x < y\n")
        yield from f.send("```ts\ncode")
        result = yield from f.end
        assert [(p.transport, p.text) for p in result.parts] == [
            ("native", "hello\nx < y\n```ts\ncode")
        ]
        assert (yield from texts(test, thread)) == ["hello\nx < y\n```ts\ncode\n```"]
        calls = yield from test.calls
        assert [(c.op, c.markdown) for c in calls] == [
            ("nativeStream.start", "hello\n"),
            ("nativeStream.append", "x < y\n"),
            ("nativeStream.append", "< y\n```ts\ncod"),
            ("nativeStream.append", "< y\n```ts\ncode\n```"),
            ("nativeStream.stop", None),
        ]

    return program.pipe(chat_layer())


@pytest.mark.parametrize(
    ("where", "prefix", "first", "rest", "whole", "close"),
    [
        # A delta that ends in half a flag, inside a fence where whole lines are not held.
        ("inside a fence", "~~~\n", "\U0001f1fa", "\U0001f1f8", "\U0001f1fa\U0001f1f8", "\n~~~"),
        # A line past the hold limit with no whitespace to release up to.
        ("in a long line", "x" * 301, "1", "\ufe0f\u20e3", "1\ufe0f\u20e3", ""),
    ],
    ids=["inside a fence", "in a long line"],
)
@testing.effect
def test_holds_a_grapheme_cluster_split_across_deltas(  # noqa: PLR0917
    where: str,
    prefix: str,
    first: str,
    rest: str,
    whole: str,
    close: str,
):
    """stream / holds a grapheme cluster split across deltas"""
    del where

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send(prefix + first)
        assert [c.markdown for c in (yield from test.calls)] == [prefix]
        yield from f.send(rest + "\n")
        assert [c.markdown for c in (yield from test.calls)] == [prefix, whole + "\n"]
        yield from f.send("z")
        result = yield from f.end
        assert joined(result.parts) == prefix + whole + "\nz"
        assert (yield from texts(test, thread)) == [prefix + whole + "\nz" + close]

    return program.pipe(chat_layer())


@testing.effect
def test_rolls_a_native_stream_over_at_a_block_boundary():
    """stream / rolls a native stream over at a block boundary"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        text = paragraphs(6, 28) + "\n\n"
        for chunk in re.split(r"(?<=\n\n)", text):
            if chunk:
                yield from f.send(chunk)
        result = yield from f.end
        assert len(result.parts) > 1
        assert joined(result.parts) == text
        for part in result.parts:
            assert part.transport == "native"
            assert part.text.endswith("\n\n"), part.text
        messages = yield from texts(test, thread)
        assert messages == [p.markdown for p in result.parts]
        for message in messages:
            assert len(message) <= 100

    return program.pipe(chat_layer(message_length=100))


@testing.effect
def test_forces_a_rollover_on_a_too_large_append():
    """stream / forces a rollover on a TooLarge append"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send("one\n")
        yield from test.fail_next("nativeStream.append", TooLarge(detail="msg_too_long"))
        yield from f.send("two\n")
        result = yield from f.end
        assert [p.text for p in result.parts] == ["one\n", "two\n"]
        assert (yield from texts(test, thread)) == ["one\n", "two\n"]

    return program.pipe(chat_layer())


@testing.effect
def test_falls_back_to_post_then_edit_when_the_start_is_unsupported_closing_an_open_fence():
    """stream / falls back to post-then-edit when the start is Unsupported, closing an open
    fence"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        yield from test.fail_next("nativeStream.start", Unsupported(capability="nativeStream"))
        result = yield from chat_markdown.stream(
            thread, stream.make("one\n", "```ts\ncode"), recipient="U1"
        )
        assert [p.transport for p in result.parts] == ["edit"]
        assert (yield from texts(test, thread)) == ["one\n```ts\ncode\n```"]

    return program.pipe(chat_layer())


def _collect_ids(ids: list[str]) -> Callable[[Part], Effect[None]]:
    return lambda part: fx.sync(lambda: ids.append(part.message_id))


@testing.effect
def test_ends_the_reply_stopped_when_an_append_comes_back_stopped():
    """stream / ends the reply stopped when an append comes back stopped"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        ids: list[str] = []
        f = yield from feed(thread, recipient="U1", on_part=_collect_ids(ids))
        yield from f.send("one\n")
        yield from test.click_stop(ids[0])
        yield from test.close_stream(ids[0])
        yield from f.send("two\n")
        result = yield from f.fiber.join()
        assert result.stopped
        assert joined(result.parts) == "one\n"

    return program.pipe(chat_layer())


@testing.effect
def test_carries_on_by_edit_when_the_stream_is_closed():
    """stream / carries on by edit when the stream is closed"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        ids: list[str] = []
        f = yield from feed(thread, recipient="U1", on_part=_collect_ids(ids))
        yield from f.send("one\n")
        yield from test.close_stream(ids[0])
        yield from f.send("two\n")
        result = yield from f.end
        assert [(p.transport, p.text) for p in result.parts] == [("native", "one\ntwo\n")]
        assert (yield from texts(test, thread)) == ["one\ntwo\n"]

    return program.pipe(chat_layer())


@testing.effect
def test_does_not_post_again_when_interrupted_while_on_part_runs():
    """stream / does not post again when interrupted while onPart runs"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        entered = yield from Deferred[None].make()
        release = yield from Deferred[None].make()

        def on_part(_part: Part) -> Effect[None]:
            return entered.succeed(None).and_then(release.wait())

        f = yield from feed(thread, recipient="U1", on_part=on_part)
        yield from f.send("hello\n")
        yield from entered.wait()
        interrupt = yield from f.fiber.interrupt().fork()
        yield from settle
        yield from release.succeed(None)
        yield from interrupt.join()
        assert (yield from texts(test, thread)) == ["hello\n"]
        assert "nativeStream.stop" in [c.op for c in (yield from test.calls)]

    return program.pipe(chat_layer())


@testing.effect
def test_repairs_with_the_retried_chunk_while_the_upstream_is_paused():
    """stream / repairs with the retried chunk while the upstream is paused"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send("one\n")
        yield from test.fail_next(
            "nativeStream.append", RateLimited(retry_after=millis(100)), times=3
        )
        yield from f.send("two\n")
        yield from testing.adjust("200 millis")
        yield from settle
        ops = [c.op for c in (yield from test.calls)]
        assert ops.count("nativeStream.append") == 3
        assert "nativeStream.stop" in ops
        assert (yield from texts(test, thread)) == ["one\ntwo\n"]

    return program.pipe(chat_layer())


@testing.effect
def test_partitions_an_uncertain_repair_followed_by_a_denied_edit():
    """stream / partitions an uncertain repair followed by a denied edit"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send("one\n")
        yield from test.fail_next("nativeStream.append", Unknown(), landed=True)
        yield from test.fail_next("edit", Unknown(), landed=True)
        yield from f.send("two\n")
        yield from test.fail_next("edit", Forbidden())
        yield from f.send("three\n")
        error = yield from f.fiber.join().flip()
        assert (joined(error.posted), error.uncertain, error.remaining) == (
            "one\n",
            "two\n",
            "three\n",
        )

    return program.pipe(chat_layer())


@testing.effect
def test_leaves_room_in_a_native_stream_to_close_a_code_fence():
    """stream / leaves room in a native stream to close a code fence"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread, recipient="U1")
        yield from f.send("~~~\n")
        yield from f.send("a" * 16)
        result = yield from f.end
        assert joined(result.parts) == "~~~\n" + "a" * 16
        messages = yield from texts(test, thread)
        assert len(messages) > 1
        for message in messages:
            assert message.endswith("\n~~~"), message
            assert len(message) <= 20

    return program.pipe(chat_layer(message_length=20))


@testing.effect
def test_takes_the_text_that_arrived_while_waiting_for_the_write_interval():
    """stream / takes the text that arrived while waiting for the write interval"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        f = yield from feed(thread)
        yield from f.send("a\n")
        yield from f.send("b\n")
        yield from f.send("c\n")
        yield from testing.adjust("1 second")
        yield from settle
        calls = yield from test.calls
        assert [(c.op, c.markdown) for c in calls] == [("post", "a\n"), ("edit", "a\nb\nc\n")]
        ended = yield from f.end.fork()
        yield from settle
        yield from testing.adjust("1 second")
        result = yield from ended.join()
        assert joined(result.parts) == "a\nb\nc\n"

    return program.pipe(chat_layer(min_write_interval=seconds(1)))


@testing.effect
def test_a_rotated_streams_start_names_the_part_it_continues():
    """stream / a rotated stream's start names the part it continues"""

    @fx.gen
    def program() -> Gen[None]:
        _test, thread = yield from setup
        continues: list[str | None] = []

        def patched(native: NativeStream) -> dict[str, Any]:
            def start(thread: ChatThread, **options: Any) -> Effect[Any, Any]:
                def go() -> Effect[Any, Any]:
                    continues.append(options.get("continues"))
                    return native.start(thread, **options)

                return fx.suspend(go)

            return {"start": start}

        yield from patch_native(patched)
        f = yield from feed(thread, recipient="U1")
        yield from f.send("one\n")
        yield from testing.adjust("9 minutes")
        yield from f.send("two\n")
        result = yield from f.end
        assert continues == [None, result.parts[0].message_id]

    return program.pipe(chat_layer())


@testing.effect
def test_sends_a_stop_again_when_interrupted_during_it():
    """stream / sends a stop again when interrupted during it"""

    @fx.gen
    def program() -> Gen[None]:
        _test, thread = yield from setup
        chat = yield from Chat()
        held = yield from hold_first("stop")
        ids: list[str] = []
        f = yield from feed(thread, recipient="U1", on_part=_collect_ids(ids))
        yield from f.send("hello\n")
        yield from f.close
        yield from held.entered.wait()
        yield from f.fiber.interrupt()
        # An open native stream would refuse the edit.
        yield from chat.edit(thread, ids[0], markdown="edited")

    return program.pipe(chat_layer())


@testing.effect
def test_keeps_a_rollover_due_after_an_append_that_was_in_flight_when_interrupted():
    """stream / keeps a rollover due after an append that was in flight when interrupted"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        held = yield from hold_first("append")
        f = yield from feed(thread, recipient="U1")
        yield from f.send("~~~\none\n")
        yield from testing.adjust("9 minutes")
        yield from f.send("two\n")
        yield from held.entered.wait()
        interrupt = yield from f.fiber.interrupt().fork()
        yield from settle
        yield from held.release.succeed(None)
        yield from interrupt.join()
        assert (yield from texts(test, thread)) == ["~~~\none\n~~~", "~~~\ntwo\n~~~"]

    return program.pipe(chat_layer())


@testing.effect
def test_bounds_an_append_in_flight_when_the_upstream_fails():
    """stream / bounds an append in flight when the upstream fails"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        held = yield from hold_first("append")
        f = yield from feed(thread, recipient="U1")
        yield from f.send("one\n")
        yield from f.send("two\n")
        yield from held.entered.wait()
        yield from f.fail("boom")
        yield from testing.adjust("6 seconds")
        finished = f.fiber.poll_unsafe() is not None
        yield from held.release.succeed(None)
        error = yield from f.fiber.join().flip()
        assert finished
        assert error.cause == chat_markdown.UpstreamCause("boom")
        assert (joined(error.posted), error.uncertain, error.remaining) == ("one\n", "two\n", "")
        yield from settle
        assert (yield from texts(test, thread)) == ["one\n"]

    return program.pipe(chat_layer())


@testing.effect
def test_stops_the_stream_after_a_denied_append_when_the_upstream_then_fails():
    """stream / stops the stream after a denied append when the upstream then fails"""

    @fx.gen
    def program() -> Gen[None]:
        test, thread = yield from setup
        chat = yield from Chat()
        held = yield from hold_first("stop")
        ids: list[str] = []
        f = yield from feed(thread, recipient="U1", on_part=_collect_ids(ids))
        yield from f.send("one\n")
        yield from test.fail_next("nativeStream.append", Forbidden())
        yield from f.send("two\n")
        yield from held.entered.wait()
        yield from f.fail("boom")
        yield from held.release.succeed(None)
        error = yield from f.fiber.join().flip()
        assert _chat_reason(error) == "Forbidden"
        assert (joined(error.posted), error.uncertain, error.remaining) == ("one\n", None, "two\n")
        assert (yield from texts(test, thread)) == ["one\n"]
        # An open native stream would refuse the edit.
        yield from chat.edit(thread, ids[0], markdown="edited")

    return program.pipe(chat_layer())
