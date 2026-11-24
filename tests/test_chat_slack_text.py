"""Port of Effect's ``packages/chat/slack/test/text.test.ts``: the CI half of
Slack's mention rule. The live rule checks stored messages; these check the
request bodies the adapter builds for ``chat.postMessage``, ``chat.update``
and stream appends over generated inputs."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Generator
from typing import Any, Literal

import pytest
from _slack_fake import CHANNEL, TEAM, Fake, adapter, slack_layer

import pyfect as fx
from pyfect import testing
from pyfect._core import Effect
from pyfect.chat import _graphemes
from pyfect.chat.chat_message import utf16_length, utf16_slice
from pyfect.chat.slack import _text, slack_chat
from pyfect.chat.slack._escape import NOBODY, Notify, escape
from pyfect.chat.slack._options import SlackPostOptions
from pyfect.chat.slack._text import Budget

type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]


def code_points(text: str) -> int:
    return len(text)


def utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def is_boundary(text: str, index: int) -> bool:
    return index == len(text) or index in _graphemes.starts(text[: index + 1])


def words(alphabet: list[str], length: int) -> list[str]:
    if length == 0:
        return [""]
    return [word + piece for word in words(alphabet, length - 1) for piece in alphabet]


def options(notify: Notify) -> SlackPostOptions:
    return SlackPostOptions(
        notify_users=tuple(notify.users),
        notify_groups=tuple(notify.groups),
        notify_broadcast=notify.broadcast,
    )


REQUEST_THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL)
ALLOWED = Notify(users=("U1",), broadcast=True)

# Pieces that spell tokens, entity forms, code and multi-unit characters.
REQUEST_ALPHABET = ["<", "@U1", "!here", ">", "&", "lt;", "`", "x", "👍🏽", "\n"]
SHORT = [word for n in (1, 2, 3) for word in words(REQUEST_ALPHABET, n)]
WITH_TOKEN = [word for word in SHORT if "<" in word]


def allowed_tokens(notify: Notify) -> list[str]:
    """The tokens ``notify`` lets through, of those the alphabet can spell."""
    return (["<@U1>"] if "U1" in notify.users else []) + (["<!here>"] if notify.broadcast else [])


def long(word: str, notify: Notify) -> str:
    """Repeats ``word`` until the text is past both budgets while the block
    stays within 12,000."""

    def sent(markdown: str) -> int:
        return code_points(escape(markdown, notify, flush=True).sent)

    times = 11_900 // sent(word)
    while sent(word * times) > 12_000:
        times //= 2
    return word * times


ENTITY = re.compile(r"[<>]|&(?!lt;|gt;|amp;)")


def check(
    op: Literal["post", "edit"], markdown: str, notify: Notify, params: dict[str, str], whole: str
) -> None:
    """``whole`` is the uncut text, ``build`` with no budget."""
    label = f"{op} {markdown[:40]!r} {notify}"
    block: str = json.loads(params["blocks"])[0]["text"]
    text = params["text"]
    assert "markdown_text" not in params, label
    assert len(text) > 0, label
    if op == "post":
        assert code_points(text) <= _text.POST_TEXT_LENGTH, label
    else:
        assert utf8_bytes(text) <= _text.UPDATE_TEXT_BYTES, label
    # No token survives in text but an allowed one, and every & starts an entity.
    rest = text
    for token in allowed_tokens(notify):
        rest = rest.replace(token, "")
    assert ENTITY.search(rest) is None, label
    # An allowed token the block sends intact is in text too, cut or not.
    for token in allowed_tokens(notify):
        if token in block:
            assert token in text, label
    # A cut is a prefix of the whole text, on a grapheme boundary and outside an entity.
    if text != whole:
        head = text[: text.rindex("…")]
        assert whole.startswith(head), label
        assert re.search(r"&[a-z]*$", head) is None, label
        assert is_boundary(whole, len(head)), label


# Effect's one test, in parts that run on separate workers: the generated
# inputs for each notify value, and the padded inputs, each dealt round-robin
# into slices so every slice holds short and long inputs alike. Together the
# slices are every input. Each part takes under a quarter of a second.
REQUEST_PARTS = {"nobody": 5, "allowed": 8, "allowed-padded": 4}


def request_inputs(notify: Notify, padded: bool, part: int, parts: int) -> list[str]:
    """Slice ``part`` of ``parts`` of the generated inputs."""
    if padded:
        # 3,300 `&` are 16,500 code points of text, so a token in the word is
        # past either cut.
        return ["&" * 3_300 + word for word in WITH_TOKEN[part::parts]]
    specs = [
        *((word, False) for word in SHORT),
        *((word, True) for n in (1, 2) for word in words(REQUEST_ALPHABET, n)),
    ]
    return [long(word, notify) if is_long else word for word, is_long in specs[part::parts]]


def test_the_request_parts_cover_every_generated_input():
    for padded, total in ((False, len(SHORT) + 110), (True, len(WITH_TOKEN))):
        for parts in set(REQUEST_PARTS.values()):
            sliced = [
                word
                for part in range(parts)
                for word in request_inputs(NOBODY, padded, part, parts)
            ]
            assert len(sliced) == total
            assert sorted(sliced) == sorted(request_inputs(NOBODY, padded, 0, 1))


@pytest.mark.parametrize(
    ("notify", "padded", "part", "parts"),
    [
        pytest.param(notify, padded, part, REQUEST_PARTS[name], id=f"{name}-{part}")
        for name, notify, padded in (
            ("nobody", NOBODY, False),
            ("allowed", ALLOWED, False),
            ("allowed-padded", ALLOWED, True),
        )
        for part in range(REQUEST_PARTS[name])
    ],
)
@testing.effect
def test_hold_the_mention_budget_and_cut_rules_over_a_generated_alphabet(
    notify: Notify, padded: bool, part: int, parts: int
):
    """request bodies / hold the mention, budget and cut rules over a generated alphabet"""
    fake = Fake({"chat.postMessage": {"ok": True, "channel": CHANNEL, "ts": "1.1"}})
    inputs = request_inputs(notify, padded, part, parts)

    @fx.gen
    def program() -> Gen[None]:
        slack = yield from adapter
        count = 0
        cuts = {"post": 0, "edit": 0}
        for markdown in inputs:
            whole = _text.build(markdown, notify, Budget("code_points", sys.maxsize)).text
            for op in ("post", "edit"):
                before = len(fake.calls)
                # A new message id for each edit, so pacing never waits.
                write = (
                    slack.post(REQUEST_THREAD, markdown=markdown).as_void()
                    if op == "post"
                    else slack.edit(REQUEST_THREAD, f"1.{count + 2}", markdown=markdown)
                )
                yield from write.pipe(slack_chat.with_post_options(options(notify)))
                call = fake.calls[-1]
                assert len(fake.calls) == before + 1
                assert call.method == ("chat.postMessage" if op == "post" else "chat.update")
                check(op, markdown, notify, call.params, whole)
                if "…" in call.params["text"]:
                    cuts[op] += 1
                count += 1
        assert count == 2 * len(inputs)
        if padded:
            assert cuts == {"post": len(inputs), "edit": len(inputs)}
        else:
            # The long inputs in every slice reach both budgets.
            assert cuts["post"] > 0
            assert cuts["edit"] > 0

    return program.pipe(fx.provide(slack_layer(fake)))


STREAM_THREAD = slack_chat.thread(team=TEAM, channel=CHANNEL, thread_ts="1794509110.999799")
TOKEN = re.compile(
    r"<(?:@[UW][A-Z0-9]+|!subteam\^[A-Z0-9]+|!(?:here|channel|everyone))(?:\|[^<>]*)?>"
)


def decode(text: str) -> str:
    """Slack's decoding on a stream, in code too, which is wider than Slack."""
    text = re.sub(r"&(?:lt|LT|#0*60|#[xX]0*3[cC]);", "<", text)
    text = re.sub(r"&(?:commat|#0*64|#[xX]0*40);", "@", text)
    return re.sub(r"&(?:excl|#0*33|#[xX]0*21);", "!", text)


