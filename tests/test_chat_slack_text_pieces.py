"""Ports of Effect's ``packages/chat/slack/test`` ``escape.test.ts``,
``actions.test.ts`` and ``emoji.test.ts``: the escaping that keeps a post from
notifying anyone it may not, the ``actions`` block's charge against Slack's
13,200 character cap, and the emoji table."""

from __future__ import annotations

import re
from collections.abc import Callable

from pyfect.chat.chat_message import utf16_length, utf16_slice
from pyfect.chat.slack import slack_chat
from pyfect.chat.slack._actions import (
    ButtonElement,
    Element,
    SelectElement,
    SelectOptionJson,
    cost,
    option,
)
from pyfect.chat.slack._emoji import blocks_cost
from pyfect.chat.slack._emoji_data import EMOJI_DATA
from pyfect.chat.slack._escape import NOBODY, Notify, escape


def sent(text: str, notify: Notify = NOBODY) -> str:
    return escape(text, notify, flush=True).sent


def test_escapes_lt_outside_code_only() -> None:
    """escape / escapes < outside code only"""
    assert sent("a <@U1> b") == "a &lt;@U1> b"
    assert sent("`<@U1>` and ``x <!here> y``") == "`<@U1>` and ``x <!here> y``"
    assert sent("```\n<@U1>\n```\n<@U1>") == "```\n<@U1>\n```\n&lt;@U1>"
    assert sent("~~~ts\nif (a < b) {}\n~~~") == "~~~ts\nif (a < b) {}\n~~~"
    assert sent("a `b < c") == "a `b &lt; c"
    assert sent("\\<@U1>") == "\\&lt;@U1>"


def test_keeps_the_tokens_the_notify_options_allow() -> None:
    """escape / keeps the tokens the notify options allow"""
    notify = Notify(users=("U1",), groups=("S1",), broadcast=True)
    assert (
        sent("<@U1> <@U2> <!subteam^S1> <!subteam^S2> <!here>", notify)
        == "<@U1> &lt;@U2> <!subteam^S1> &lt;!subteam^S2> <!here>"
    )
    assert sent("<@U1|name>", Notify(users=("U1",))) == "<@U1|name>"
    assert sent("<!channel>") == "&lt;!channel>"


def opts(
    n: int,
    label: Callable[[int], str] = lambda i: f"Option {i}",
    value: Callable[[int], str] = lambda i: f"o{i}",
) -> list[SelectOptionJson]:
    return [option(label(i), value(i)) for i in range(1, n + 1)]


def select(
    *,
    id: str = "sel1",
    ph: str | None = "Pick one",
    options: list[SelectOptionJson] | None = None,
    initial: SelectOptionJson | None = None,
) -> Element:
    element: SelectElement = {
        "type": "static_select",
        "action_id": id,
        "options": opts(3) if options is None else options,
    }
    if ph is not None:
        element["placeholder"] = {"type": "plain_text", "text": ph}
    if initial is not None:
        element["initial_option"] = initial
    return element


def button(
    *,
    id: str = "eff3738_noop",
    label: str = "Test button",
    url: str | None = None,
    value: str | None = "v",
) -> Element:
    element: ButtonElement = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": id,
    }
    if url is not None:
        element["url"] = url
    if value is not None:
        element["value"] = value
    return element


def one(label: str) -> list[SelectOptionJson]:
    return opts(1, lambda _: label, lambda _: "a")


# Name, elements, what Slack charged, and whether every string in it is ASCII.
ROWS: list[tuple[str, list[Element], int, bool]] = [
    ("V1", [select(options=one("A"), ph=None)], 173, True),
    ("V2", [select(options=one("A"))], 240, True),
    ("V6", [select(options=opts(10, lambda _: "A", lambda _: "a"))], 843, True),
    ("V10", [select(options=opts(3), initial=option("Option 2", "o2"))], 490, True),
    ("V15", [button(), select(options=opts(3)), button(id="b2")], 628, True),
    ("V18", [select(options=one("é" * 20))], 359, False),
    ("V20", [button()], 170, True),
    ("V21", [button(url="https://effect.website/docs", value=None)], 197, True),
    ("V22", [button(url="https://effect.website/docs", value="v")], 209, True),
    ("W1", [button(label="é" * 20)], 279, False),
    ("W2", [button(label="\U0001f644")], 183, False),
    ("W4", [select(options=one("A"), ph="\U0001f644")], 256, False),
    ("W8", [button(label="<&>" * 10)], 289, True),
    ("W13", [select(options=one("\U0001d49c" * 5))], 299, False),
]