def tokens(text: str) -> list[str]:
    return TOKEN.findall(decode(text))


STREAM_ALPHABET = [
    "<",
    "&lt;",
    "&l",
    "t;",
    "&lt",
    "@U1",
    "&commat;",
    "!",
    "here",
    "`",
    "\n",
    "x",
    ">",
    "👍🏽",
]
# Whole tokens, which the generated words are too short to spell.
SEEDS = [
    "<@U1>",
    "<!here>",
    "&lt;@U1>",
    "<&commat;U1>",
    "&#x3C;!here>",
    "`<@U1>`",
    "&#0000000000000060;@U1>",
    "&#x00000000003c;&#00000000064;U1>",
    "<@U1|hello world>",
    "&lt@U1> &#60@U1>",
]


# Each notify value's words, dealt round-robin into slices that run on
# separate workers. Together the slices are every word.
STREAM_WORDS = [*SEEDS, *(w for n in (1, 2) for w in words(STREAM_ALPHABET, n))]
STREAM_PARTS = 6


def test_the_stream_parts_cover_every_word():
    sliced = [word for part in range(STREAM_PARTS) for word in STREAM_WORDS[part::STREAM_PARTS]]
    assert sorted(sliced) == sorted(STREAM_WORDS)
    assert len(STREAM_WORDS) == len(SEEDS) + 14 + 14 * 14