def test_is_never_below_what_slack_charged_and_at_most_5_over_on_ascii_for_the_measured_rows() -> (
    None
):
    """actionsCost / is never below what Slack charged, and at most 5 over on ASCII, for the
    measured rows"""
    for name, elements, charged, ascii in ROWS:
        charge = cost(elements)
        assert charge >= charged, name
        if ascii:
            assert charge <= charged + 5, name


def _decode(hex: str) -> str:
    return "".join(chr(int(point, 16)) for point in hex.split("-"))


def _written(emoji: str, non_qualified: str | None) -> list[str]:
    return [emoji, emoji.replace("️", "")] if non_qualified == "!" else [emoji]


def _sequences() -> list[str]:
    """Every emoji string the table defines, read from the table directly so
    the fuzz does not trust ``_emoji`` to parse it."""
    found: list[str] = []
    for line in EMOJI_DATA.split("\n"):
        fields = line.split("|")
        if len(fields) < 2:
            continue
        unified = fields[1]
        non_qualified = fields[2] if len(fields) > 2 else None
        groups = fields[3] if len(fields) > 3 else None
        found += _written(_decode(unified), non_qualified)
        if groups is None:
            continue
        for group in groups.split(";"):
            keys, template, *rest = group.split(":")
            variation_non_qualified = rest[0] if rest else None
            for tones in keys.split(","):
                digits = iter(tones)
                emoji = _decode(
                    re.sub(
                        r"\*",
                        lambda _, digits=digits: format(0x1F3FB + int(next(digits)) - 2, "x"),
                        template,
                    )
                )
                found += _written(emoji, variation_non_qualified)
    return found


def test_gives_a_single_tone_or_the_same_tone_twice_where_upstream_keys_only_by_two() -> None:
    """emoji / gives a single tone, or the same tone twice where upstream keys only by two"""
    assert slack_chat.emoji_from_name("handshake::skin-tone-3") == "🤝🏼"
    assert slack_chat.emoji_from_name("people_holding_hands::skin-tone-4") == "🧑🏽‍🤝‍🧑🏽"
    assert slack_chat.emoji_from_name("people_holding_hands::skin-tone-1") is None


def _js(text: str) -> str:
    """A JavaScript string's code points: a high and a low surrogate that end
    up side by side become one character, as they do in UTF-16."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def test_blocks_cost_is_subadditive() -> None:
    """emoji / blocksCost is subadditive"""
    extras = ["a", " ", "1", "#", "‍", "️", "⃣", "🏽", "🇺", "🇸", "🦰", "\U000e0067"]
    extras += ["\ud83d", "\ude00"]
    sequences = _sequences()
    seed = 1

    def random(n: int) -> int:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed % n

    def piece() -> str:
        kind = random(3)
        if kind == 0:
            return extras[random(len(extras))]
        sequence = sequences[random(len(sequences))]
        if kind == 1:
            return sequence
        length = utf16_length(sequence)
        start = random(length + 1)
        end = random(length + 1)
        return utf16_slice(sequence, min(start, end), max(start, end))

    for _ in range(20_000):
        text = ""
        for _ in range(1 + random(8)):
            text = _js(text + piece())
        cut = random(utf16_length(text) + 1)
        a = utf16_slice(text, 0, cut)
        b = utf16_slice(text, cut, utf16_length(text))
        assert blocks_cost(text) <= blocks_cost(a) + blocks_cost(b), (a, b)