@pytest.mark.parametrize(
    ("notify", "part"),
    [
        pytest.param(notify, part, id=f"{name}-{part}")
        for name, notify in (("nobody", NOBODY), ("u1", Notify(users=("U1",))))
        for part in range(STREAM_PARTS)
    ],
)
@testing.effect
def test_hold_the_mention_rule_at_every_split_and_leave_no_u200b_after_the_stream(
    notify: Notify, part: int
):
    """stream bodies / hold the mention rule at every split, and leave no U+200B after the stream"""
    count = 0

    def start_stream(_: dict[str, Any]) -> dict[str, Any]:
        # A new message for each stream, so the edit pacing never waits.
        nonlocal count
        count += 1
        return {"ok": True, "channel": CHANNEL, "ts": f"1.{count}"}

    fake = Fake({"chat.startStream": start_stream})

    @fx.gen
    def program() -> Gen[None]:
        native = (yield from adapter).native_stream
        assert native is not None
        cleaned = 0

        def allowed(found: str, notify: Notify = notify) -> bool:
            return bool(notify.users) and re.match(r"^<@U1[|>]", found) is not None

        for word in STREAM_WORDS[part::STREAM_PARTS]:
            # Every split in UTF-16 units, as JavaScript slices, so a
            # surrogate pair can be cut.
            length = utf16_length(word)
            for at in range(length + 1):
                for across in ("appends", "start"):
                    label = f"{word!r} at {at} across {across} {notify}"
                    before = len(fake.calls)
                    first = utf16_slice(word, 0, at)
                    rest = utf16_slice(word, at, length)

                    @fx.gen
                    def run(
                        first: str = first, rest: str = rest, across: str = across
                    ) -> Gen[None]:
                        if across == "start":
                            started = yield from native.start(
                                STREAM_THREAD, markdown="s " + first, recipient="U080YLYB277"
                            )
                            yield from native.append(STREAM_THREAD, started.id, rest, flush=True)
                            yield from native.stop(STREAM_THREAD, started.id, end="done")
                            return
                        started = yield from native.start(
                            STREAM_THREAD, markdown="s ", recipient="U080YLYB277"
                        )
                        appended = yield from native.append(STREAM_THREAD, started.id, first)
                        held = first[len(first) - appended.held :] if appended.held else ""
                        yield from native.append(STREAM_THREAD, started.id, held + rest, flush=True)
                        yield from native.stop(STREAM_THREAD, started.id, end="done")

                    yield from run.pipe(slack_chat.with_post_options(options(notify)))
                    calls = fake.calls[before:]
                    streamed = "".join(
                        call.params["markdown_text"]
                        for call in calls
                        if call.method != "chat.update" and call.params.get("markdown_text")
                    )
                    if across == "appends":
                        # Held text keeps every allowed token whole, and nothing else.
                        whole = "s " + word
                        assert tokens(streamed) == [t for t in tokens(whole) if allowed(t)], label
                    else:
                        # The start holds nothing, so it may break an allowed token,
                        # but never makes one.
                        assert [t for t in tokens(streamed) if not allowed(t)] == [], label
                    update = next((call for call in calls if call.method == "chat.update"), None)
                    left = (
                        streamed
                        if update is None
                        else update.params["blocks"] + update.params["text"]
                    )
                    assert "\u200b" not in left, label
                    if update is not None:
                        cleaned += 1
        assert cleaned > 0

    return program.pipe(fx.provide(slack_layer(fake)))
